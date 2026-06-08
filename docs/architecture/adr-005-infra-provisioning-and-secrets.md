# ADR-005 — Infra layout: per-service compose, provisioning, env split, IaC

- Status: **Accepted**
- Date: 2026-06-08
- Context: [network-design.md](./network-design.md), [high-level-architecture.md](./high-level-architecture.md)

## Context

Нужно: управлять всем через `make` (короткие команды `make up`/`make down`/`make dev-infra-up`), поднимать инфру отдельно, гонять провижининг (миграции + pgvector) перед стартом приложения, разделить env на «безопасные» и «секретные», и держать prod-конфигурацию как IaC. Источник переменных — Ansible.

## Decision

### 1. Единая точка входа — root `Makefile`

`apps/trendPulse/Makefile` (НЕ `development/Makefile`) — чтобы работало `make up`, а не `make -C development build`. Таргеты:

| Команда | Что делает |
|---|---|
| `make up` | поднять всё (инфра → провижининг → app → nginx) |
| `make dev-up` | dev-режим (app с reload), инфра поднята |
| `make dev-infra-up` | поднять **только** инфру (postgres, redis) + провижининг |
| `make down` | остановить всё |
| `make build` | собрать образы |
| `make logs` / `make ps` / `make restart` / `make sh` | операционка |
| `make migrate` | прогнать `migration_runner` |
| `make ansible-unpack` | вытащить/отрендерить env из Ansible в `development/env/` (см. §4) |
| `make lint` / `fmt` / `typecheck` / `test` / `ci` / `ci-fast` | dev/CI (uv run в `backend/`) |
| `make help` | список таргетов |

Makefile вызывает `docker compose` с набором per-service файлов; пользователь docker compose напрямую не трогает (CONVENTIONS).

### 2. Per-service compose + `include`

`development/compose/` — по файлу на сервис:
```
development/
├── docker-compose.yml          # top: include всех ниже + определение networks
├── version.env                 # §6 — пины версий deps/образов (committed)
├── compose/
│   ├── nginx.yml
│   ├── api.yml
│   ├── worker.yml
│   ├── beat.yml
│   ├── postgres.yml
│   └── redis.yml
├── provisioning/               # §3
│   ├── pg_vector_provisioner/
│   ├── migration_runner/
│   └── nginx/                   # nginx.conf, tls (конфиг reverse-proxy)
└── env/                        # §4 (deploy.env, sensitive.env)
```
Top-`docker-compose.yml` через `include:` собирает сервисы и объявляет сети (`edge`, `internal`, `postgres_net`, `redis_net` — см. network-design). Каждый сервис объявляет свои `networks`, `healthcheck`, `env_file`.

### 3. Provisioning (one-shot, перед стартом app)

`development/provisioning/` — каждый провижинер со **своим** compose-файлом; здесь же лежит конфиг reverse-proxy:
- `pg_vector_provisioner/` — `CREATE EXTENSION IF NOT EXISTS vector;` (выполняется после healthy `postgres`, до миграций).
- `migration_runner/` — `alembic upgrade head` (после pgvector).
- `nginx/` — `nginx.conf` + tls (монтируется в сервис `nginx`; конфиг — часть провижининга edge, а не отдельная папка).
Зависящие сервисы (`api`/`worker`/`beat`) стартуют только при `condition: service_completed_successfully` обоих провижинеров. Порядок: `postgres(healthy)` → `pg_vector_provisioner` → `migration_runner` → app. Новый провижинер (например, сидер) добавляется как папка + compose, подключается в top-include.

### 4. Env split: `deploy.env` + `sensitive.env`, источник — Ansible

- `deploy.env` — **несекретные дефолты** (имена БД, порты, имена сетей, URL-шаблоны, фичефлаги). Не страшно слить; может коммититься.
- `sensitive.env` — **секреты** (пароль БД, JWT secret, NOWPayments API key/IPN secret, OAuth client secret, Telegram pool creds). Гитигнор; на VPS прилетают из Ansible.
- Локально оба лежат в `development/env/` и **берутся из Ansible** перед запуском: `make ansible-unpack` рендерит `deploy.env` из `group_vars/*` и расшифровывает `sensitive.env` из ansible-vault → в `development/env/`. **Ansible — единственный источник истины** по переменным (и локально, и на prod).
- compose: `env_file: [../env/deploy.env, ../env/sensitive.env]`.

### 5. `ops/` — IaC

`apps/trendPulse/ops/`:
- `ops/terraform/` — внешние сервисы через IaC (DNS, VPS/провайдер, firewall/edge).
- `ops/ansible/` — playbooks, `group_vars` (prod settings + defaults), `vault` (секреты), inventory; доставляет `deploy.env`/`sensitive.env` на VPS и локально (источник переменных). `make ansible-unpack` дёргает именно отсюда.

### 6. `version.env` — пины версий (воспроизводимость сборки)

`development/version.env` — **закоммиченный, несекретный** файл с версиями всех зависимостей/образов, чтобы локально, в CI и на prod собиралось/поднималось **одинаково**. Пример:

```dotenv
# development/version.env — pinned deps/images (committed, non-secret)
PYTHON_VERSION=3.12
PG_VERSION=16
PGVECTOR_IMAGE=pgvector/pgvector:pg16
REDIS_VERSION=7
NGINX_VERSION=1.27
UV_VERSION=0.7.12
```

- Назначение — **compose-интерполяция и build-args**, а не переменные внутри контейнера: `image: ${PGVECTOR_IMAGE}`, `image: redis:${REDIS_VERSION}`, `image: nginx:${NGINX_VERSION}`, `ARG PYTHON_VERSION`/`ARG UV_VERSION` в Dockerfile.
- `make`-таргеты передают его как `docker compose --env-file development/version.env -f development/docker-compose.yml …` (отдельно от `env_file:` сервисов — тот про runtime-env контейнера, а `version.env` про интерполяцию/сборку).
- Меняем версию — только здесь, в одном месте; pin'ы коммитятся → детерминированная сборка.

## Consequences

- (+) `make up` и понятные dev-команды; инфра отдельно и стабильна.
- (+) БД готова (extension+миграции) до старта app — нет гонок «таблиц ещё нет».
- (+) Один источник переменных (Ansible) для локали и prod; чёткое разделение секретов.
- (+) Per-service compose — изменения изолированы, провижинеры расширяемы.
- (−) Больше файлов/движущихся частей; `make ansible-unpack` обязателен перед первым `up`.
- Влияет на: **task-001** (всё это), **task-002** (migration_runner/pgvector_provisioner), **task-012** (ops/IaC реализация).
