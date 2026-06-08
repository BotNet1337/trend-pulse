---
id: TASK-007
title: Batch pipeline — dedup→normalize→embed→cluster + batch_processor (per-user)
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: ""    # set by executor at ship time
branch: ""             # set by executor at ship time
tags: [backend, pipeline, ml, celery, dedup, embed, cluster, multi-tenancy]
---

# TASK-007 — Batch pipeline (dedup · normalize · embed · cluster · batch_processor)

> Реализовать батч-pipeline TrendPulse: чистые иммутабельные шаги `dedup → normalize → embed → cluster` над платформо-независимыми `RawPost`/`NormalizedPost` (ADR-001) и Celery-задачу `run_batch(user_id)`, которая drain'ит Redis-буфер юзера, прогоняет посты через шаги и сохраняет кластеры в Postgres с `user_id` (overview §4 «Pipeline»).

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md) §4, [`../architecture/high-level-architecture.md`](../architecture/high-level-architecture.md) §4 «Data flow» шаг 3). Окружение и скелет пакета `trendpulse` готовы (task-001). Это ядро обработки: между коллектором (task-005, пишет `RawPost` в Redis-буфер) и scorer'ом (task-008, читает кластеры). По roadmap критического пути `… → 005 → 006 → 007 → 008 → …` — без него нет кластеров, нечего скорить.

Pipeline по [ADR-001](../architecture/adr-001-source-abstraction.md) **платформо-независим**: шаги оперируют только `RawPost`/`NormalizedPost`, ничего не знают про Telegram/Telethon. Это позволит подключить Twitter/X (Фаза 2) без переписывания ядра. `batch_processor` использует репозитории/схему task-002 (`user_id`-scoped, фиксированная размерность эмбеддинга в pgvector-колонке) и инфраструктуру task-006 (Celery app, per-user очереди `batch:user_{id}`, `max_instances=1` / lock).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints (no `Any`, no `# type: ignore`), pure/immutable pipeline steps (возвращают новые данные, не мутируют вход), no magic literals (пороги/TTL/размерности — в pydantic-settings или именованных константах), cross-module через service-функции, Celery task args JSON-serializable (передаём `user_id`, не ORM-объекты), SQL через SQLAlchemy bind params, размерность эмбеддинга совпадает с pgvector-колонкой.

## Goal

Есть рабочая, протестированная цепочка `dedup → normalize → embed → cluster` (каждый шаг чист и иммутабелен) и Celery-задача `run_batch(user_id)`, которая: drain'ит Redis-буфер юзера → дедуплицирует near-duplicate тексты (MinHash) → нормализует (перевод/чистка) → эмбеддит (sentence-transformers, lazy-load модели) → кластеризует по cosine similarity → персистит кластеры в Postgres scoped по `user_id`. Пустой буфер → no-op. Все проверки — unit-тесты на `RawPost`-фикстурах (без Telegram) плюс behavioral-прогон `run_batch` через worker (G2). DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения приняты по дефолтам overview/ADR-001; все обратимы. -->
- Q: На каких данных работают шаги? → A: **только `RawPost`/`NormalizedPost`** из ADR-001 → Decision: ни один шаг не импортирует ничего из `collector/telegram/`; вход/выход — платформо-независимые модели (rationale: ADR-001 «pipeline работает только с RawPost/NormalizedPost и ничего не знает о платформе»; готовность к Twitter/X без переписывания).
- Q: Иммутабельность шагов? → A: **pure-функции** → Decision: каждый шаг — `run(items: list[...]) -> list[...]`, возвращает НОВЫЙ список новых объектов, вход не мутируется; модели — `@dataclass(frozen=True)` / pydantic immutable (rationale: CONVENTIONS «Pure/immutable pipeline steps»; глобальное правило immutability).
- Q: Алгоритм дедупа? → A: **MinHash** через `datasketch` → Decision: shingling текста → `MinHash` → near-dup при Jaccard-оценке ≥ порога (`dedup_similarity_threshold` в settings); near-дубликаты коллапсятся в один пост (rationale: overview §4 «Дедупликация: MinHash (datasketch)»; `datasketch` уже в core-deps task-001).
- Q: Модель эмбеддингов и её вес? → A: **sentence-transformers / sentence-BERT**, тяжёлая (torch) → Decision: зависимость в dependency-group **`ml`** (task-001); модель грузится **лениво** (lazy singleton при первом `embed.run`, не на импорте) — чтобы `api`-процесс и импорт пакета оставались лёгкими (rationale: arch §7 «ML-стек тяжёлый → группа ml только в worker»; имя модели — в settings, не magic literal).
- Q: Размерность вектора? → A: фиксированная, **из схемы task-002** → Decision: pgvector-колонка имеет фиксированный dim; `embed` выдаёт векторы ровно этой размерности; константа размерности — единый источник (settings/схема), проверяется (rationale: arch §7 «pgvector dimension drift → фиксированная размерность + проверка»; CONVENTIONS «Match pgvector embedding dimension to the column»).
- Q: Алгоритм кластеризации? → A: **cosine similarity threshold** → Decision: greedy/agglomerative группировка по косинусной близости векторов ≥ `cluster_cosine_threshold` (settings); кластер агрегирует посты + участвовавшие каналы (rationale: overview §4 «cluster: cosine similarity»; cross-source кластеризация уже работает, т.к. оперируем векторами `NormalizedPost` — ADR-001).
- Q: Откуда берутся посты и куда пишутся кластеры? → A: вход — Redis-буфер (task-005/006), выход — Postgres → Decision: `run_batch` использует Redis-клиент/буфер из storage (task-006 drain) и репозитории кластеров из storage (task-002), всё scoped по `user_id`; задача принимает только `user_id` (JSON-serializable) (rationale: CONVENTIONS «pass ids, not ORM objects»; §5 multi-tenancy).
- Q: Параллельность батчей одного юзера? → A: **нет** → Decision: `run_batch` уважает `max_instances=1` / per-user lock из task-006 (rationale: overview §5; arch §4 шаг 2).
- Q: Граница перевода в `normalize`? → A: перевод/чистка текста как в overview §4 → Decision: `normalize` приводит текст к единому виду (чистка разметки/эмодзи/URL, опциональный перевод к целевому языку); деталь реализации перевода вынесена за интерфейс шага, по умолчанию — no-op-passthrough если перевод не сконфигурирован (rationale: держим шаг чистым и тестируемым; не блокируем pipeline внешним переводчиком на этой задаче).

## Scope
> **Раскладка:** задача трогает **только `backend/`**, модуль `pipeline/`. Источник данных (`collector/`, task-005) и Celery-инфра (`celery_app`/scheduler/locks, task-006) и схема/репозитории (`storage/`, task-002) — уже существуют; здесь они только **используются** через их публичные service-функции, не модифицируются.

- **Touch ONLY (создать):**
  - `apps/trendPulse/backend/src/trendpulse/pipeline/__init__.py` — публичный API модуля (re-export `run_batch`, шаги).
  - `apps/trendPulse/backend/src/trendpulse/pipeline/steps/__init__.py`.
  - `apps/trendPulse/backend/src/trendpulse/pipeline/steps/dedup.py` — MinHash (datasketch): `run(posts: list[RawPost]) -> list[RawPost]`, коллапс near-duplicate текстов; порог из settings.
  - `apps/trendPulse/backend/src/trendpulse/pipeline/steps/normalize.py` — `run(posts: list[RawPost]) -> list[NormalizedPost]`: чистка текста (+ опц. перевод), pure/immutable.
  - `apps/trendPulse/backend/src/trendpulse/pipeline/steps/embed.py` — sentence-transformers (`ml` group), **lazy** загрузка модели; `run(posts: list[NormalizedPost]) -> list[numpy-вектор фиксированного dim]` (или `list[NormalizedPost]` с проставленным вектором).
  - `apps/trendPulse/backend/src/trendpulse/pipeline/steps/cluster.py` — cosine-similarity группировка: `run(posts, vectors) -> list[Cluster]`; порог из settings.
  - `apps/trendPulse/backend/src/trendpulse/pipeline/batch_processor.py` — Celery-задача `run_batch(user_id)`: drain буфера → dedup → normalize → embed → cluster → persist кластеров с `user_id`.
  - `apps/trendPulse/backend/tests/unit/test_dedup.py` (AC1 — RED-якорь), `tests/unit/test_normalize.py`, `tests/unit/test_embed.py`, `tests/unit/test_cluster.py`, `tests/unit/test_batch_processor.py`.
  - `apps/trendPulse/backend/tests/integration/test_run_batch.py` (маркер `integration`, behavioral G2).
  - Возможны фикстуры в `apps/trendPulse/backend/tests/conftest.py` (RawPost-фабрики) — добавление, не переписывание чужого.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`; `collector/**` (task-005), `storage/**` модели/миграции (task-002), `celery_app.py`/`scheduler.py`/locks (task-006) — только потребляем их публичный API, не редактируем. Никакого scorer'а (task-008) и alerts (task-009). Размерность pgvector-колонки и схему кластеров не менять.
- **Blast radius:** потребитель кластеров — scorer (task-008): задаёт контракт сохранённого кластера (`user_id`, агрегированные каналы, вектор/метрики). Контракт `RawPost`/`NormalizedPost` приходит из ADR-001/task-005; pipeline не должен его расширять платформо-специфично. Размерность эмбеддинга — общий инвариант со схемой task-002.

## Acceptance Criteria
- [ ] **AC1 — dedup коллапсит near-duplicates.** Given два `RawPost` с почти одинаковым текстом (near-duplicate) и один отличный, When `dedup.run([p1, p1_near, p2])`, Then на выходе 2 поста (near-пара схлопнута в один), а `p2` сохранён; вход не мутирован. _(failing unit test — RED-якорь.)_
- [ ] **AC2 — normalize чист и иммутабелен.** Given `RawPost` с «грязным» текстом (URL/эмодзи/разметка), When `normalize.run([...])`, Then возвращён НОВЫЙ список `NormalizedPost` с очищенным текстом; исходные `RawPost` не изменены.
- [ ] **AC3 — embed выдаёт векторы фиксированной размерности.** Given список `NormalizedPost`, When `embed.run([...])`, Then для каждого поста получен вектор ровно размерности схемы (task-002); модель загружена лениво (не на импорте модуля).
- [ ] **AC4 — cluster группирует семантически близкие посты.** Given векторы, где две пары близки по cosine ≥ порога, а один пост далёк, When `cluster.run(posts, vectors)`, Then близкие попадают в общие кластеры, далёкий — в отдельный; число/состав кластеров соответствует порогу `cluster_cosine_threshold`.
- [ ] **AC5 — пустой буфер → no-op.** Given пустой Redis-буфер юзера, When `run_batch(user_id)`, Then задача завершается без записи в Postgres и без ошибок (ничего не персистится).
- [ ] **AC6 — run_batch пишет кластеры scoped по user_id.** Given буфер юзера с постами, When `run_batch(user_id)`, Then в Postgres появляются кластеры с этим `user_id`; задача принимает только `user_id` (JSON-serializable), не ORM-объекты; уважается `max_instances=1`.
- [ ] **AC7 — pipeline платформо-независим.** Given любой `RawPost` (произвольный `source.kind`), When прогон шагов, Then ни один шаг не импортирует `collector/telegram/*` и не обращается к Telegram-специфике (проверяется тестом на фикстурах без Telegram + статически).

## Plan
1. **RED:** `tests/unit/test_dedup.py` — две near-dup `RawPost` + одна отличная → `dedup.run(...)` даёт 2 поста, вход не мутирован (AC1). Запустить `make ci-fast` → FAIL.
2. `pipeline/steps/dedup.py` — MinHash (datasketch): shingling текста → `MinHash` → оценка Jaccard; коллапс при ≥ `dedup_similarity_threshold` (settings). Pure: новый список. GREEN для AC1.
3. `pipeline/steps/normalize.py` — `RawPost -> NormalizedPost`: чистка (URL/эмодзи/разметка) + опц. перевод (за интерфейсом, default passthrough). Тест `test_normalize.py` на иммутабельность + очистку (AC2).
4. `pipeline/steps/embed.py` — sentence-transformers (`ml` group); lazy singleton модели (имя модели из settings); `run` → векторы фиксированного dim (константа из settings/схемы task-002). Тест `test_embed.py`: размерность + lazy-load (AC3). _(в unit можно мокать модель, чтобы не тянуть torch; реальная модель — в integration.)_
5. `pipeline/steps/cluster.py` — cosine-similarity группировка (numpy), порог `cluster_cosine_threshold` (settings); кластер агрегирует посты + каналы. Тест `test_cluster.py` (AC4).
6. `pipeline/batch_processor.py` — `@celery.task run_batch(user_id)`: drain Redis-буфера (storage, task-006) → `dedup` → `normalize` → `embed` → `cluster` → persist через cluster-репозиторий (storage, task-002) с `user_id`; пустой буфер → ранний return (AC5). Уважать lock/`max_instances=1` (task-006). Тест `test_batch_processor.py` с мок-репо/буфером (AC5, AC6).
7. `pipeline/__init__.py`, `pipeline/steps/__init__.py` — публичный API (re-export). Статическая проверка AC7 (нет импортов из `collector/telegram`).
8. `tests/integration/test_run_batch.py` (маркер `integration`) — реальный прогон `run_batch` на засеянном буфере через поднятый стек: кластеры появляются в Postgres scoped по `user_id` (behavioral G2).
9. Прогнать `make ci-fast` (unit зелёные) и `make test-integration` / `make up-d` + worker для G2.

## Invariants
- **Каждый шаг чист и иммутабелен:** `run` принимает список, возвращает НОВЫЙ список новых объектов; вход никогда не мутируется (CONVENTIONS, глобальное immutability).
- **Платформо-независимость:** шаги оперируют только `RawPost`/`NormalizedPost`; нет импортов/знаний о Telegram/Telethon (ADR-001).
- **Размерность эмбеддинга = размерности pgvector-колонки** (task-002) — единый источник-константа, проверяется; никакого dimension drift (arch §7).
- **Модель эмбеддингов грузится лениво** (не на импорте) и не на критическом пути старта `api`; torch — только в `ml`-группе/worker (arch §7).
- **`run_batch` принимает только `user_id`** (JSON-serializable), всё чтение/запись scoped по `user_id`; `max_instances=1` / per-user lock уважается (CONVENTIONS, §5).
- **Никаких magic literals:** пороги дедупа/кластера, имя модели, размерность — в pydantic-settings/именованных константах; время в секундах как именованные константы.
- **Кросс-модульно — только через публичные service-функции** storage/celery (task-002/006); не лезть во внутренности чужих модулей.
- **Cross-module via interfaces:** persist кластеров — через репозиторий storage, не raw SQL; SQL — bind params (CONVENTIONS).

## Edge cases
- Пустой буфер → `run_batch` no-op (ранний return, без записи в БД) — AC5.
- Один пост в буфере → проходит шаги; кластер из одного поста — валидный результат (не падать).
- Все посты near-duplicate → dedup схлопывает почти всё в один; pipeline не падает на маленьком наборе.
- `sentence-transformers` тянет torch (~2GB) → lazy-load + `ml`-группа; в unit-тестах модель мокается, реальная — только в integration (иначе CI медленный/жирный).
- Размерность вектора модели ≠ размерности pgvector-колонки → fail-fast с понятной ошибкой (проверка), не молчаливая порча данных (arch §7 dimension drift).
- Текст пустой/только эмодзи/только URL после `normalize` → не падать; пустой текст не должен ломать MinHash/эмбеддинг (обработать как граничный, например пропустить или дать нулевой shingle-набор детерминированно).
- Параллельный enqueue батча того же юзера → lock/`max_instances=1` не даёт двойного прогона (task-006); кластеры не дублируются.
- Cosine на нулевом/вырожденном векторе → защита от деления на ноль при нормализации.
- Не tz-aware `posted_at` в `RawPost` — приходит уже нормализованным (UTC) из коллектора (ADR-001); pipeline не чинит время, но и не предполагает naive.

## Test plan
- **unit (RED-first):**
  - `test_dedup.py` — near-dup пара → один пост, отличный сохранён, вход не мутирован (AC1, пишется ПЕРВЫМ, RED).
  - `test_normalize.py` — очистка текста + иммутабельность входа (AC2).
  - `test_embed.py` — размерность вектора == схема; lazy-load модели (модель мокается) (AC3).
  - `test_cluster.py` — близкие по cosine → общий кластер, далёкий — отдельный (AC4).
  - `test_batch_processor.py` — пустой буфер → no-op (AC5); непустой → persist с `user_id`, args = `user_id` (AC6); проверка отсутствия Telegram-импортов (AC7).
- **integration (по требованию, маркер `integration`):** `test_run_batch.py` — реальный Redis-буфер + Postgres через поднятый compose; реальная sentence-transformers модель; кластеры появляются scoped по `user_id`.
- **runtime/behavioral (G2):** `make up-d` + worker → засеять буфер юзера → вызвать `run_batch(user_id)` (`.delay()`/прямой вызов задачи) → наблюдать кластеры в Postgres с `user_id`; пустой буфер → no-op в логах.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security — N/A (pure compute; no auth/secret/input boundary)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по overview §4 «Pipeline», ADR-001 (source abstraction, RawPost/NormalizedPost), high-level-architecture §4 шаг 3; зависит от task-005 (collector/RawPost + Redis-буфер) и task-006 (Celery app, per-user очереди, lock/max_instances=1); потребитель кластеров — task-008 scorer)
