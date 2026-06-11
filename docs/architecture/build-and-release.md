# TrendPulse — Build & Release

> Как проект собирается сегодня (Docker + uv + per-service compose) и как будет дистрибутироваться в будущем (OCI-артефакты через **ORAS** в `release`-репо → один VPS-бандл). Будущая часть — **только при проектировании**, не реализуем сейчас.

Связано: [high-level-architecture.md](./high-level-architecture.md), [ADR-005](./adr-005-infra-provisioning-and-secrets.md), [ADR-006](./adr-006-packaging-and-release.md), [network-design.md](./network-design.md).

---

## 1. Сборка backend-образа (сейчас)

Multi-stage на `uv` (эталон `ma/prediction`): зависимости ставятся по `uv.lock` отдельным слоем, затем код. Один образ для `api`/`worker`/`beat` — различие лишь в команде запуска.

```mermaid
flowchart LR
    src["backend/ src · pyproject.toml · uv.lock"] --> s1
    subgraph build[Dockerfile · multi-stage uv]
        s1["uv sync --frozen --no-install-project\n(слой зависимостей, кэшируется)"] --> s2["COPY src/"] --> s3["uv sync --frozen\n(install project)"]
    end
    s3 --> img[["trendpulse image\n(versioned tag)"]]
    img --> api[api: uvicorn]
    img --> worker[worker: celery worker]
    img --> beat[beat: celery beat]
```

## 2. Ассемблирование окружения (compose `include`)

`development/docker-compose.yml` через `include:` собирает per-service файлы и объявляет сети. `make` — единственная точка входа.

```mermaid
flowchart TB
    mk["root Makefile\nmake up / dev-infra-up / down"] --> top["development/docker-compose.yml (include:)"]
    top --> nginx[compose/nginx.yml]
    top --> apiy[compose/api.yml]
    top --> wy[compose/worker.yml]
    top --> by[compose/beat.yml]
    top --> pgy[compose/postgres.yml]
    top --> rdy[compose/redis.yml]
    top --> prov["provisioning/* (pg_vector_provisioner, migration_runner, nginx/ conf+tls)"]
    top --> nets["networks: edge · internal · postgres_net · redis_net"]
    env["development/env/{deploy,sensitive}.env\n← make ansible-unpack (Ansible source of truth)"] --> top
    ver["development/version.env\npinned PG/REDIS/NGINX/PYTHON/UV versions"] -->|"--env-file (interpolation)"| top
```

## 3. Старт-ордер (provisioning перед app)

```mermaid
flowchart LR
    pg[(postgres · healthy)] --> pv[pg_vector_provisioner\nCREATE EXTENSION vector] 
    pv --> mr[migration_runner\nalembic upgrade head]
    rd[(redis · healthy)] --> app
    mr --> app[api · worker · beat]
    app --> ng[nginx · edge]
    classDef oneshot fill:#fff3cd,stroke:#d39e00;
    class pv,mr oneshot;
```

`api`/`worker`/`beat` ждут `condition: service_completed_successfully` обоих провижинеров (ADR-005 §3).

## 4. `release/`-бандл + Docker Swarm (СЕЙЧАС — TASK-057)

Прод деплоится **не** из `development/`, а из самодостаточного бандла
[`apps/trendPulse/release/`](../../release/README.md) — структура зеркалит
`development/` (top-compose с `include:` + `compose/*` + `provisioning/*` +
`version.env` + `env/` + `scripts/`), но с операторским контрактом ironfist
(`Makefile`/`validate`/`README`/`RELEASE.md`/`deployment.example/`) и оркестрацией
**Docker Swarm** (single-node) вместо `compose up`.

Чем отличается от dev-бандла: нет mailpit (прод-SMTP = Resend); образы тегируются
`:${APP_VERSION}` (не `:dev`); у каждого сервиса swarm-блок `deploy:` (replicas,
resources.limits, `update_config: order: start-first` + `failure_action: rollback`,
`rollback_config`, restart_policy); nginx — 443/TLS + редирект 80→443 +
security-headers (envsubst-шаблон, `${DOMAIN}`); сети `overlay`; провижинеры —
swarm-джобы (`deploy.mode: replicated-job`); beat строго `replicas: 1`.

**Рендер-пайплайн** (инкапсулирован в `release/Makefile` target `render`) — почему
не `docker stack deploy -c docker-compose.yml` напрямую: `stack deploy` игнорирует
`include:`/`env_file:`/`build:`/`depends_on.condition`. Поэтому деплой идёт ТОЛЬКО
через `compose config`:

```
docker compose --project-name trendpulse \
  --env-file version.env --env-file env/deploy.env --env-file env/sensitive.env \
  -f docker-compose.yml config \
| sed '/^name:/d'                          # убрать top-level name: (старые docker его отвергают)
| docker stack deploy --compose-file -      # через stdin — секреты НИКОГДА не на диске
    --detach=false --resolve-image never trendpulse
```

`compose config` разворачивает `include:`, инлайнит `env_file:` в `environment:`,
интерполирует `${...}`. `--resolve-image never` обязателен (образы локальные;
иначе swarm лезет в Hub). `--detach=false` ждёт сходимости и даёт ненулевой exit
при фейле (гейт для ansible). После — `make deploy-wait` поллит
`docker stack services` до «все replicated running + оба job Complete».

Вход — один `make deploy` (обёртка `ansible-playbook site.yml -l prod`):
provision (Docker + **swarm init** + ufw) → env-роль рендерит в `release/env/` →
build образов с тегом `app_version` → `make -C release deploy` → `deploy-wait` →
роль `tls` (certbot + renew-timer) → showcase-init → smoke (последняя таска,
гейтит). **CD по тегу** (`.github/workflows/deploy-tag.yml`) вызывает ТОТ ЖЕ
ansible-путь по push semver-тега `v*` — одна логика, два триггера; версия сквозная
от тега до образов и Sentry `release`.

## 5. Дистрибуция через ORAS (СЛЕДУЮЩИЙ ШАГ поверх бандла)

Каждое приложение/бот (`trendPulse` и будущие боты в `botnet/apps/*`) собирается в **версионированный OCI-образ** и публикуется как **OCI-артефакт через ORAS** в репозиторий `botnet/release`. `release` агрегирует все боты как **зависимости** и собирает **один удобный VPS-деплой** (единый bundle: pinned-ссылки на артефакты + общий compose/манифест + сети + provisioning).

```mermaid
flowchart LR
    subgraph apps[botnet/apps/*]
        tp["trendPulse → OCI image + manifest"]
        b2["bot-2 (future)"]
        b3["bot-3 (future)"]
    end
    tp -->|oras push| reg[("release registry\n(OCI artifacts, semver)")]
    b2 -->|oras push| reg
    b3 -->|oras push| reg
    reg --> rel["botnet/release\naggregate as dependencies"]
    rel -->|assemble| bundle[["single VPS deploy bundle\ncompose + pinned artifacts"]]
    bundle -->|oras pull + up| vps[(VPS)]
```

### Что это требует от дизайна УЖЕ сейчас (чтобы потом «просто заработало»)

- **12-factor config:** вся конфигурация — через env (`deploy.env`/`sensitive.env`), никаких build-time привязок к хосту/путям. Образ переносим как есть.
- **Версионирование:** образы и артефакты тегируются semver; деплой ссылается на pinned-версии (воспроизводимость).
- **Самодостаточность образа:** один образ `api`/`worker`/`beat`, команда — снаружи; нет «магии» вне контейнера.
- **Сети/секреты — декларативно:** топология сетей (network-design) и секреты (Ansible/vault) описаны так, что `release`-бандл их переиспользует, а не переопределяет.
- **Provisioning как артефакт:** `pg_vector_provisioner`/`migration_runner` — тоже образы/шаги, переносимые в бандл.

> Реализация ORAS/`release`-агрегата — **следующий шаг поверх бандла `release/`**
> (TASK-057 заложил структуру: single-node swarm = посадочная площадка, бандл
> самодостаточен и версионирован). ORAS добавляет registry-дистрибуцию вместо
> build-on-host и агрегацию нескольких бот-стеков на один swarm. См.
> [ADR-006](./adr-006-packaging-and-release.md).
