# TrendPulse — Learnings Ledger

Append-only. Stage 7 of `trendpulse-executor` writes one dated block per run.
`trendpulse-distill-learnings` periodically promotes durable lessons into agent memory
and marks promoted blocks with `<!-- promoted: <names> (YYYY-MM-DD) -->`.

Block format:

```
## YYYY-MM-DD — TASK-NNN <title>
- **Lesson:** … **Why:** … **How to apply:** …
- **Decision:** … **Rationale:** …
- **Gotcha:** …
```

---

<!-- learnings start below -->

## 2026-06-08 — TASK-001 Dev + infra environment
- **Lesson:** В Docker `COPY --from=<image:${TAG}>` НЕ поддерживает интерполяцию переменных. **Why:** buildkit резолвит `--from` до раскрытия ARG в строке образа → ошибка «variable expansion is not supported for --from». **How to apply:** выноси версионируемый внешний образ в отдельный stage (`FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv`) и `COPY --from=uv …`. ARG до первого FROM = глобальный scope.
- **Lesson:** `uv sync --frozen` ставит и `default-groups` → dev-инструменты протекают в runtime-образ. **Why:** `[tool.uv] default-groups=["dev"]` удобен для локального CI, но образ один на api/worker/beat/migration_runner и уходит в prod. **How to apply:** в Dockerfile всегда `uv sync --frozen --no-dev`; dev-тулинг — только на хосте через `make ci`/`uv run`. Проверка: `docker run --rm <img> python -c "import pytest"` → ModuleNotFoundError.
- **Lesson:** Не клади пароль БД ни в код, ни в committed `deploy.env` (даже dev-дефолт задаёт паттерн). **Why:** CONVENTIONS — секреты только в `sensitive.env`/vault. **How to apply:** `Settings` собирает `database_url` из `POSTGRES_*` частей; пароль приходит из `sensitive.env`; `all.yml`/`deploy.env` держат только host/port/db/user.
- **Lesson:** `depends_on` без `condition: service_healthy` = гонка холодного старта (nginx → 502, celery → crash-loop до restart). **Why:** дефолт `service_started` ждёт только запуск процесса, не готовность. **How to apply:** дай api `healthcheck` (stdlib `urllib` на `/health`, без лишних пакетов), nginx → `depends_on api: service_healthy`; redis(healthy) в depends_on api/worker/beat.
- **Decision:** `ansible-unpack` на task-001 — dependency-free stub-рендерер `key: value` YAML → env (deploy.env из `all.yml`, sensitive.env из `vault.yml`, chmod 600). **Rationale:** локальный dev без `ansible` binary; реальный `ansible-vault` + secret-scan — **task-012**.
- **Gotcha (важно для task-002):** worker/beat сидят только на `postgres_net`/`redis_net` (`internal: true`) → **нет egress в интернет**. Telethon (MTProto) и pull моделей sentence-transformers в коллекторе сломаются. **How to apply:** в task-002+ дать worker egress-способную сеть (отдельная не-internal `egress`) ИЛИ кэшировать модель на build-time. Не наследовать молча.
- **Gotcha:** host-порт 443 часто занят другим локальным проектом (OrbStack/другой nginx). nginx.conf слушает только 80 локально (443 ssl — prod, под серты). **How to apply:** публикуй только `${HTTP_PORT:-80}:80`; 443 включай на prod вместе с TLS-блоком и сертами (ops/).
- **Gotcha (git hygiene):** `git rm --cached <dir>` оставляет файлы на диске, НО последующий `git checkout` на коммит/ветку, где dir был ещё tracked-then-removed, **удалит файлы с диска**. Так чуть не потеряли `.claude/` (хуки+скиллы) после merge finalize-PR. **How to apply:** untrack + gitignore в один заход и не переключайся на старые ревизии, ожидая файлы на диске; при потере — `git checkout <bootstrap-sha> -- <dir>` + `git restore --staged <dir>` (вернуть на диск, оставить untracked). Теперь `.claude`/`_bmad` untracked везде → переключения веток безопасны.

## 2026-06-08 — TASK-002 Data model (SQLAlchemy 2.0 · pgvector · multi-tenancy)
- **Lesson:** integration-тесты к БД нельзя гнать с хоста против compose-postgres (нет host-порта — изоляция из task-001). **Why:** network-design публикует только nginx. **How to apply:** для реального прогона integration-suite поднимай эфемерный `pgvector/pgvector:pg16` с проброшенным host-портом и `POSTGRES_HOST/PORT` env-override; продакшн-путь миграции проверяй отдельно через `migration_runner` + `docker exec psql` на изолированном стеке. (Оба пути прогнаны в G2.)
- **Decision:** baseline-миграция переиспользует СУЩЕСТВУЮЩИЙ `backend/migrations/` (task-001), не создаёт параллельный `alembic/`. `alembic.ini script_location=migrations`. **Rationale:** один alembic-скаффолд; план task-002 ошибочно говорил `alembic/` — диск важнее плана.
- **Decision:** pgvector без py.typed → mypy `ignore_missing_imports` через `[[tool.mypy.overrides]]` scoped на `pgvector.*` (НЕ inline `# type: ignore`). **Rationale:** CONVENTIONS запрещает inline-ignore; config-override локализован.
- **Gotcha:** размерность вектора (`EMBEDDING_DIM=384`) дублируется литералом в миграции (Alembic-миграции самодостаточны, не импортируют живой app-код) — ок, но **task-007 (pipeline) обязан матчить 384**, иначе Postgres отвергнет вставку. **How to apply:** при смене размерности — новая миграция + проверка `clusters.embedding` dim == EMBEDDING_DIM.
- **Gotcha:** репо-тесты строят схему через `Base.metadata.create_all`, а не миграцией → model↔migration drift не ловится round-trip-тестами (только `test_migrations` проверяет наличие таблиц). **How to apply:** при росте схемы добавить parity-check (autogenerate diff == empty).

## 2026-06-08 — TASK-003 Auth (fastapi-users + Google OAuth, JWT + cookie)
- **Lesson (КРИТИЧНО для локали):** `Secure` cookie НЕ отправляется браузером/curl по http. Локально стек http-only (:80) → и auth-cookie (`CookieTransport.cookie_secure`), и OAuth CSRF-cookie (`get_oauth_router(csrf_token_cookie_secure=...)`) должны быть `False` локально, иначе login/OAuth молча ломаются (401 / OAUTH_INVALID_STATE). **How to apply:** настройка `auth_cookie_secure` (код-дефолт True для prod, env `AUTH_COOKIE_SECURE=false` локально). Prod (task-012 `group_vars/prod.yml`) обязан выставить true.
- **Lesson:** fastapi-users 15 кладёт CSRF-токен в OAuth `state` (double-submit: state-JWT + cookie сверяются на callback). Ручной state → `OAUTH_INVALID_STATE`. **How to apply:** в тестах прогоняй реальный `/auth/google/authorize` чтобы получить валидный state + CSRF-cookie (мокая только `GoogleOAuth2.get_access_token`/`get_id_email`).
- **Lesson:** `oauth_accounts.expires_at` — INTEGER (int4, max 2147483647); мок unix-ts должен влезать (используй ~2000000000, не 9999999999).
- **Decision:** сохранили **int user id** (не UUID fastapi-users по умолчанию) — `FastAPIUsers[User,int]` + `IntegerIDMixin`, чтобы не ломать FK из task-002. Один `User` (расширили существующий `SQLAlchemyBaseUserTable[int]`), не второй. Миграция аддитивная (0002, down_revision 0001).
- **Decision (user-directive):** плоская раскладка `backend/src/` без уровня пакета `trendpulse/` — импорты top-level (`from config import`, `from storage...`, `from api...`). hatchling `[tool.hatch.build.targets.wheel] sources=["src"] only-include=["src"]`; mypy `mypy_path="src"` + `explicit_package_bases=true`; compose-команды `uvicorn api.main:app` / `celery -A celery_app`; alembic.ini `prepend_sys_path=src`. **Why:** запрошено пользователем; переопределяет CONVENTIONS §Repo layout (src-layout с пакетом). **How to apply:** новые backend-модули кладём прямо в `backend/src/<module>`, без `trendpulse.`-префикса.
- **Gotcha (prod-hardening долг → task-012):** (1) `auth_cookie_secure=true` на prod; (2) валидатор min-length ≥32 на `jwt_secret`/`oauth_state_secret` (дев-плейсхолдеры слабые, InsecureKeyLengthWarning); (3) шифрование Google токенов в `oauth_accounts` at rest; (4) `associate_by_email=True` полагается на Google-verified email (для строгости gate на is_verified). Защищённый контракт = `Depends(current_user)` (active, НЕ verified) — downstream-роуты выбирают gating осознанно.

## 2026-06-08 — TASK-004 Watchlist CRUD API
- **Decision (user-directive):** «одна junction-строка = один watchlist» — single channel на watchlist, адрес по числовому `id`; несколько каналов = несколько watchlists. Переопределяет multi-channel `channels: list` из task-doc. Лимит плана = макс. число watchlists на юзера (Free=5); `min_channels` = scoring-параметр, не счётчик каналов. **How to apply:** downstream (task-005 читает каналы watchlist'ов, task-006/008 берут topic+threshold) ожидают per-row watchlist с одним каналом.
- **Lesson:** sync-репозитории task-002 в async FastAPI-приложении — делай **sync `def` route-handlers** (FastAPI гонит их в threadpool; async-зависимость `current_user` всё равно резолвится) + sync session-dependency над `get_session`. Не тащить async-репозитории. (Auth остаётся на async-движке fastapi-users — два движка на одном psycopg-DSN, см. [[trendpulse-build-and-infra-gotchas]].)
- **Lesson (BOLA/IDOR):** tenant-изоляция держится на том, что `UserScopedRepository` НЕ наследует глобальный `get_by_id(by id)` — все выборки требуют `user_id`. Чужой/несущ. id → 404 (не 403/200, без утечки существования); tenant из токена (`get_tenant_user_id(user)`), НЕ из тела/пути; Pydantic `extra="forbid"` (нет mass-assignment `id`/`user_id`).
- **Gotcha:** дубликат `(user_id, channel_id, topic)` (unique из task-002) лови как IntegrityError → rollback → доменная ошибка → **409**, не 500. Покрой тестом (review поймал отсутствие).
- **Gotcha (seam-долг):** лимит — read-then-write (TOCTOU, неатомарен) + `len(list())` для count → task-010 (атомарный счётчик/индекс, пагинация). `validate_ref` сейчас format-only; когда task-005 даст `collector.registry` — проверь его на SSRF/timeout (вызывается на attacker-controlled handle на границе).
