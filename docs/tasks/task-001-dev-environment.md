---
id: TASK-001
title: Dev + infra environment — 3-app layout, uv backend, per-service compose, nginx, provisioning, env split
status: done           # planned → in-progress → review → done
owner: infra
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "c1790601c34b802534b8d8ee6ab0b6ef3724d7fd"
branch: ""             # set by executor at ship time
tags: [infra, tooling, docker, compose, nginx, uv, alembic, ansible, ci]
---

# TASK-001 — Dev + infra environment (3-app layout · uv backend · per-service compose · nginx · provisioning · env split)

> Подготовить `apps/trendPulse` к разработке: трёхприложенческая раскладка (`backend/`, `landing/`, `frontend/`), воспроизводимое окружение `backend/` на uv + Python 3.12, per-service `docker compose` под `development/compose/`, сегментированные сети (только nginx наружу), one-shot provisioning (pgvector + alembic-миграции) перед стартом app, env split `deploy.env`/`sensitive.env` из Ansible, скелет `ops/`, и единая точка входа — **root `apps/trendPulse/Makefile`** (`make up`, `make dev-infra-up`, …). Всё — строго по [ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md) и [network-design.md](../architecture/network-design.md).

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md), [`../architecture/high-level-architecture.md`](../architecture/high-level-architecture.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon · sentence-transformers. Кода ещё нет — это нулевая, инфраструктурная задача: создать скелет приложений и полный dev+infra-контур, чтобы все последующие фичи (коллектор, pipeline, scorer, billing) разрабатывались в одном воспроизводимом и безопасно сегментированном окружении.

Эта ревизия задачи приводит контур в соответствие с двумя принятыми артефактами:
- **[ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md)** — root `Makefile` как единая точка входа, per-service compose + `include:`, provisioning (pgvector + migration_runner), env split `deploy.env`/`sensitive.env` с источником истины в Ansible, скелет `ops/` (terraform/ansible).
- **[network-design.md](../architecture/network-design.md)** — сегментация сетей `edge`/`internal`/`postgres_net`/`redis_net`; наружу торчит только nginx; api/postgres/redis не публикуют порты; старт-ордер `postgres(healthy) → pg_vector_provisioner → migration_runner → app → nginx`.

Эталон конфигурации backend — `/Users/macbookpro16/work/ma/prediction` (uv + pinned Python, multi-stage Dockerfile с `uv sync --frozen`, `uv run`-CI, ruff/mypy/pytest в `pyproject.toml`). Адаптируем под мульти-сервисный SaaS с reverse-proxy и provisioning.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md).

## Goal

Один разработчик с нуля делает `git clone` → `make ansible-unpack` (материализует env из Ansible) → `make dev-infra-up` (postgres+redis healthy, оба провижинера отработали) → `make up` (полный стек включая nginx) и получает: FastAPI с `/health`, доступный **только через nginx** (`curl http://localhost/health` → `200 {"status":"ok"}`), запущенные Celery worker и beat, БД с расширением `vector` и применёнными миграциями. api/postgres/redis **не публикуют** host-портов. `make ci-fast` (ruff + mypy + pytest) зелёный. Все действия — через root `make`.

## Discussion
<!-- durable record of clarifications. Решения приняты по ADR-005 + network-design; все обратимы. -->
- Q: Раскладка репо? → A: **3 приложения** под `apps/trendPulse/` → Decision: `backend/` (Python, src-layout `trendpulse` в `backend/src/trendpulse/`), `landing/` + `frontend/` (пустые скелеты с `.gitkeep`, наполнение в эпиках B/C), `development/` (оркестратор), `ops/` (IaC-скелет). Эта задача готовит **только `backend/` + development/ + ops/-скелет**.
- Q: Менеджер пакетов и версия Python? → A: **uv** + **Python 3.12** → Decision: `requires-python="==3.12.*"`, `backend/.python-version=3.12`, `backend/uv.lock` коммитим (rationale: эталон на 3.12; ML-стек стабилен на 3.12).
- Q: Раскладка пакета? → A: **src-layout** `backend/src/trendpulse/` → Decision: hatchling `packages=["src/trendpulse"]`; чище для uv/тестов, предотвращает импорт из CWD (CONVENTIONS §Repo layout).
- Q: Где единая точка входа — `development/Makefile` или root? → A: **root `apps/trendPulse/Makefile`** (ADR-005 §1) → Decision: так работает `make up`, а **не** `make -C development build`. Все таргеты живут в root-Makefile; он оборачивает `docker compose` с per-service файлами и `uv run` в `backend/`. CONVENTIONS закрепляет короткие таргеты.
- Q: Структура compose? → A: **per-service** (ADR-005 §2) → Decision: `development/compose/{nginx,api,worker,beat,postgres,redis}.yml`; top `development/docker-compose.yml` через `include:` собирает их и объявляет сети; build context `../backend`.
- Q: Сетевая топология? → A: network-design → Decision: `edge` (только nginx, publishes 80/443), `internal` (nginx+api), `postgres_net` (postgres + api/worker/beat/провижинеры), `redis_net` (redis + api/worker/beat). api НЕ в edge и НЕ публикует порты. nginx reverse-proxy → `proxy_pass http://api:8000` + security-заголовки.
- Q: Как готовить БД до старта app? → A: **provisioning one-shot** (ADR-005 §3) → Decision: `development/provisioning/pg_vector_provisioner/` (`CREATE EXTENSION IF NOT EXISTS vector;`) и `development/provisioning/migration_runner/` (`alembic upgrade head`), каждый со своим compose-файлом. Порядок: postgres(healthy) → pg_vector_provisioner → migration_runner → app, через `depends_on: condition: service_completed_successfully`. Миграции запускаются **только** провижинером, не инлайн в app.
- Q: ORM/миграции? → A: **SQLAlchemy 2.0 + Alembic** (CONVENTIONS) → Decision: alembic-скаффолд в `backend/` (`alembic.ini`, `migrations/`); фактический прогон — `migration_runner`. На этой задаче миграций по существу нет (только пустой `migrations/versions/`), но контур готов.
- Q: Секреты/env? → A: **env split + Ansible как источник истины** (ADR-005 §4) → Decision: `development/env/deploy.env` (несекретные дефолты, коммитим) + `development/env/sensitive.env` (секреты, gitignore). Оба материализуются `make ansible-unpack` из `ops/ansible` (group_vars → deploy.env, vault → sensitive.env). compose: `env_file: [../env/deploy.env, ../env/sensitive.env]`.
- Q: IaC? → A: **скелет сейчас, реализация в task-012** (ADR-005 §5) → Decision: `ops/terraform/` (.gitkeep + README) и `ops/ansible/` (group_vars defaults, vault placeholder, inventory). Реальный Terraform/Ansible — task-012; здесь только скелет + wiring `make ansible-unpack`.
- Q: ML-стек (sentence-transformers→torch ~2GB)? → A: отдельная dependency-group `ml` → Decision: `core` (api/worker boot) + `ml` (embeddings, только worker) + `dev` (tooling). Не блокирует первый `up`.
- Q: git? → A: репозиторий ещё не инициализирован → Decision: **step 0 = `git init`**; `baseline_commit` заполняет executor сразу после init.

## Scope
> **Раскладка (3 приложения внутри `apps/trendPulse`):** `backend/` — Python (FastAPI/Celery), `landing/` — React+Vite, `frontend/` — Vite+React SPA. Эта задача готовит **только `backend/`** + общий `development/`-оркестратор + скелет `ops/`. Окружение `landing/`/`frontend/` — отдельные задачи (эпики B/C).

- **Touch ONLY (создать):**
  - **Раскладка приложений:**
    - `apps/trendPulse/landing/.gitkeep`, `apps/trendPulse/frontend/.gitkeep` — пустые скелеты (наполнение в эпиках B/C).
  - **Backend (uv + Python 3.12, src-layout):**
    - `apps/trendPulse/backend/pyproject.toml` — name `trendpulse`, `requires-python="==3.12.*"`; deps core: fastapi, uvicorn[standard], celery[redis], redis, sqlalchemy, pgvector, psycopg[binary], alembic, telethon, datasketch, imagehash, pillow, pydantic, pydantic-settings; group `ml`: sentence-transformers; group `dev`: pytest, ruff, mypy, pre-commit, types-*; `[tool.ruff]` + `[tool.mypy]` (strict) + `[tool.pytest.ini_options]` (маркер `integration`); hatchling build `packages=["src/trendpulse"]`.
    - `apps/trendPulse/backend/.python-version` (`3.12`), `apps/trendPulse/backend/uv.lock` (генерится `uv lock`).
    - `apps/trendPulse/backend/Dockerfile` — multi-stage на uv (как эталон: `uv sync --frozen --no-install-project` → копия src → `uv sync --frozen`). Один образ; команда задаётся в compose-сервисах.
    - `apps/trendPulse/backend/.dockerignore`, `apps/trendPulse/backend/.pre-commit-config.yaml` (ruff + ruff-format + базовые хуки; pre-push → `make ci`).
    - `apps/trendPulse/backend/src/trendpulse/`: `__init__.py`, `config.py` (pydantic-settings Settings: `database_url`, `redis_url`, telegram creds), `api/__init__.py`, `api/main.py` (`app=FastAPI()`, `GET /health` → `{"status":"ok"}`), `celery_app.py` (`Celery(broker=…, backend=…)` + skeleton `ping` task), `scheduler.py` (beat_schedule).
    - `apps/trendPulse/backend/alembic.ini`, `apps/trendPulse/backend/migrations/env.py`, `apps/trendPulse/backend/migrations/script.py.mako`, `apps/trendPulse/backend/migrations/versions/.gitkeep` — alembic-скаффолд (прогон — `migration_runner`).
    - `apps/trendPulse/backend/tests/__init__.py`, `tests/conftest.py`, `tests/unit/test_health.py` (TDD-якорь для AC1: `TestClient(app).get('/health')` == 200 + `{"status":"ok"}`).
  - **Development (per-service compose + nginx):**
    - `apps/trendPulse/development/docker-compose.yml` — top-файл: `include:` всех per-service/provisioning compose + объявление сетей `edge`/`internal`/`postgres_net`/`redis_net` (`internal: true` где можно).
    - `apps/trendPulse/development/compose/postgres.yml` — `pgvector/pgvector:pg16`, сеть `postgres_net`, healthcheck `pg_isready`, без published-портов.
    - `apps/trendPulse/development/compose/redis.yml` — `redis:7`, сеть `redis_net`, healthcheck `redis-cli ping`, без published-портов.
    - `apps/trendPulse/development/compose/api.yml` — build `context: ../backend`, команда `uvicorn trendpulse.api.main:app --host 0.0.0.0 --port 8000`, сети `internal`/`postgres_net`/`redis_net`, **без** `ports:`, `depends_on` провижинеры (`service_completed_successfully`), `env_file: [../env/deploy.env, ../env/sensitive.env]`.
    - `apps/trendPulse/development/compose/worker.yml` — тот же образ, команда `celery -A trendpulse.celery_app worker`, сети `postgres_net`/`redis_net`.
    - `apps/trendPulse/development/compose/beat.yml` — тот же образ, команда `celery -A trendpulse.celery_app beat`, сети `postgres_net`/`redis_net`.
    - `apps/trendPulse/development/compose/nginx.yml` — `nginx` (образ `nginx:${NGINX_VERSION}`), сети `edge`/`internal`, `ports: ["80:80","443:443"]`, `depends_on: api`, volume `../provisioning/nginx/nginx.conf`.
    - `apps/trendPulse/development/provisioning/nginx/nginx.conf` — reverse-proxy `proxy_pass http://api:8000`, security-заголовки (HSTS, X-Content-Type-Options, frame-deny), таймауты, лимит тела. (Конфиг edge-прокси живёт в `provisioning/`, не отдельной папкой.)
    - `apps/trendPulse/development/version.env` — **пины версий** (committed, non-secret): `PYTHON_VERSION`, `PG_VERSION`, `PGVECTOR_IMAGE`, `REDIS_VERSION`, `NGINX_VERSION`, `UV_VERSION`. Для compose-интерполяции образов и build-args (ADR-005 §6).
    - `apps/trendPulse/development/provisioning/pg_vector_provisioner/docker-compose.yml` (+ скрипт/команда `CREATE EXTENSION IF NOT EXISTS vector;`) — one-shot, `postgres_net`, `depends_on postgres: service_healthy`.
    - `apps/trendPulse/development/provisioning/migration_runner/docker-compose.yml` — one-shot `alembic upgrade head` на образе backend, `postgres_net`, `depends_on pg_vector_provisioner: service_completed_successfully`.
    - `apps/trendPulse/development/env/deploy.env` — несекретные дефолты (имена БД, порты, имена сетей, URL-шаблоны, фичефлаги). Коммитим.
    - (`development/env/sensitive.env` — НЕ коммитим; создаётся `make ansible-unpack`; покрыт `.gitignore`.)
  - **Ops (скелет, реализация в task-012):**
    - `apps/trendPulse/ops/terraform/.gitkeep`, `apps/trendPulse/ops/terraform/README.md` (что сюда придёт в task-012).
    - `apps/trendPulse/ops/ansible/inventory.ini`, `ops/ansible/group_vars/all.yml` (несекретные дефолты для deploy.env), `ops/ansible/group_vars/vault.yml` (placeholder для секретов, ссылка на ansible-vault), `ops/ansible/README.md`.
  - **Root оркестратор + repo-level:**
    - `apps/trendPulse/Makefile` — **единая точка входа**. Таргеты: `up`, `dev-up`, `dev-infra-up`, `down`, `build`, `logs`, `ps`, `restart`, `sh`, `migrate`, `ansible-unpack`, `lint`, `fmt`, `typecheck`, `test`, `test-integration`, `ci`, `ci-fast`, `help`. Docker-таргеты оборачивают `docker compose -f development/docker-compose.yml …`; dev/CI-таргеты — `uv run --directory backend …`.
    - `apps/trendPulse/.gitignore` (repo-level: `.venv/`, `__pycache__/`, `node_modules/`, `development/env/sensitive.env`, кэши).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме обновления `tasks/tasks-index.md` на ship), содержимое `landing/**` и `frontend/**` (только `.gitkeep`), **реализация** `ops/terraform`/`ops/ansible` (только скелет — реальный IaC в task-012). Никакой бизнес-логики коллектора/pipeline/scorer/billing — только скелет, чтобы процессы стартовали.
- **Blast radius:** нет потребителей (greenfield); задаёт контракты для всех будущих backend-задач — структура пакета `trendpulse`, имена сервисов/сетей, env-переменные, CI-поверхность, build context, старт-ордер и provisioning-конвенции (task-002 расширяет migration_runner/pgvector_provisioner; task-012 наполняет ops/).

## Acceptance Criteria
- [ ] **AC1 — `/health` (failing-test anchor, TDD).** Given пакет `trendpulse` ещё без роутов, When `make ci-fast` (включая `tests/unit/test_health.py` → `TestClient(app).get('/health')`), Then тест сначала FAL (RED, нет эндпоинта), затем после минимальной реализации возвращает `200` + тело `{"status":"ok"}` (GREEN).
- [ ] **AC2 — env материализуется из Ansible.** Given чистый checkout без `development/env/*.env`, When `make ansible-unpack`, Then создаются `development/env/deploy.env` (из `ops/ansible/group_vars`) и `development/env/sensitive.env` (из vault/placeholder); `sensitive.env` под `.gitignore`.
- [ ] **AC3 — `make dev-infra-up` поднимает инфру + провижининг.** Given материализованный env, When `make dev-infra-up`, Then `postgres` и `redis` `healthy`; `pg_vector_provisioner` и `migration_runner` завершаются успешно (exit 0); `SELECT * FROM pg_extension WHERE extname='vector'` находит расширение; `alembic` помечает БД как up-to-date.
- [ ] **AC4 — `make up` поднимает полный стек.** Given dev-infra-up отработал, When `make up` затем `make ps`, Then `nginx`, `api`, `worker`, `beat`, `postgres`, `redis` все `running`/`healthy`; в логах `api` — `Application startup complete`; в логах `worker` — `celery@… ready`.
- [ ] **AC5 — `/health` доступен только через nginx.** Given поднятый стек, When `curl -s http://localhost/health`, Then `200` + `{"status":"ok"}` (трафик идёт nginx → `api:8000`).
- [ ] **AC6 — изоляция портов.** Given поднятый стек, When `make ps` / `docker compose ps`, Then **только** `nginx` публикует host-порты (80/443); `api`, `postgres`, `redis`, `worker`, `beat` НЕ имеют `ports:`-маппингов на хост.
- [ ] **AC7 — CI зелёный.** Given установленное окружение, When `make ci-fast`, Then `ruff format --check` + `ruff check` + `mypy` + `pytest -m 'not integration'` проходят (exit 0).
- [ ] **AC8 — make как единая точка входа.** Given чистый checkout, When `make help`, Then перечислены все таргеты; ключевые действия (`up`/`dev-infra-up`/`down`/`logs`/`migrate`/`ansible-unpack`/`ci`) работают из корня `apps/trendPulse` без ручных `docker compose`/`uv` вызовов и без `-C development`.

## Plan
0. `git init` в `apps/trendPulse` → executor фиксирует `baseline_commit`. Создать каркас `backend/`, `landing/` (+`.gitkeep`), `frontend/` (+`.gitkeep`), `development/`, `ops/`.
1. `backend/pyproject.toml` (core/ml/dev deps, ruff/mypy-strict/pytest, hatchling `src/trendpulse`); `backend/.python-version`; `apps/trendPulse/.gitignore` (incl. `development/env/sensitive.env`); `backend/.dockerignore`.
2. `backend/src/trendpulse/`: `__init__.py`, `config.py` (pydantic-settings), `api/main.py` (`GET /health`), `celery_app.py` (`Celery` + `ping` task), `scheduler.py` (beat_schedule).
3. `backend/tests/`: `__init__.py`, `conftest.py`, `unit/test_health.py` — RED→GREEN якорь для AC1 (пишется ПЕРВЫМ).
4. Alembic-скаффолд в `backend/`: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/.gitkeep` (прогон делегирован `migration_runner`).
5. `backend/Dockerfile` — multi-stage uv; `backend/.pre-commit-config.yaml`.
6. `development/version.env` — пины версий (`PYTHON_VERSION`, `PG_VERSION`, `PGVECTOR_IMAGE`, `REDIS_VERSION`, `NGINX_VERSION`, `UV_VERSION`). compose использует их для образов/build-args; Dockerfile принимает `ARG PYTHON_VERSION`/`ARG UV_VERSION`.
6b. `development/compose/` — `postgres.yml` (`image: ${PGVECTOR_IMAGE}` + `pg_isready` healthcheck), `redis.yml` (`image: redis:${REDIS_VERSION}` + `redis-cli ping`), `api.yml`/`worker.yml`/`beat.yml` (один образ, разные команды, без `ports:`), `nginx.yml` (`image: nginx:${NGINX_VERSION}`, edge, 80/443). Все — с корректными `networks` по network-design.
7. `development/provisioning/nginx/nginx.conf` — `proxy_pass http://api:8000` + security-заголовки/таймауты/лимит тела.
8. `development/provisioning/pg_vector_provisioner/docker-compose.yml` (CREATE EXTENSION vector, one-shot, after postgres healthy) и `development/provisioning/migration_runner/docker-compose.yml` (`alembic upgrade head`, after pgvector). Старт-ордер через `service_completed_successfully`.
9. `development/docker-compose.yml` — top-файл с `include:` всех per-service + provisioning compose и объявлением сетей `edge`/`internal`/`postgres_net`/`redis_net`.
10. `development/env/deploy.env` (несекретные дефолты); `env_file: [../env/deploy.env, ../env/sensitive.env]` во всех app/provisioner-сервисах.
11. `ops/terraform/` (.gitkeep + README) и `ops/ansible/` (inventory, group_vars/all.yml, group_vars/vault.yml placeholder, README) — скелет, реализация в task-012.
12. `apps/trendPulse/Makefile` — root-оркестратор. `COMPOSE := docker compose --env-file development/version.env -f development/docker-compose.yml` (version.env даёт пины образов/версий для интерполяции); docker-таргеты (`up`/`dev-up`/`dev-infra-up`/`down`/`build`/`logs`/`ps`/`restart`/`sh`/`migrate`); `ansible-unpack` (рендер group_vars→deploy.env + vault→sensitive.env в `development/env/`); dev/CI-таргеты (`lint`/`fmt`/`typecheck`/`test`/`test-integration`/`ci`/`ci-fast` через `uv run --directory backend`); `help`.
13. `uv lock` (в `backend/`); `make ci-fast`; `make ansible-unpack && make dev-infra-up && make up` → проверить AC2–AC8 вживую (`make ps`, `curl http://localhost/health`, `pg_extension`, изоляция портов).

## Invariants
- **Root `apps/trendPulse/Makefile` — единственная точка входа.** Работает `make up`, НЕ `make -C development …`. Raw `docker compose` / `uv run` — только внутри таргетов.
- **Наружу торчит только nginx (edge).** api/postgres/redis/worker/beat НЕ публикуют host-порты; api не в `edge`. Сети строго по [network-design.md](../architecture/network-design.md).
- **Старт-ордер фиксирован:** `postgres(healthy) → pg_vector_provisioner → migration_runner → api/worker/beat → nginx` через `depends_on: condition: service_completed_successfully`/`service_healthy`. App НЕ стартует до успешного провижининга.
- **Миграции — только через `migration_runner`** (`alembic upgrade head`), не инлайн в app-старте. ORM = SQLAlchemy 2.0, миграции = Alembic.
- **Ansible — единственный источник истины по env.** Локально и на prod `deploy.env`/`sensitive.env` материализуются `make ansible-unpack`; секреты только в `sensitive.env` (gitignore), никогда в образах/коде.
- **Версии пинятся в `development/version.env`** (committed). Никаких `latest`/незакреплённых тегов в compose/Dockerfile — все образы/build-args берут версию оттуда, чтобы сборка была детерминированной (ADR-005 §6).
- **Один образ приложения** для `api`/`worker`/`beat` — различие только в команде (нет дрейфа окружений).
- **Per-service compose** + top `include:` — изменения сервиса изолированы; новый провижинер = папка + compose + подключение в include.
- ML-deps (`torch`) не в критическом пути старта `api` (группа `ml`, только worker).
- `src`-layout: импорт `trendpulse.*`, не относительные хаки из CWD.

## Edge cases
- `make up` без предварительного `make ansible-unpack` → нет `sensitive.env` → compose упадёт на отсутствии `env_file`. Митигировать: `ansible-unpack` создаёт оба файла; документировать как обязательный первый шаг (ADR-005 §Consequences).
- pgvector: дефолтный `postgres:16` НЕ содержит расширения → обязательно `pgvector/pgvector:pg16`; `pg_vector_provisioner` идемпотентен (`IF NOT EXISTS`).
- Гонка старта: app/провижинеры стартуют раньше готовности БД/Redis → `healthcheck` (`pg_isready`/`redis-cli ping`) + `depends_on: condition: service_healthy` / `service_completed_successfully`.
- One-shot провижинеры должны давать exit 0 при повторном запуске (миграции уже применены, extension уже есть) — иначе `make up` будет циклически падать.
- nginx без TLS-сертификатов локально → слушаем 80; 443/HSTS — конфиг готов, серты подкладываются на prod (ops/terraform). Не публиковать api-порт «для отладки» — нарушит изоляцию (AC6).
- `sentence-transformers` тянет torch (~2GB) → группа `ml`, только worker-образ; api лёгкий.
- `psycopg` build на slim-образе → `psycopg[binary]`.
- `uv sync --frozen` в Docker требует закоммиченного `uv.lock` — сгенерировать ДО сборки образа.
- `internal: true` сети не имеют egf-маршрута наружу → провижинеры/app не должны лезть в интернет на старте (кроме pull образов, который вне сети контейнера).

## Test plan
- **unit:** `tests/unit/test_health.py` — `TestClient(app).get('/health')` == 200 + `{"status":"ok"}` (пишется ПЕРВЫМ, RED — AC1).
- **integration (по требованию, маркер `integration`):** smoke `celery ping` через реальный Redis на поднятом стеке.
- **runtime/behavioral (G2):**
  - `make ansible-unpack` → файлы `development/env/deploy.env` + `sensitive.env` существуют (AC2).
  - `make dev-infra-up` → `make ps` показывает postgres/redis healthy; провижинеры exit 0; `psql -c "SELECT extname FROM pg_extension WHERE extname='vector'"` находит расширение; `alembic current` = head (AC3).
  - `make up` → `make ps` (все running/healthy, AC4); `curl -s http://localhost/health` == `200 {"status":"ok"}` (AC5); проверка, что только nginx публикует порты (AC6).
  - `make help` перечисляет таргеты; команды работают из корня без `-C development` (AC8).
- **ci:** `make ci-fast` (ruff format --check + ruff check + mypy + pytest -m 'not integration') exit 0 (AC7).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "c1790601c34b802534b8d8ee6ab0b6ef3724d7fd"
branch: "gsd/phase-001-dev-environment"
lock: ""
- [x] 1 locate
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do
- [x] 4 verify
- [x] 5 review
- [x] 5.5 security (PASS — 0 blocking; MEDIUM/LOW debt → task-012/prod)
- [x] 6 ship (merged to main as 4cf985b)
- [x] 7 learnings
debug_runs:
  - cycle: 1
    where: backend/Dockerfile
    symptom: "make build → 'variable expansion is not supported for --from' (COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION})"
    root_cause: "buildkit forbids variable interpolation directly in COPY --from image ref"
    fix: "ввёл отдельный stage `FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv` и COPY --from=uv; rebuild → exit 0 (образ 1.16GB, без torch)"
  - cycle: 2
    where: development/compose/nginx.yml
    symptom: "make up → nginx 'Bind for 0.0.0.0:443 failed: port is already allocated'"
    root_cause: "host-порт 443 занят другим проектом (micropich-nginx); наш nginx.conf слушает только 80 (443 ssl закомментирован как prod-only) → публикация 443 локально мертва и конфликтна"
    fix: "публикуем только ${HTTP_PORT:-80}:80; 443 включается на prod вместе с TLS-блоком+сертами (ADR-005/ops). Соответствует edge-case задачи."
  - cycle: 3
    where: "backend/Dockerfile + config.py + compose (api/worker/beat/nginx) + nginx.conf"
    symptom: "review-стадия: 1 HIGH (dev-группа запекается в runtime-образ) + MEDIUM (пароль БД в коде/committed deploy.env; нет api healthcheck → 502-гонка; redis не в depends_on)"
    root_cause: "uv sync --frozen с default-groups=[dev] ставит dev-инструменты в образ; database_url с литералом-паролем; nginx depends_on api без service_healthy; redis вне старт-ордера app"
    fix: "Dockerfile: uv sync --frozen --no-dev (оба слоя) → pytest отсутствует в образе (подтв. ModuleNotFoundError), core импортируется. config.py: database_url собирается из POSTGRES_* (пароль только из sensitive.env), убран DATABASE_URL из all.yml/deploy.env. api: healthcheck (stdlib urllib /health); nginx depends_on api condition: service_healthy; redis: service_healthy в depends_on api/worker/beat. nginx.conf: server_tokens off. Re-verify PASS (api healthy, nginx ждёт healthy, curl 200)."

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план приведён в соответствие с ADR-005 (root Makefile, per-service compose + include, provisioning, env split из Ansible, ops-скелет) и network-design.md (сегментация сетей, только nginx наружу, старт-ордер). Backend-эталон — /Users/macbookpro16/work/ma/prediction. Depends on: — (foundation).)

### Step 3 — do (TDD) · loop-20260608-184532
- **RED→GREEN:** `tests/unit/test_health.py` написан первым (AC1), затем минимальный `api/main.py` (`GET /health` → `{"status":"ok"}`, pure, typed `HealthResponse`). `make ci-fast` зелёный: ruff format ✓ · ruff check ✓ · mypy strict (6 файлов) ✓ · pytest 1 passed.
- **Создано:** backend (pyproject `==3.12.*`, hatchling src-layout, ruff/mypy-strict/pytest; `config.py` pydantic-settings; `celery_app.py`+`ping`; `scheduler.py`; alembic-скаффолд env.py/ini/versions; Dockerfile multi-stage uv параметризован PYTHON/UV_VERSION; `uv.lock`). development (version.env с пинами + APP_IMAGE; per-service compose postgres/redis/api/worker/beat/nginx; top docker-compose.yml через include + сети edge/internal/postgres_net/redis_net с internal:true; nginx.conf reverse-proxy+security-headers; pg_vector_provisioner + migration_runner one-shot; deploy.env; ansible-unpack.sh stub). ops/ скелет (terraform README+.gitkeep, ansible inventory/group_vars/vault/README). landing+frontend .gitkeep. Root Makefile (16 таргетов) + .gitignore.
- **Инварианты подтверждены статически:** только nginx имеет `ports:`; `docker compose config` валиден (8 сервисов, сети мёржатся, EXIT 0); `ml` (sentence-transformers→torch) НЕ в default-groups → не тянется в app-образ; кэши/`sensitive.env` под .gitignore (не staged).
- **Решение:** `ansible-unpack` на task-001 — dependency-free stub-рендерер `key: value` YAML → env (реальный ansible-vault в task-012). `default-groups=["dev"]` (CI-инструменты доступны; ml — opt-in `--group ml`).

### Step 4 — verify (G2, реальная behavioral) · loop-20260608-184532 · PASS
Все 8 AC подтверждены на живом стеке (2 debug-цикла, см. debug_runs):
- **AC1/AC7** — `make ci-fast` зелёный (ruff format ✓ · ruff check ✓ · mypy strict 6 файлов ✓ · pytest 1 passed); health RED→GREEN.
- **AC2** — `make ansible-unpack` → `development/env/deploy.env` + `sensitive.env` (mode 600, gitignored).
- **AC3** — `make dev-infra-up`: postgres+redis healthy; `pg_vector_provisioner` exit 0; `migration_runner` exit 0 (`alembic upgrade head`); `SELECT extname FROM pg_extension WHERE extname='vector'` → `vector`.
- **AC4** — `make up`+`make ps`: nginx/api/worker/beat/postgres/redis все Up (postgres/redis healthy); api-лог `Application startup complete.`; worker-лог `celery@… ready.`; beat `Starting…`.
- **AC5** — `curl -s http://localhost/health` → `200 {"status":"ok"}` (через nginx→api:8000). Прямой `http://localhost:8000` с хоста → недоступен (000) — подтверждает «только через nginx».
- **AC6** — изоляция портов: только `nginx` публикует `0.0.0.0:80->80`; api/worker/beat без `ports`; postgres/redis — только internal `5432/tcp`/`6379/tcp` (без host-маппинга).
- **AC8** — `make help` перечисляет все таргеты; все команды работают из корня `apps/trendPulse` без `-C development`.
Стек свёрнут `make down` (гигиена ресурсов).

### Step 5 — review (adversarial, opus, ≠ do) · loop-20260608-184532
Вердикт: changes-required → 1 HIGH + 3 MEDIUM устранены в debug-цикле 3 (см. debug_runs), re-verify PASS.
- **HIGH (исправлено):** runtime-образ запекал dev-группу → `--no-dev`; подтверждено `pytest` отсутствует в образе, core импортируется.
- **MEDIUM (исправлено):** пароль БД вне кода/committed-env (только sensitive.env); api healthcheck + nginx `service_healthy` (устранена 502-гонка); redis в depends_on app.
- **Отложено (non-blocking, в learnings/будущие задачи):** ruff-pre-commit rev vs CI-версия (LOW); worker на internal:true-сетях не имеет egress → **task-002** (Telethon/model pull) потребует egress-сеть или build-time model cache (LOW, важно для следующей задачи); redis без requirepass (LOW, defense-in-depth, prod-hardening).

### Step 5.5 — security (security-reviewer, opus) · PASS
0 блокирующих (CRITICAL/HIGH). Секреты не утекают: `sensitive.env` gitignored + не tracked + mode 600; в образ секреты не запекаются (build-args только версии); изоляция сетей корректна (только nginx наружу; postgres/redis на internal:true без host-портов); `ansible-unpack.sh` injection-safe. Нечего ротировать. Долг (MEDIUM/LOW) → **task-012**: реальный ansible-vault (vault.yml сейчас plaintext-placeholder), pre-commit secret-scan, redis requirepass, CSP когда появятся HTML-ответы. Часть (пароль БД из кода/deploy.env) уже закрыта в цикле 3.
