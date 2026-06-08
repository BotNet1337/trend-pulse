# TrendPulse — Conventions

The authoritative coding conventions for `apps/trendPulse`. `trendpulse-review` and
`trendpulse-locate` read this file; the `trendpulse-forbidden-patterns` hook flags the
high-signal violations below on every edit.

## Repo layout (3 apps in `apps/trendPulse`)

- `backend/` — Python app (FastAPI + Celery). Package `trendpulse` lives in `backend/src/trendpulse/` (src-layout); submodules `api/`, `collector/`, `pipeline/`, `storage/`, `alerts/`, plus `config.py`, `celery_app.py`, `scheduler.py`.
- `landing/` — marketing landing (React + Vite).
- `frontend/` — dashboard SPA (Vite + React).
- `development/` — central `Makefile` + `docker-compose.yml` orchestrating all apps.
- `docs/` — this vault. `_bmad/`, `.claude/` — tooling.

The conventions below apply to **`backend/`** unless noted. Frontend/landing conventions are added in their epics.

## Stack (backend)

- **API:** FastAPI (Pydantic models at the boundary)
- **Async / queues:** Celery + Redis (Beat scheduler; per-user queues `batch:user_{id}`)
- **Parsing:** Telethon (MTProto) via a pool of technical accounts — **never** a user `session_string`
- **ML/NLP:** sentence-transformers (embeddings), MinHash (dedup), imagehash (photo hash)
- **DB:** PostgreSQL + pgvector — **ORM = SQLAlchemy 2.0**, миграции **Alembic** (через `migration_runner` provisioner)
- **Auth:** `fastapi-users` (+ httpx-oauth Google) — не катаем свой (ADR-003)
- **Billing:** крипто через NOWPayments за абстракцией `PaymentGateway` (ADR-004) — **никакого Stripe**
- **Delivery:** Telegram Bot API + webhook

## Hard rules (`## Forbidden Patterns`)

- **Full type hints.** No bare `Any` (`: Any` / `-> Any`), no `# type: ignore`. `mypy` must pass.
- **Explicit error handling.** Raise/handle domain errors at boundaries; never a bare `except:` or `except …: pass` that swallows.
- **No magic literals** for TTL / URL / timeout / thresholds — put them in pydantic-settings/env or a named constant. Time in **seconds** as named constants.
- **Cross-module via service interfaces.** Modules (`api/`, `collector/`, `pipeline/`, `storage/`, `alerts/`) talk through their public service functions — don't reach into another module's internals.
- **Celery task args are JSON-serializable** — pass ids, not ORM objects. Respect `max_instances=1` / per-user isolation.
- **Pure/immutable pipeline steps** (`dedup` → `normalize` → `embed` → `cluster`): return new data, don't mutate inputs.
- **Pydantic validates at the API boundary** — never trust external/user/Telegram data unvalidated.
- **SQL via SQLAlchemy bind params** — never f-string SQL. Match pgvector embedding dimension to the column.
- **Compliance:** read only public channels; do not persist raw post content beyond the 48h retention window; secrets via env/secret-manager only.

## Environment management

- **`make` (root `apps/trendPulse/Makefile`) is the single entry point.** Use short targets: `make up`, `make dev-up`, `make dev-infra-up`, `make down`, `make build`, `make logs`, `make migrate`, `make ansible-unpack`, `make ci` — **not** raw `docker compose` or bare `uv`/`pytest`/`ruff`/`mypy` (those are wrapped inside targets). See [ADR-005](./architecture/adr-005-infra-provisioning-and-secrets.md).
- **Networks/isolation:** only nginx is public (edge); api in `internal`; postgres/redis each on their own net, no published ports. See [network-design.md](./architecture/network-design.md).
- **Provisioning:** `pg_vector_provisioner` + `migration_runner` (one-shot, own compose files) run before app starts; per-service compose files under `development/compose/`; reverse-proxy config (`nginx.conf`, tls) lives under `development/provisioning/nginx/`.
- **Version pinning:** all dep/image versions live in `development/version.env` (committed, e.g. `PG_VERSION`, `REDIS_VERSION`, `NGINX_VERSION`, `PYTHON_VERSION`, `UV_VERSION`). No `latest`/floating tags — compose interpolates `${...}` from it so builds are identical everywhere.
- **Env split:** `development/env/deploy.env` (non-secret defaults, committable) + `sensitive.env` (secrets, gitignored). **Ansible is the single source of truth** for both — `make ansible-unpack` materializes them before run.
- Same app image for `api`/`worker`/`beat`; differ only by command.

## Git

- Branches `gsd/phase-{N}-{slug}`; never commit to `main`/`master`.
- Conventional Commits: `feat|fix|refactor|docs|test|chore|perf|ci: …`.
- Code + docs ship in the **same** PR (single repo).
