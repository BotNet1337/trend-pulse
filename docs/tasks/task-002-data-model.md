---
id: TASK-002
title: Data model — SQLAlchemy 2.0 модели, Alembic baseline, multi-tenancy (pgvector)
status: in-progress    # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "310b28d5cae15e0249090e8902f57b0add443f66"
branch: "gsd/phase-002-data-model"
tags: [backend, storage, sqlalchemy, alembic, pgvector, multi-tenancy]
---

# TASK-002 — Data model (SQLAlchemy 2.0 · Alembic · pgvector · multi-tenancy)

> Заложить доменную схему хранения TrendPulse: SQLAlchemy 2.0 модели (`users`, `channels`, `watchlists`, `posts`, `clusters`, `scores`, `alerts`), baseline Alembic-миграцию, ОПРЕДЕЛЯЮЩУЮ схему (включая vector-колонки) — расширение `vector` ставит `pg_vector_provisioner`, миграцию ПРИМЕНЯЕТ `migration_runner` (one-shot провижинеры из task-001, [ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md)), user-scoped репозитории (ADR-002) и Redis-клиент — фундамент для auth/collector/pipeline/scorer.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): мульти-тенантный SaaS поверх PostgreSQL+pgvector. task-001 поднял окружение (uv·Docker·make·ruff/pytest, образ `pgvector/pgvector:pg16`, Alembic в deps). Кода схемы ещё нет — это первая доменная задача эпика A, от неё зависят почти все остальные (auth, watchlist, collector, pipeline, scorer — см. [`../architecture/roadmap.md`](../architecture/roadmap.md)).

Схема обязана быть **multi-source ready** ([ADR-001](../architecture/adr-001-source-abstraction.md)): `channels` — глобальная таблица источников с колонкой `source_kind` (default `telegram`), чтобы Twitter/X подключился без миграций ядра. И **multi-tenant** ([ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md)): все пользовательские таблицы несут `user_id` FK→`users` с `ON DELETE CASCADE`, репозитории требуют `user_id` обязательным параметром — нет «глобальных» выборок пользовательских данных. Retention: сырой контент постов TTL'ится (Redis/temp), в Postgres — метрики + векторы + кластеры (overview §7, ADR-002 §4).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) (full type hints, SQL только через SQLAlchemy bind-params, размерность эмбеддинга фиксирована и совпадает с колонкой, tz-aware UTC, секреты из env).

## Goal

После задачи в пакете `trendpulse.storage` есть: SQLAlchemy 2.0 модели всех семи сущностей (typed `Mapped[...]`, `DeclarativeBase`), baseline Alembic-миграция, ОПРЕДЕЛЯЮЩАЯ все таблицы и vector-колонки, user-scoped репозитории и Redis-клиент. Расширение `vector` ставит `pg_vector_provisioner`, миграцию применяет `migration_runner` (ADR-005, заведены в task-001) — НЕ inline в старте приложения. `make migrate` (root, прогоняет `migration_runner`) применяет миграцию на готовой к `vector` БД; `make ci-fast` зелёный; round-trip запись/чтение поста с эмбеддингом фиксированной размерности проходит; удаление юзера каскадно вычищает все его строки. DoD — Acceptance Criteria ниже.

## Schema (ER diagram)

```mermaid
erDiagram
    users ||--o{ watchlists : has
    users ||--o{ posts : owns
    users ||--o{ clusters : owns
    users ||--o{ scores : owns
    users ||--o{ alerts : owns
    users ||--o{ subscriptions : has
    channels ||--o{ watchlists : referenced_by
    channels ||--o{ posts : produces
    clusters ||--o{ scores : scored_by
    clusters ||--o{ alerts : triggers

    users {
        int id PK
        string email UK
        datetime created_at "tz-aware UTC"
    }
    channels {
        int id PK
        string source_kind "StrEnum default=telegram"
        string handle
        datetime created_at "tz-aware UTC"
        UK source_kind_handle "(source_kind, handle)"
    }
    watchlists {
        int id PK
        int user_id FK "→ users.id ON DELETE CASCADE"
        int channel_id FK "→ channels.id"
        string topic
        float threshold "alert config"
        int min_channels "alert config"
        string lang "alert config"
        UK user_channel_topic "(user_id, channel_id, topic)"
    }
    posts {
        int id PK
        int user_id FK "→ users.id ON DELETE CASCADE"
        int channel_id FK "→ channels.id"
        string external_id
        int views "metric"
        int forwards "metric"
        int reactions "metric"
        vector embedding "Vector(EMBEDDING_DIM=384), nullable cache"
        string text "nullable, TTL'd — NOT long-term"
        datetime posted_at "tz-aware UTC"
        datetime fetched_at "tz-aware UTC"
    }
    clusters {
        int id PK
        int user_id FK "→ users.id ON DELETE CASCADE"
        string topic
        vector embedding "pgvector Vector(EMBEDDING_DIM=384)"
        datetime first_seen "tz-aware UTC"
        datetime updated_at "tz-aware UTC"
    }
    scores {
        int id PK
        int user_id FK "→ users.id ON DELETE CASCADE"
        int cluster_id FK "→ clusters.id"
        float velocity
        float engagement
        float cross_channel
        float viral_score
        datetime computed_at "tz-aware UTC"
    }
    alerts {
        int id PK
        int user_id FK "→ users.id ON DELETE CASCADE"
        int cluster_id FK "→ clusters.id"
        float score
        int channels_count
        datetime first_seen "tz-aware UTC"
        datetime delivered_at "tz-aware UTC"
    }
    subscriptions {
        int id PK
        int user_id FK "→ users.id (forward-ref, owned by billing task-010)"
        string plan
        datetime expires_at "tz-aware UTC"
    }
```

> `subscriptions` показана для полноты картины (forward-ref): её схема и владение — за биллинг-задачей **task-010**, эта задача её НЕ создаёт. Остальные семь сущностей — предмет данной задачи.

## Discussion
<!-- durable record of clarifications. Решения приняты по дефолтам overview/ADR; обратимы. -->
- Q: Фиксированная размерность эмбеддинга? → A: модель эмбеддинга — sentence-transformers MiniLM (overview §4) → Decision: **`EMBEDDING_DIM = 384`** именованной константой в `storage/models/clusters.py` (`all-MiniLM-L6-v2` = 384). Колонка `clusters.embedding Vector(EMBEDDING_DIM)`; pipeline (task-007) обязан матчить (rationale: CONVENTIONS «match pgvector embedding dimension», arch §7 «pgvector dimension drift» → константа + проверка).
- Q: Где живёт вектор — на `posts` или `clusters`? → A: кластеризация (overview §4) оперирует центроидами кластеров → Decision: pgvector-колонка **на `clusters`** (`embedding`); `posts` несут опциональный `embedding` (nullable) как кэш пер-пост вектора. Оба — `Vector(EMBEDDING_DIM)` (rationale: scorer/cluster работают с кластерами; пер-пост вектор полезен для re-clustering, но не обязателен).
- Q: Хранить ли сырой текст постов долгосрочно? → A: НЕТ (overview §7, ADR-002 §4: TTL ≤ 48h) → Decision: `posts` хранит метрики + опц. вектор + ссылки (`external_id`, `channel_id`, `posted_at`); поле сырого `text` либо отсутствует, либо nullable и чистится retention-задачей (task-011). Эта задача НЕ реализует TTL-cron — только схему, допускающую её.
- Q: `channels` — глобальная или per-user? → A: cross-tenant дедуп источников (ADR-002 §3) → Decision: **`channels` глобальная** (без `user_id`), связь с юзерами через junction `watchlists`. Колонка `source_kind` (StrEnum, default `telegram`) + уникальность `(source_kind, handle)` (rationale: канал читается один раз для всех юзеров).
- Q: Где alert-config (threshold/min_channels/lang)? → A: настройка per watchlist (overview §3) → Decision: поля `threshold`, `min_channels`, `lang` живут на `watchlists` (junction user↔channel↔topic), не на `users` (rationale: алерты настраиваются на уровне топика/списка, не аккаунта).
- Q: ON DELETE поведение? → A: «удаление аккаунта вычищает все строки одним каскадом» (ADR-002 §4) → Decision: все user-owned FK → `users.id` с `ondelete="CASCADE"` (`watchlists`, `posts`, `clusters`, `scores`, `alerts`); `channels` — без `user_id`, не каскадится по юзеру.
- Q: Драйвер/синхронность для миграций и репозиториев? → A: Alembic классически синхронный; collector/pipeline async → Decision: **миграции и репозитории на sync SQLAlchemy + `psycopg`** в этой задаче (минимальный диф, тестируемо); async-сессии — отдельно, если понадобится в task-005/007 (rationale: не тащить async-инфраструктуру в фундамент схемы; sync покрывает миграцию + round-trip тесты).
- Q: tz-aware datetimes? → A: CONVENTIONS + ADR-001 (`posted_at` tz-aware UTC) → Decision: все datetime-колонки `DateTime(timezone=True)`, дефолты `datetime.now(UTC)` (не `utcnow()`); хранение в UTC.

## Scope
> **Раскладка:** трогаем **только `backend/`** (пакет `trendpulse.storage`) + один make-таргет/тест. landing/frontend/collector/pipeline/api не затрагиваются — это чистый слой хранения.

- **Touch ONLY (создать):**
  - `apps/trendPulse/backend/src/trendpulse/storage/__init__.py` — публичный реэкспорт `Base`, моделей, репозиториев.
  - `apps/trendPulse/backend/src/trendpulse/storage/database.py` — `engine`/`SessionLocal` фабрика из `config.Settings.database_url`, `get_session` контекст.
  - `apps/trendPulse/backend/src/trendpulse/storage/models/__init__.py` — `Base = DeclarativeBase`, реэкспорт всех моделей, `EMBEDDING_DIM` константа.
  - `apps/trendPulse/backend/src/trendpulse/storage/models/users.py` — `User` (id, email unique, created_at).
  - `apps/trendPulse/backend/src/trendpulse/storage/models/channels.py` — `Channel` (id, `source_kind` default `telegram`, handle; unique `(source_kind, handle)`) — **глобальная** (ADR-001).
  - `apps/trendPulse/backend/src/trendpulse/storage/models/watchlists.py` — `Watchlist` (junction `user_id`↔`channel_id` + `topic` + alert-config `threshold`/`min_channels`/`lang`).
  - `apps/trendPulse/backend/src/trendpulse/storage/models/posts.py` — `Post` (user_id, channel_id, external_id, metrics-поля, optional `embedding Vector`, posted_at/fetched_at; raw text nullable/TTL'd — НЕ долгосрочно).
  - `apps/trendPulse/backend/src/trendpulse/storage/models/clusters.py` — `Cluster` (user_id, topic, `embedding Vector(EMBEDDING_DIM)`, first_seen/updated_at) + `EMBEDDING_DIM = 384`.
  - `apps/trendPulse/backend/src/trendpulse/storage/models/scores.py` — `Score` (user_id, cluster_id, velocity/engagement/cross_channel/viral_score, computed_at).
  - `apps/trendPulse/backend/src/trendpulse/storage/models/alerts.py` — `Alert` (user_id, cluster_id, score, channels_count, first_seen, delivered_at).
  - `apps/trendPulse/backend/src/trendpulse/storage/repositories/__init__.py`, `base.py` (generic CRUD), `watchlist_repo.py`, `cluster_repo.py`, `alert_repo.py` — **все user-scoped методы требуют `user_id`** (ADR-002); `channel_repo.py` — глобальный (без `user_id`).
  - `apps/trendPulse/backend/src/trendpulse/storage/redis_client.py` — обёртка над `redis` (фабрика из `Settings.redis_url`, типизированный клиент).
  - `apps/trendPulse/backend/alembic.ini`, `apps/trendPulse/backend/alembic/env.py`, `apps/trendPulse/backend/alembic/script.py.mako`, `apps/trendPulse/backend/alembic/versions/0001_baseline.py` — baseline ОПРЕДЕЛЯЕТ все таблицы + vector-колонки + индексы (`user_id`, `(source_kind, handle)`); расширение `vector` уже стоит к моменту применения (его ставит `pg_vector_provisioner`, ADR-005). Миграция содержит `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` идемпотентно-defensive (no-op при уже установленном расширении), но штатно расширение приходит от провижинера, а саму миграцию ПРИМЕНЯЕТ `migration_runner` — НЕ старт приложения.
  - `apps/trendPulse/backend/tests/conftest.py` (расширить: фикстура тест-БД/сессии), `tests/integration/test_migrations.py`, `tests/integration/test_repositories.py`, `tests/unit/test_models.py`.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`, `backend/src/trendpulse/api/**`, `collector/**`, `pipeline/**`, `alerts/**`, `celery_app.py`, `scheduler.py`. Никакой бизнес-логики коллектора/scorer — только слой хранения. `config.py` трогаем минимально лишь если `database_url`/`redis_url` отсутствуют (в task-001 заведены — проверить, не дублировать).
- **Blast radius:** задаёт контракт данных для всего бэкенда — имена таблиц/колонок, FK-каскады, размерность вектора (384), сигнатуры репозиториев (`user_id`-обязательность). Потребители: task-003 (auth → `users`), task-004 (watchlist API), task-005 (collector → `channels`/`posts`), task-007 (pipeline → `clusters`), task-008 (scorer → `scores`/`alerts`), task-011 (retention/GDPR-delete опирается на каскад).

## Acceptance Criteria
- [ ] **AC1 — модели и контракт (RED-якорь).** Given нет схемы, When `tests/unit/test_models.py` (пишется ПЕРВЫМ, RED): импортирует `Base` + 7 моделей, проверяет `Cluster.embedding` типа `Vector(384)`, наличие `user_id` FK с `ondelete="CASCADE"` на user-owned таблицах, отсутствие `user_id` на `Channel`, Then тест сначала падает (модулей нет), после реализации — зелёный.
- [ ] **AC2 — миграция применяется `migration_runner`'ом на тест-БД.** Given тест-БД (pgvector-образ) с уже установленным расширением `vector` (ставит `pg_vector_provisioner`, ADR-005), When `alembic upgrade head` (через `make migrate`, т.е. `migration_runner` / фикстуру — НЕ inline в старте app), Then все таблицы созданы, exit 0, `alembic current` == baseline revision.
- [ ] **AC3 — расширение `vector` присутствует (ставит провижинер).** Given БД, провижиненная `pg_vector_provisioner`'ом (ADR-005) до миграции, When `SELECT 1 FROM pg_extension WHERE extname = 'vector'`, Then ровно одна строка. Расширение создаёт `pg_vector_provisioner`, НЕ старт приложения; defensive `CREATE EXTENSION IF NOT EXISTS vector` в миграции остаётся no-op-safe.
- [ ] **AC4 — round-trip с эмбеддингом.** Given применённая схема, When записать `User`→`Channel`→`Post`/`Cluster` с `embedding` вектором длины `EMBEDDING_DIM` (384) и прочитать обратно, Then вектор читается той же размерности и значениями (в пределах float-точности), запись/чтение через репозиторий с `user_id`.
- [ ] **AC5 — каскадное удаление тенанта.** Given юзер с `watchlists`/`posts`/`clusters`/`scores`/`alerts`, When `DELETE FROM users WHERE id = :uid` (или `repo.delete_user`), Then все строки этих таблиц с данным `user_id` удалены (count == 0); `channels` остаются (глобальные).
- [ ] **AC6 — user-scoped репозитории.** Given две сущности разных юзеров, When `cluster_repo.list(session, user_id=A)`, Then возвращаются только строки юзера A; методы user-owned репозиториев не имеют перегрузки без `user_id` (нет глобальных выборок) — ADR-002.
- [ ] **AC7 — tz-aware UTC.** Given сохранённая строка с datetime, When прочитать `posted_at`/`created_at`, Then значение `tzinfo` не `None` и нормализуется к UTC (все datetime-колонки `DateTime(timezone=True)`).
- [ ] **AC8 — CI зелёный.** Given реализация, When `make ci-fast` (ruff+mypy+`pytest -m 'not integration'`), Then exit 0; mypy без `Any`/`type: ignore` (CONVENTIONS).

## Plan
1. `tests/unit/test_models.py` (RED) — импорт `Base` + 7 моделей, ассерты на `Vector(384)`, `user_id`-каскад на user-owned, отсутствие `user_id` на `Channel`. Прогнать → падает (AC1).
2. `storage/models/__init__.py` — `class Base(DeclarativeBase)`, `EMBEDDING_DIM = 384`, реэкспорт. Затем по файлу на сущность: `users.py`, `channels.py` (`source_kind` StrEnum default `telegram`, unique `(source_kind, handle)`), `watchlists.py` (junction + `threshold`/`min_channels`/`lang`), `posts.py` (метрики + nullable `embedding Vector`, raw text nullable), `clusters.py` (`embedding Vector(EMBEDDING_DIM)`), `scores.py`, `alerts.py`. Все datetime — `DateTime(timezone=True)` + `default=lambda: datetime.now(UTC)`; user-owned FK → `users.id` `ondelete="CASCADE"`. → test_models зелёный.
3. `storage/database.py` — `create_engine(settings.database_url)`, `SessionLocal`, `get_session()` контекстменеджер. `storage/__init__.py` — публичный реэкспорт.
4. `storage/repositories/base.py` — generic `Repository` (findById/list/create/delete) на сессии; `watchlist_repo.py`/`cluster_repo.py`/`alert_repo.py` — методы с обязательным `user_id` (фильтр в `where`); `channel_repo.py` — глобальный (get-or-create по `(source_kind, handle)`). `redis_client.py` — фабрика клиента из `settings.redis_url`.
5. `alembic.ini` + `alembic/env.py` (target_metadata = `Base.metadata`, url из `Settings`) + `script.py.mako`. `alembic/versions/0001_baseline.py` ОПРЕДЕЛЯЕТ схему: первой операцией defensive-`op.execute("CREATE EXTENSION IF NOT EXISTS vector")` (no-op, т.к. штатно расширение уже стоит от `pg_vector_provisioner` — ADR-005), затем `create_table` для всех семи (вектор-колонки через `pgvector.sqlalchemy.Vector`), индексы по `user_id` и `(source_kind, handle)`. Применяет миграцию `migration_runner`, НЕ старт app.
6. Root `Makefile` — убедиться, что `make migrate` прогоняет `migration_runner` (`alembic upgrade head` в one-shot контейнере провижинера) и что `pg_vector_provisioner` ставит расширение до него (заведены в task-001 по ADR-005; при отсутствии таргета/провижинера — НЕ создавать здесь, это scope task-001).
7. `tests/conftest.py` — фикстура тест-БД: применяет миграцию (или `Base.metadata.create_all` для unit), отдаёт сессию, откатывает/дропает после. Маркер `integration` для тестов с реальной БД.
8. `tests/integration/test_migrations.py` — `alembic upgrade head` на тест-БД → проверка `pg_extension` (AC3) и наличия таблиц (AC2).
9. `tests/integration/test_repositories.py` — round-trip с вектором длины 384 (AC4), каскадное удаление юзера (AC5), user-scoping (AC6), tz-aware (AC7).
10. Прогнать `make ci-fast` (AC8); поднять инфру (`make dev-infra-up` → postgres + `pg_vector_provisioner`) и `make migrate` (`migration_runner`) на живой БД, проверить AC2/AC3 вживую (G2).

## Invariants
- **`user_id` обязателен** во всех user-scoped запросах репозиториев; нет публичного метода выборки пользовательских данных без `user_id` (ADR-002).
- Все user-owned FK → `users.id` объявлены с `ondelete="CASCADE"`; `channels` — глобальная, без `user_id`.
- **`EMBEDDING_DIM = 384`** — единый источник правды размерности; колонки `Vector(EMBEDDING_DIM)`; pipeline обязан матчить (CONVENTIONS, arch §7).
- `source_kind` на `channels` (default `telegram`), unique `(source_kind, handle)` — schema multi-source с первого дня (ADR-001); ядро не привязано к Telegram.
- Все datetime-колонки `DateTime(timezone=True)`, значения tz-aware UTC (`datetime.now(UTC)`, не naive/`utcnow`).
- Сырой контент постов НЕ хранится долгосрочно — схема допускает TTL/чистку (task-011), но эта задача его не персистит как постоянное поле.
- SQL только через SQLAlchemy/Alembic bind-params; никаких f-string SQL (CONVENTIONS). Full type hints, mypy strict, без `Any`/`type: ignore`.
- Расширение `vector` ставит `pg_vector_provisioner`, миграции применяет `migration_runner` — оба one-shot провижинеры из task-001 (ADR-005). Старт приложения НЕ делает `CREATE EXTENSION` и НЕ гонит миграции inline. Миграция лишь ОПРЕДЕЛЯЕТ схему (включая vector-колонки); defensive `CREATE EXTENSION IF NOT EXISTS` в ней — no-op-safe, не источник истины.
- Управление окружением и миграциями — только через root `make …` (`make migrate`, `make dev-infra-up`, ADR-005/CONVENTIONS), не raw `docker compose`/`alembic`.

## Edge cases
- pgvector-тип в Alembic autogenerate не распознаётся из коробки → в baseline-ревизии импортировать `from pgvector.sqlalchemy import Vector` и объявлять колонки явно; не полагаться на autogenerate для вектора.
- `vector`-тип должен быть зарегистрирован в БД ДО `create_table` с `Vector`, иначе `create_table` упадёт. Штатно расширение ставит `pg_vector_provisioner` до запуска `migration_runner` (ADR-005); defensive `CREATE EXTENSION IF NOT EXISTS vector` идёт ПЕРВОЙ операцией миграции как страховка (в т.ч. для тест-фикстур, поднимающих БД без провижинера). `CREATE EXTENSION` требует прав — провижинер ходит под ролью, у которой они есть.
- Размерность вектора при вставке ≠ `EMBEDDING_DIM` → Postgres бросит ошибку; тест AC4 фиксирует ровно 384 — защита от drift.
- Каскад работает только если FK объявлен с `ondelete="CASCADE"` И БД его уважает — для ORM-каскада нужен также `passive_deletes=True` на relationship либо DB-level FK; полагаемся на DB-level `ON DELETE CASCADE` (тест AC5 проверяет реальный DELETE).
- Тест-БД должна быть на pgvector-образе (`pgvector/pgvector:pg16`), не голый `postgres` — иначе `CREATE EXTENSION` упадёт (как в task-001 AC5).
- Naive datetime, попавший в `DateTime(timezone=True)`, тихо трактуется как локальный → всегда вставлять tz-aware UTC; тест AC7 ловит `tzinfo is None`.
- Junction `watchlists`: уникальность `(user_id, channel_id, topic)` чтобы не плодить дубли подписок одного юзера на канал в рамках топика.

## Test plan
- **unit:** `tests/unit/test_models.py` — импорт `Base`+модели, тип/размерность `Vector(384)`, наличие/отсутствие `user_id`, `ondelete="CASCADE"`, tz-aware дефолты (пишется ПЕРВЫМ, RED → GREEN; маркер не-integration).
- **integration:** `tests/integration/test_migrations.py` — `alembic upgrade head` на реальной тест-БД → `pg_extension` содержит `vector` (AC3), таблицы созданы (AC2). `tests/integration/test_repositories.py` — round-trip вектора 384 (AC4), каскадное удаление юзера (AC5), user-scoping выборок (AC6), tz-aware round-trip (AC7). Маркер `integration`, требует поднятого `postgres`.
- **runtime/behavioral (G2):** `make dev-infra-up` (postgres + `pg_vector_provisioner` ставит расширение) затем `make migrate` (`migration_runner` применяет миграцию) на живой БД → `make sh` + `SELECT 1 FROM pg_extension WHERE extname='vector'` и `\dt` показывает все семь таблиц; вручную проверить round-trip вставку/чтение вектора и каскадное удаление по `user_id`.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "310b28d5cae15e0249090e8902f57b0add443f66"
branch: "gsd/phase-002-data-model"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — PASS, 0 blocking)
- [x] 5.5 security (N/A — no auth/secrets/user-input; only static DDL raw SQL; SQL-injection check passed in review)
- [x] 6 ship (PR #2, squash-merged to main)
- [x] 7 learnings (auto)
debug_runs: []   # no debug cycles — verify + review passed first time

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по эталону task-001, source of truth: overview §4/§5/§7, ADR-001 `source_kind`, ADR-002 multi-tenancy/каскад; размерность вектора 384 для MiniLM, sync SQLAlchemy+psycopg для миграций/репозиториев)

### Step 3 — do (TDD) · loop-20260608-192301
- **RED→GREEN:** `tests/unit/test_models.py` написан первым → `ModuleNotFoundError: trendpulse.storage` (RED), после реализации 9/9 GREEN. `make ci-fast` зелёный: ruff/format ✓ · ruff ✓ · mypy strict (25 файлов) ✓ · pytest 10 passed / 6 deselected.
- **Создано:** `trendpulse.storage` — `Base(DeclarativeBase)` + `EMBEDDING_DIM=384`, 7 моделей (User/Channel/Watchlist/Post/Cluster/Score/Alert, typed `Mapped`, `DateTime(timezone=True)` + `datetime.now(UTC)`, user-owned FK `ondelete=CASCADE`, `Channel` глобальная без user_id, unique `(source_kind, handle)` через `SourceKind(StrEnum)`, индексы по user_id); `database.py` (sync engine/SessionLocal/get_session); user-scoped репозитории (`user_id` обязателен — `base.py`/`user_scoped.py`/`watchlist_repo`/`cluster_repo`/`alert_repo`) + глобальный `channel_repo.get_or_create`; `redis_client.py`. Baseline-миграция в **существующем** `migrations/versions/0001_baseline.py` (defensive `CREATE EXTENSION IF NOT EXISTS vector` первой операцией, 7 таблиц, `Vector(384)`); `migrations/env.py` → `target_metadata = Base.metadata`.
- **Решения:** pgvector без py.typed → mypy override `ignore_missing_imports` на уровне конфигурации (НЕ inline `# type: ignore`, CONVENTIONS). Абстрактный `UserOwnedBase`-mixin для типобезопасных user-scoped репозиториев (PEP 695 generics, без `Any`). `alerts.delivered_at` nullable (ещё не доставлен) + `timezone=True`. Новых зависимостей нет; `config.py` не тронут (`database_url`/`redis_url` уже были).

### Step 4 — verify (G2, реальная behavioral) · PASS
- **Integration-suite (6/6) против реальной pgvector-БД** (эфемерный `pgvector/pgvector:pg16` на host-порту, изолированно от стека): `test_migrations` (alembic upgrade head → vector ext **AC3**, 7 таблиц **AC2**, revision 0001), round-trip вектора 384 **AC4**, каскад тенанта (channels остаются) **AC5**, user-scoping **AC6**, tz-aware UTC **AC7**, channel get_or_create dedup.
- **Продакшн-путь** на изолированном compose-стеке: `make build` → `make dev-infra-up` → `pg_vector_provisioner` exit 0, `migration_runner` exit 0; `docker exec psql`: `pg_extension`=vector, таблицы {users,channels,watchlists,posts,clusters,scores,alerts}+alembic_version, `alembic_version`=0001, `clusters.embedding`=`vector(384)`. **AC8** — `make ci-fast` зелёный. Стек свёрнут `make down`.

### Step 5 — review (adversarial, opus) · PASS (0 blocking)
Вердикт clean. Multi-tenancy подтверждена: `UserScopedRepository` не имеет нефильтрованных list/get/delete; глобальный `Repository` base используется ТОЛЬКО `ChannelRepository`; все 5 user-owned таблиц — FK `ondelete=CASCADE` (модели+миграция); `channels` глобальная. `EMBEDDING_DIM=384` единый источник; нет f-string SQL (только статичный DDL); mypy-override scoped на `pgvector.*`; tz-aware UTC везде. Только LOW/INFO (downstream-footguns, не блокеры):
- LOW: `EMBEDDING_DIM` продублирован литералом в миграции — стандартная Alembic-практика (миграции самодостаточны), ок; для task-007 — следить за drift.
- LOW: generic `Repository` базу теоретически можно связать с tenant-моделью (сегодня безопасно — так делает только глобальный channel_repo).
- INFO: хелпер `utcnow()` (имя похоже на запрещённый `datetime.utcnow`, но функция tz-aware и hook его не банит); тесты репозиториев строят схему через `create_all`, не миграцией (риск model↔migration drift → опц. parity-check позже); `watchlists.threshold` default 0.0 + метрики постов default 0 → валидация на границе в task-004/коллектор в task-005.

### Step 5.5 — security · N/A
Нет auth/секретов/пользовательского ввода; единственный raw SQL — статичный DDL (`CREATE EXTENSION IF NOT EXISTS vector`, DROP в тестах) без интерполяции. SQL-injection проверка проведена в review (clean). Секретов нет → ротировать нечего.

### Step 6 — ship · PR #2 (squash-merged)
### Step 7 — learnings · см. docs/learnings.md (TASK-002 блок).
