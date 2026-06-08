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
