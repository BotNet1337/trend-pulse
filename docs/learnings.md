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
