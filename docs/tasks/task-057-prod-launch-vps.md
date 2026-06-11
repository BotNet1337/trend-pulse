---
id: TASK-057
title: Прод-запуск на VPS — release-бандл + Docker Swarm, make deploy одной командой
status: review              # planned → in-progress → review → done
owner: infra
created: 2026-06-10
updated: 2026-06-11
baseline_commit: "e9070d3"
branch: "gsd/phase-launch-prod-vps"
tags: [launch, infra, ansible, swarm, release, ops, ci-cd]
---

# TASK-057 — Прод-запуск на VPS: `release/`-бандл + Docker Swarm (Launch)

> Финальная миля E0→продакшн. Владелец вписывает ТОЛЬКО креды (IP VPS + SSH-ключ + домен +
> недостающие vault-ключи) — всё остальное делает `make deploy`: provision (Docker + **swarm
> init**) → деплой **`release/`-бандла** через **`docker stack deploy`** → миграции (swarm
> jobs) → showcase-init → TLS → smoke «регистрация → сигнал».
> Поверх этого — **CD по git-тегу**: `git tag v1.2.3 && git push --tags` запускает тот же
> деплой из GitHub Actions без участия владельца.
> Принцип владельца: «всё настраивается само, без мануальных действий».

## Context

Уже есть: `ops/ansible/site.yml` = provision.yml (Docker engine+compose) + deploy.yml
(git checkout по `app_version` → env-роль (рендер env из vault в `development/env/`) →
backup-роль (cron pg_backup, TASK-034) → `docker_compose_v2 up` по
`development/docker-compose.yml`). Vault разблокирован, интерполяция env починена (PR #45).

Проблема текущего подхода: **прод деплоится из `development/`** — dev-бандла с mailpit,
`:dev`-тегами, nginx-конфигом без 443 и compose-семантикой `docker compose up` (нет
rolling-update, нет декларативной сходимости). Эталон целевой структуры — два источника:

1. **`~/work/ironfist/ironfist/release/`** — самодостаточный операторский бандл:
   `Makefile` (единственная точка входа: `validate`/`up`/`down`/`logs`/`status`),
   слоёные env-файлы (`vendor.env` коммитится / `deployment/` — only-on-host,
   с коммитнутым шаблоном `deployment.example/`), `README.md` (рантайм-runbook),
   `RELEASE.md` (инкрементальные ручные шаги по версиям), `provisioning/`, `nginx/`.
   Принцип: «всё в бандле статично, оператор трогает только `deployment/`».
2. **`apps/trendPulse/development/`** — наша сборка окружения: top-level
   `docker-compose.yml` с `include:` per-service фрагментов (`compose/*.yml`),
   `provisioning/` (pg_vector_provisioner, migration_runner, nginx-conf),
   `version.env` (pinned-образы, interpolation-only), `env/{deploy,sensitive}.env`
   (рендерятся ansible, gitignored), `scripts/`.

TASK-057 = синтез: **новая папка `apps/trendPulse/release/`** со структурой как у
`development/`, но операторским контрактом как у ironfist, и оркестрацией **Docker Swarm**
(single-node) вместо `compose up`. Это же шаг к ADR-006: будущий `botnet/release`-агрегат
деплоит несколько бот-стеков на один swarm — структура закладывается сейчас.

TLS: 443 + certbot НЕ настроены. Inventory: `group_vars/prod.yml` есть; hosts-файл с
реальным IP — вход владельца. Smoke: `docs/full-system-test.md` §A3 — curl-сценарий.

CI уже есть (GitHub Actions, repo root = `apps/trendPulse`): `pr-checks.yml` (PR-гейты)
и `main-integration.yml` (integration+E2E на push в main, least-privilege permissions,
concurrency-группы). CD-workflow нет — деплой пока только с машины владельца. Эта задача
добавляет третий workflow: **деплой по тегу** тем же ansible-путём, что и локальный
`make deploy` (одна логика, два триггера).

## Goal

`make deploy` (обёртка `ansible-playbook site.yml -l prod`) доводит ГОЛЫЙ Ubuntu-VPS до
работающего HTTPS-продакшна на **Docker Swarm** и зелёного smoke-теста без ручных шагов.

Целевое состояние:
- В репо появляется **`apps/trendPulse/release/`** — самодостаточный прод-бандл
  (см. Layout ниже): свой `Makefile`, свой top-level compose с `include:`, pinned
  `version.env` с прод-тегами, `env/` под ansible-рендер, прод-nginx с 443.
- На хосте стек живёт как **swarm stack `trendpulse`**: `docker stack deploy` идемпотентен,
  healthcheck-гейтед, rolling-update с автооткатом (`update_config`/`rollback_config`).
- Провижинеры (pg_vector, migrations) — **swarm jobs** (`deploy.mode: replicated-job`),
  идемпотентные по построению.
- Вход владельца — один файл `ops/ansible/inventory/prod.yml` (IP/ssh-ключ/домен;
  шаблон-example в гите) + заполненный vault. Smoke: register→login→watchlist→/ready
  после деплоя (последняя таска playbook), фейл = фейл деплоя.
- **CD по тегу:** push тега `v*` → workflow `deploy-tag.yml` (GitHub `environment:
  production`) собирает inventory из GitHub Secrets, проверяет что тег стоит на зелёном
  main-коммите, и запускает ТОТ ЖЕ `ansible-playbook site.yml -l prod -e
  app_version=<tag>`. Релиз = `git tag vX.Y.Z && git push origin vX.Y.Z`. Ручной
  `make deploy` с ноутбука остаётся рабочим fallback'ом (та же команда, тот же код).
- `development/` и локальный `make up` НЕ меняются (dev остаётся на compose).

DoD = AC.

## Discussion

- **Q: Почему Swarm, а не compose up на проде?** → Decision: `docker stack deploy`
  декларативен и идемпотентен (повторный deploy = diff-сходимость, не re-up), даёт
  rolling-update + автооткат по healthcheck (`update_config.failure_action: rollback`),
  restart_policy управляется оркестратором, secrets/configs-механизм доступен на будущее,
  и один swarm — посадочная площадка для будущего мульти-бот `botnet/release` (ADR-006).
  K8s — оверкилл для одного VPS. Single-node swarm: `docker swarm init` и всё.

- **Q: Как структурировать `release/`?** → Decision: зеркало `development/`
  (top-compose + `include:` + `compose/*.yml` + `provisioning/` + `version.env` + `env/` +
  `scripts/`) + операторский слой ironfist (`Makefile` с `validate`-гейтом,
  `README.md`-runbook, `RELEASE.md`-журнал ручных шагов, `deployment.example/`-шаблоны).
  Бандл самодостаточен: на хосте достаточно `release/` + заполненный `env/` — никаких
  ссылок наружу (в `development/`, в корневой Makefile).

- **Q: `docker stack deploy` не понимает `include:`, `env_file:`, `build:`,
  `depends_on.condition`, `profiles` — как сохранить структуру development?** → Decision:
  **рендер через `docker compose config`**. Канонический пайплайн (инкапсулирован в
  `release/Makefile` target `render`):
  ```
  docker compose --project-name trendpulse \
    --env-file version.env \
    --env-file env/deploy.env \
    --env-file env/sensitive.env \
    -f docker-compose.yml config \
  | <фикс-фильтр: убрать top-level `name:`, ничего больше> \
  | docker stack deploy --compose-file - --detach=false --resolve-image never trendpulse
  ```
  `compose config` разворачивает `include:`, инлайнит `env_file:` в `environment:`,
  интерполирует `${...}` из `--env-file`. Рендер идёт **через pipe в stdin** — файл с
  заинлайненными секретами НИКОГДА не пишется на диск. `--detach=false` — deploy ждёт
  сходимости и возвращает ненулевой exit при фейле (гейт для ansible).

- **Q: Образы — build-on-host или registry?** → Decision: build на хосте (как сейчас),
  registry/ORAS = ADR-006/future. Single-node swarm резолвит локальные образы; флаг
  `--resolve-image never` обязателен (иначе swarm лезет в Docker Hub за digest и падает
  на локальных тегах). Тег = `app_version` (git ref деплоя): `trendpulse-backend:${APP_VERSION}`
  и т.д. — рендерится ansible в `version.env` бандла, build-таска собирает с этим тегом.
  Смена тега при деплое новой версии = триггер rolling-update.

- **Q: Провижинеры (pg_vector, миграции) — где?** → Decision: внутри стека как
  `deploy.mode: replicated-job` + `restart_policy.condition: none` (swarm-идиоматика
  one-shot). `depends_on` swarm игнорирует → `api`/`worker`/`beat` получают
  `restart_policy: on-failure` + healthcheck и спокойно рестартуют, пока миграции не
  применились; `make deploy-wait` (в release/Makefile) поллит `docker service ls` до
  «все replicated сходятся, все jobs Complete» с таймаутом. Оба джоба идемпотентны по
  построению (CREATE EXTENSION IF NOT EXISTS; alembic upgrade head) — повторный deploy
  безопасен.

- **Q: Сети?** → Decision: та же топология network-design.md, но `driver: overlay` +
  `attachable: true` (чтобы one-off `docker run`/exec-утилиты могли подключаться):
  `edge` (публичная), `internal`, `postgres_net`, `redis_net` (все три `internal: true`),
  `egress` (worker → Telegram, НЕ internal). Объявляются в top-compose бандла; stack
  создаёт их с префиксом `trendpulse_`.

- **Q: TLS как?** → Decision: certbot **на хосте** (ansible-роль `tls`: issue standalone
  до первого up ИЛИ webroot после, + systemd renew-timer с `--deploy-hook` на
  `docker service update --force trendpulse_nginx`). Серты bind-mount в nginx-сервис
  (`/etc/letsencrypt:ro`) — для single-node это корректно. Прод-nginx-конфиг — в
  `release/provisioning/nginx/templates/*.conf.template` (механизм envsubst официального
  nginx-образа, `${DOMAIN}` из env): 443/ssl + редирект 80→443 + security-headers
  (паттерн ironfist `nginx/templates/`). Dev-конфиг не трогаем. Флаг `tls_enabled`
  (default true) — выключаемо для smoke-прогона по голому IP.

- **Q: Секреты?** → Decision: без изменений контракта ADR-005 §4 — vault → ansible
  env-роль → `release/env/{deploy,sensitive}.env` на хосте (0600, owner deploy).
  Docker secrets — сознательно НЕ сейчас (рендер через `compose config` инлайнит env;
  переход на secrets — отдельная задача, когда появится ротация). `env/` и
  `deployment/`-аналоги gitignored; коммитятся только `deployment.example/`-шаблоны.

- **Q: Что в release/ отличается от development/?** → Decision (исчерпывающе):
  (1) НЕТ mailpit (прод-SMTP = Resend, креды в vault) и dev-mounts/watch;
  (2) `version.env`: прод-теги `:${APP_VERSION}` вместо `:dev`;
  (3) у каждого сервиса блок `deploy:` (replicas, resources.limits, update_config,
  rollback_config, restart_policy); (4) nginx: 443+TLS-шаблоны; (5) сети overlay;
  (6) провижинеры = replicated-job; (7) pg-backup-фрагмент включён в бандл (cron
  дергает `release/scripts/pg_backup.sh`); (8) операторские файлы: Makefile/README/
  RELEASE.md/deployment.example.

- **Q: Что владелец делает руками?** → Decision (исчерпывающий список, всё остальное —
  само): (1) арендовать VPS (Ubuntu 22.04/24.04, ≥4GB), вписать IP в inventory/prod.yml;
  (2) направить A-запись домена на IP; (3) дозаполнить vault (SMTP уже есть,
  OPS_TELEGRAM_BOT_TOKEN опц., showcase-ключи когда будет TASK-044); (4) **первый** деплой —
  `make deploy` с ноутбука; (5) one-time для CD: завести GitHub Secrets (список ниже).
  Дальше каждый релиз = `git tag vX.Y.Z && git push origin vX.Y.Z`.

- **Q: CD по тегу — как именно?** → Decision: новый workflow
  `.github/workflows/deploy-tag.yml`, триггер `push: tags: ['v*']` + `workflow_dispatch`
  (input `tag` — ручной повторный деплой любой версии). Workflow НЕ содержит собственной
  деплой-логики — он только готовит окружение и вызывает тот же
  `ansible-playbook site.yml -l prod -e app_version=${{ github.ref_name }}`, что и
  локальный `make deploy`. Инвариант «одна логика, два триггера»: любое расхождение
  CI-пути и ручного пути = баг. Шаги джобы:
  (1) checkout тега; (2) gate «тег указывает на коммит, достижимый из main, и
  main-integration на этом коммите зелёный» (`gh api .../check-runs` — иначе fail с
  понятным сообщением); (3) setup python + `pip install ansible` + `ansible-galaxy
  install -r requirements.yml`; (4) ssh-agent с `SSH_PRIVATE_KEY`, known_hosts из
  `SSH_KNOWN_HOSTS` (строгая проверка, не `StrictHostKeyChecking=no`); (5) рендер
  `inventory/prod.yml` из секретов (PROD_HOST/PROD_DOMAIN/LETSENCRYPT_EMAIL) — тот же
  формат, что prod.example.yml; (6) vault-pass из `ANSIBLE_VAULT_PASSWORD` в tmpfile;
  (7) `ansible-playbook site.yml -l prod -e app_version=<tag>`. Smoke внутри playbook
  гейтит → красный workflow = неудавшийся релиз (а swarm уже откатился сам по
  rollback_config).

- **Q: Секреты CD где?** → Decision: GitHub `environment: production` (не repo-level) —
  даёт опциональный required-reviewer-гейт перед деплоем и скоупит секреты. Состав:
  `SSH_PRIVATE_KEY` (отдельный deploy-ключ, НЕ личный ключ владельца; pubkey кладётся
  ansible/terraform в authorized_keys юзера deploy), `SSH_KNOWN_HOSTS` (host key VPS),
  `ANSIBLE_VAULT_PASSWORD` (содержимое .vault-pass), `PROD_HOST`, `PROD_DOMAIN`,
  `LETSENCRYPT_EMAIL`. Vault-файл `sensitive.vault.yml` уже в гите зашифрованным —
  CI расшифровывает его тем же паролем, отдельного дублирования секретов в GitHub нет.

- **Q: Параллельные деплои (два тега подряд)?** → Decision: `concurrency: group:
  prod-deploy, cancel-in-progress: false` — деплои строго последовательны, очередь;
  отмена in-flight ansible-прогона опаснее ожидания.

- **Q: Что считается релизом / версией?** → Decision: аннотированный semver-тег `vX.Y.Z`
  на main. `app_version=<tag>` сквозной: deploy.yml чекаутит его на хосте, build тегирует
  образы `trendpulse-*:vX.Y.Z`, deploy.env получает `RELEASE=vX.Y.Z` (Sentry-события
  фильтруются по версии). Смена тега = триггер rolling-update (см. решение про образы).

## Layout — `apps/trendPulse/release/` (целевая структура)

```
release/
├── Makefile                      # операторская точка входа НА ХОСТЕ (стиль ironfist):
│                                 #   help (awk-самодокументация), validate (env-файлы есть,
│                                 #   docker жив, swarm active), render (compose config-пайплайн),
│                                 #   deploy (render | stack deploy --detach=false),
│                                 #   deploy-wait (поллинг сходимости: replicated running,
│                                 #   jobs Complete), down (stack rm), status (stack ps),
│                                 #   logs [SERVICES=...], smoke, backup-now, restore-check
├── README.md                     # runbook оператора: layout, update-sequence
│                                 #   («скопируй env/ из прошлого релиза → RELEASE.md → make deploy»),
│                                 #   предупреждение «изменил env → make deploy, НЕ restart»
├── RELEASE.md                    # инкрементальные ручные шаги по версиям (журнал, как ironfist)
├── version.env                   # pinned-образы прод (коммитится): PGVECTOR_IMAGE, REDIS_VERSION,
│                                 #   NGINX_VERSION, AWS_CLI_IMAGE, APP_IMAGE=trendpulse-backend:${APP_VERSION},
│                                 #   APP_IMAGE_ML, FRONTEND_IMAGE, TEMPLATES_IMAGE; APP_VERSION
│                                 #   подставляет ansible при деплое (default в гите = последний тег)
├── docker-compose.yml            # top assembly: include: compose/* + provisioning/*,
│                                 #   networks (overlay, attachable; internal по network-design)
├── compose/                      # per-service фрагменты с deploy:-блоками (swarm)
│   ├── api.yml                   #   replicas:1, healthcheck /ready, update_config(order:
│   │                             #   start-first, failure_action: rollback), restart on-failure
│   ├── worker.yml                #   сеть egress; stop_grace_period под долгие таски
│   ├── beat.yml                  #   replicas:1 строго (single scheduler)
│   ├── frontend.yml
│   ├── templates.yml
│   ├── nginx.yml                 #   ports 80/443 (mode: host — реальные client-IP в логах),
│   │                             #   bind /etc/letsencrypt:ro, envsubst-шаблоны
│   ├── postgres.yml              #   named volume pgdata, healthcheck pg_isready,
│   │                             #   placement: node.role==manager (данные прибиты к ноде)
│   ├── redis.yml
│   └── pg-backup.yml             #   образ aws-cli для backup/restore-check сценариев
├── provisioning/
│   ├── pg_vector_provisioner/    # deploy.mode: replicated-job (CREATE EXTENSION IF NOT EXISTS)
│   ├── migration_runner/         # deploy.mode: replicated-job (alembic upgrade head)
│   └── nginx/templates/          # прод-конфиг: 443/ssl, 80→443 redirect, security-headers,
│                                 #   ${DOMAIN} через envsubst nginx-образа
├── env/                          # gitignored — рендерит ansible env-роль (vault → host)
│   ├── deploy.env                #   (non-secret прод-значения: AUTH_COOKIE_SECURE=true,
│   │                             #    SWAGGER_ENABLE=false, SMTP=Resend, FRONTEND_BASE_URL=https://…)
│   └── sensitive.env
├── deployment.example/           # коммитнутые шаблоны env/ с комментарием на каждый ключ
│   ├── deploy.env.example
│   └── sensitive.env.example
└── scripts/                      # pg_backup.sh, pg_restore_check.sh, smoke.sh
                                  #   (smoke.sh: register→login→watchlist→/ready→/trending;
                                  #    параметр HOST; используется и локально, и из playbook)
```

## Scope

- **Touch ONLY:**
  - `release/` — **новая папка целиком** (layout выше). Фрагменты `compose/*` пишутся
    по образцу `development/compose/*` (та же декомпозиция, те же имена сервисов), но
    с swarm-`deploy:`-блоками и без dev-сервисов.
  - `ops/ansible/inventory/prod.example.yml` — **новый** (шаблон: host/IP, user, ssh-key,
    domain, letsencrypt_email, app_version); реальный `inventory/prod.yml` — gitignored.
  - `ops/ansible/playbooks/provision.yml` — добавить: `docker swarm init`
    (идемпотентно: `docker info` → Swarm: active → skip; advertise-addr = private/public IP
    хоста), ufw (22/80/443 only + решение граблей docker-vs-ufw — см. Edge cases),
    preflight-asserts (RAM/disk).
  - `ops/ansible/playbooks/deploy.yml` — **переписать**: git checkout `app_version` →
    env-роль рендерит в `{{ app_dir }}/release/env/` (НЕ development) → build образов
    с тегом `app_version` (`docker compose -f release/docker-compose.yml build` или
    buildx bake) → `make -C release deploy` (render|stack deploy) → `make -C release
    deploy-wait` → showcase-init (`docker exec $(api-container) python -m api.trending`
    через swarm-aware lookup) → smoke (последняя таска, гейтит).
  - `ops/ansible/roles/env/` — параметризовать `env_dir` (→ `release/env`), прод-значения
    deploy.env (cookie secure, swagger off, домены из inventory).
  - `ops/ansible/roles/tls/` — **новая роль**: certbot issue + systemd renew-timer
    (+ deploy-hook `service update --force nginx`) + флаг `tls_enabled`.
  - `ops/ansible/roles/backup/` — путь скриптов → `release/scripts/`.
  - `Makefile` (корневой) — `deploy` (site.yml -l prod), `smoke HOST=…`, help-текст.
  - `.github/workflows/deploy-tag.yml` — **новый** (CD по тегу `v*` + workflow_dispatch:
    green-main-gate → ansible-prep → рендер inventory из secrets → `ansible-playbook
    site.yml -l prod -e app_version=<tag>`; `environment: production`,
    `concurrency: prod-deploy`, least-privilege permissions как в существующих workflows).
  - `.gitignore` — `ops/ansible/inventory/prod.yml`, `release/env/`.
  - `docs/architecture/build-and-release.md` — новый § «release/ bundle + Swarm (сейчас)»,
    ORAS-§ пометить как «следующий шаг поверх бандла».
  - `docs/full-system-test.md` §C — актуализация под make deploy/swarm.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `development/` (НИ ОДНОГО файла — dev-флоу и `make up` не меняются),
  dev-nginx, terraform (VPS уже поднимается TF — вход ansible = IP из inventory),
  существующие `pr-checks.yml`/`main-integration.yml` (новый workflow добавляется рядом,
  старые не правим), backend/frontend-код (кроме нулевых ожиданий: код уже 12-factor).
- **Blast radius:** прод-путь деплоя целиком (deploy.yml переписывается) — но прода ещё
  нет, откатываться не из чего; критично не задеть локальный dev-контракт (общий код —
  только env-роль и backup-роль: проверить, что `make ansible-unpack` по-прежнему рендерит
  в `development/env` для локалки — env_dir параметризован, default не менять).

## Acceptance Criteria

- [ ] **AC1 — release-бандл самодостаточен (failing-check anchor).** `make -C release help`
  и `make -C release validate` работают; validate падает с ЧЕЛОВЕЧЕСКОЙ ошибкой при
  отсутствии `env/*.env` (указывая на deployment.example) и при swarm inactive.
  `make -C release render` на машине с заполненным env выдаёт валидный stack-YAML
  (`docker stack deploy --compose-file - --dry-run` нет, такого флага нет — валидация:
  рендер парсится `docker compose -f - config -q`). ansible-lint/syntax-check зелёные.
  Без inventory/prod.yml корневой `make deploy` падает с подсказкой «скопируй
  prod.example.yml».
- [ ] **AC2 — голый VPS → сходящийся swarm-стек.** На чистом Ubuntu один `make deploy`:
  Docker установлен, swarm active, образы собраны с тегом `app_version`, stack `trendpulse`
  задеплоен, оба jobs (pg_vector, migrations) Complete, все replicated-сервисы running
  + healthy, showcase-init выполнен, бэкап-cron стоит.
- [ ] **AC3 — TLS.** https://домен отдаёт валидный LE-сертификат, 80→443 редирект,
  renew-timer активен (`systemctl list-timers`), deploy-hook перечитывает nginx.
  22/80/443 — единственные открытые порты снаружи (проверка nmap/ss).
- [ ] **AC4 — smoke зелёный и гейтит.** `release/scripts/smoke.sh`:
  register→login→watchlist create→/ready 200→/trending 200; фейл любого шага =
  ненулевой exit deploy (playbook падает).
- [ ] **AC5 — идемпотентность + rolling update.** Повторный `make deploy` без изменений —
  ноль ошибок, jobs переисполняются безопасно, данные целы. Деплой с новым `app_version`
  (изменённый APP_IMAGE-тег) — rolling-update api/frontend без даунтайма
  (`update_config: order: start-first`), при фейле healthcheck — автооткат
  (`failure_action: rollback`) и ненулевой exit.
- [ ] **AC6 — G2 (боевой).** Реальный VPS владельца: make deploy с нуля → браузерный
  прогон «регистрация → сигнал ≤60с» (full-system-test §B с реальными TG-кредами из
  vault); `make backup-restore-check` PASS против прод-бакета.
- [ ] **AC7 — CD по тегу.** На боевом сетапе: `git tag vX.Y.Z && git push origin vX.Y.Z`
  → workflow `deploy-tag.yml` зелёный → на хосте `docker stack ps trendpulse` показывает
  образы `:vX.Y.Z`, https-smoke зелёный, Sentry-события несут `release=vX.Y.Z`.
  Негативные ветки: тег на коммите НЕ с main / с красным main-integration → workflow
  падает на gate-шаге ДО касания VPS; параллельный второй тег встаёт в очередь
  (concurrency), не накладывается.

## Plan

1. **RED (AC1):** скелет `release/` (Makefile c help/validate/render-заглушкой,
   deployment.example, .gitignore) + inventory/prod.example.yml + guard в корневом
   `make deploy`; ansible-lint в ci-режиме. Всё падает осмысленно — якорь.
2. `release/compose/*` + `provisioning/*` + top `docker-compose.yml` + `version.env`:
   перенос из development с swarm-адаптацией (deploy:-блоки, overlay-сети,
   replicated-jobs, минус mailpit/dev-mounts). Локальная проверка: `render` парсится,
   `docker stack deploy` на локальном single-node swarm (docker desktop/Multipass) сходится.
3. `release/provisioning/nginx/templates/` — прод-конфиг 443 + headers; флаг tls_enabled.
4. Ansible: provision.yml (+swarm init, ufw, preflight) → roles/tls → env-роль
   (env_dir → release/env, прод-значения) → deploy.yml (checkout → env → build →
   `make -C release deploy` → deploy-wait → showcase-init → smoke).
5. `release/scripts/smoke.sh` (curl-сценарий §A3 + /trending non-empty после прогрева)
   + Makefile-обвязка (корень + release).
6. README.md/RELEASE.md бандла (update-sequence, ручные шаги первого релиза).
7. CD: `.github/workflows/deploy-tag.yml` (gate → prep → inventory из secrets →
   ansible-playbook); секреты в GitHub `environment: production`; actionlint/проверка
   на тестовом теге против одноразового VPS.
8. Verify: дешёвый прогон на одноразовом VPS/Multipass-VM — AC2–AC5 (включая повторный
   deploy и rolling-update с фейковым плохим образом для проверки rollback) + AC7-прогон
   тегом против того же VPS → G2 на боевом (AC6 + финальный AC7).
9. Docs: build-and-release.md (§ release-бандл + § релиз-флоу «tag → deploy»),
   full-system-test §C, README релиза (как катить релиз), tasks-index.

## Invariants

- Один вход владельца: inventory/prod.yml + vault. Никаких ручных ssh-шагов в runbook.
- `release/` самодостаточен: на хосте оператор работает ТОЛЬКО из release/ (`make -C
  release …`); никаких ссылок бандла на development/ или корневой Makefile.
- Всё в release/ статично и коммитнуто, КРОМЕ `env/` (рендер ansible, gitignored;
  шаблоны — в deployment.example/). Паттерн ironfist «operators touch only deployment/».
- Рендеренный stack-конфиг с заинлайненными секретами существует только в pipe —
  никогда на диске.
- Все таски идемпотентны (повторный deploy безопасен): ansible-идиоматика, swarm
  replicated-jobs идемпотентны по построению, stack deploy = декларативная сходимость.
- Секреты только через vault→env-роль; no_log на чувствительных тасках.
- **Одна деплой-логика, два триггера:** CD-workflow вызывает тот же
  `ansible-playbook site.yml`, что и ручной `make deploy` — никакой деплой-логики
  в YAML workflow (только prep: ключи, inventory, vault-pass).
- CD не хранит прикладные секреты: GitHub Secrets = только доступ (ssh-ключ, vault-pass,
  host/domain); приклад остаётся в ansible-vault в гите.
- Dev-флоу (`make up` локально, compose) не меняется ни одним файлом.
- Версии pinned: version.env бандла — единственное место тегов; никаких `latest`.
  Прод-версия = git-тег, сквозной от workflow до образов и Sentry `release`.

## Edge cases

- **stack deploy игнорирует `env_file`/`include`/`build`/`depends_on.condition`** →
  весь деплой ТОЛЬКО через `render`-target (`compose config`-пайплайн); прямой
  `docker stack deploy -c docker-compose.yml` должен быть невозможен по документации
  README (и бессмыслен — упадёт на include).
- **`compose config` эмитит top-level `name:`** — старые docker отвергают его в stack
  deploy → render-фильтр вырезает; зафиксировать в комментарии Makefile.
- **Локальные образы + swarm** → `--resolve-image never` обязателен; иначе деплой
  ходит в Hub и падает. При будущем registry (ADR-006) флаг убирается одной строкой.
- **`depends_on` не работает** → api/worker/beat могут стартовать до завершения
  миграций: restart_policy on-failure + healthcheck = крутятся до сходимости;
  `deploy-wait` ограничен таймаутом (default 300s) с дампом `stack ps --no-trunc`
  при фейле.
- **Повторный deploy переисполняет jobs** — это норма (идемпотентны); но если job
  упал, stack deploy сам его не перезапустит при неизменном spec → deploy-wait
  детектит Failed-jobs и валит деплой с подсказкой.
- **docker + ufw — известная грабля** (docker пишет iptables в обход ufw): published
  ports у нас только 80/443 (mode: host у nginx) + 22 ssh; решение (DOCKER-USER chain
  или ufw-docker-правила) зафиксировать в provision-роли с комментарием-обоснованием.
- **Домен ещё не резолвится** → certbot fail: tls-роль даёт понятную ошибку и НЕ валит
  http-деплой (tls_enabled=false для прогона по IP).
- **Повторный certbot issue при существующем серте** → `--keep-until-expiring`
  (идемпотентность).
- **beat — строго 1 replica** (дубль scheduler = двойные таски): replicas:1 +
  комментарий-инвариант в beat.yml.
- **postgres на overlay при будущем multi-node** → placement constraint
  `node.role==manager` уже сейчас: данные прибиты, multi-node не разнесёт stateful-сервис.
- VPS с малым диском/без swap → preflight-assert в provision (RAM/disk, warning).
- **GitHub-runner не достучался до VPS по ssh** (22 закрыт для интернета?) → решение:
  22 открыт миру, доступ только по ключам + fail2ban опц.; альтернатива (allowlist
  IP-диапазонов GitHub из meta API) — задокументировать как hardening-опцию, не default.
- **Тег запушен раньше, чем main-integration на коммите дозелёнел** → gate-шаг не
  «red=fail», а poll с таймаутом (wait-for-checks до 20 мин), потом fail; сообщение
  подсказывает перезапустить через workflow_dispatch.
- **Тег переставлен (force-push на другой коммит)** → деплой идёт по коммиту тега,
  «какая версия на проде» отвечает `docker stack ps` (образ `:vX.Y.Z` + label с sha);
  build-таска лейблит образ `org.opencontainers.image.revision=<sha>`.
- **workflow_dispatch с произвольным тегом** = штатный канал отката на прошлую версию
  (rollback-релиз): деплой старого тега — те же гарантии идемпотентности; миграции
  НЕ откатываются автоматически (alembic downgrade — ручная операция, зафиксировать
  в README релиза).
- **Секрет отсутствует/протух** (ssh-ключ отозван, vault-pass сменился) → prep-шаги
  падают ДО ansible с явным именем секрета в сообщении; список секретов — в README
  релиза и в комментарии workflow.

## Test plan

- **static:** ansible-lint + syntax-check; actionlint на deploy-tag.yml; `make -C release
  validate/render` на CI-машине с example-env (рендер парсится `compose config -q`);
  make-таргеты (ci-fast не задет).
- **AC2–AC5:** одноразовый VPS или Multipass-VM — полный прогон с нуля; повторный прогон
  (идемпотентность); прогон с новым тегом (rolling-update); прогон с заведомо битым
  образом (rollback срабатывает, exit ненулевой).
- **AC7:** тестовый тег (`v0.0.1-rc*`) против одноразового VPS из CD-workflow:
  happy-path + негативные ветки (тег не с main; красный check-run; параллельный тег).
- **G2:** боевой VPS + браузерный сценарий + restore-check (AC6) + финальный релиз-тег
  через CD (AC7).
- **security (5.5):** ОБЯЗАТЕЛЬНО — поверхность хоста (ufw+docker iptables, ssh),
  TLS-конфиг (современные шифры, headers-шаблон), секреты не в логах ansible (no_log)
  и не на диске (pipe-рендер), env/ права 0600; CD: least-privilege permissions,
  секреты не в логах workflow (masked), deploy-ключ отдельный и отзываемый,
  known_hosts строгий.

## Checkpoints

current_step: 7
baseline_commit: "e9070d3"
branch: "gsd/phase-launch-prod-vps"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 offline: bundle/ansible/CD validated; live AC6/AC7 owner-blocked — require real VPS + GitHub Secrets)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (REQUIRED — host surface + TLS + secrets)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-10, переработано 2026-06-11: вместо «деплой development/-бандла через
compose up» — отдельный самодостаточный `release/`-бандл (операторский контракт ironfist:
Makefile/validate/README/RELEASE.md/deployment.example; внутренняя структура development:
include-фрагменты/version.env/env/provisioning/scripts) и оркестрация Docker Swarm
(`compose config | stack deploy`, replicated-jobs для провижинеров, rolling-update с
автооткатом). Дополнено 2026-06-11: CD по git-тегу — `.github/workflows/deploy-tag.yml`
(environment: production, green-main-gate, concurrency-очередь) вызывает тот же
ansible-путь с `app_version=<tag>`; релиз = push semver-тега, версия сквозная до образов
и Sentry release. Вход владельца не изменился: VPS+IP, A-запись, vault-ключи, первый
make deploy + one-time GitHub Secrets. Swarm выбран как минимальный декларативный
оркестратор для одного VPS и посадочная площадка ADR-006 (мульти-бот botnet/release
поверх одного swarm).
Зависимости: vault разблокирован (2026-06-10), интерполяция env починена (PR #45),
showcase-init идемпотентен (TASK-039), backup-cron (TASK-034), S3-бакет (TASK-056),
SMTP Resend в vault (2026-06-10).)

### do — что собрано (2026-06-11, checkpoint 3)

**Бандл `apps/trendPulse/release/` (новый, целиком по Layout):**
- `Makefile` — операторская точка входа: help (awk-самодок), validate (env-файлы +
  docker + swarm active, человеческие ошибки), render (compose config | вырезать
  top-level `name:` | вывод в stdout), deploy (render | `docker stack deploy
  --detach=false --resolve-image never`), deploy-wait (поллинг replicated running +
  jobs Complete, таймаут `DEPLOY_WAIT_TIMEOUT`=300s, дамп `stack ps` + детект
  Failed-job), down (stack rm), status, logs [SERVICES=…], smoke, backup-now,
  restore-check.
- `version.env` — прод-теги `:${APP_VERSION}` (APP_VERSION подставляет ansible),
  без mailpit. `docker-compose.yml` — top-assembly с `include:` compose/* +
  provisioning/* + overlay-сети (edge/internal/postgres_net/redis_net internal,
  egress non-internal, все attachable).
- `compose/*` — api/worker/beat/frontend/templates/nginx/postgres/redis/pg-backup,
  у каждого swarm `deploy:` (replicas, resources.limits, update_config
  order:start-first|stop-first + failure_action:rollback, rollback_config,
  restart_policy). beat replicas:1 строго (stop-first, инвариант-коммент); nginx
  ports 80/443 mode:host + `/etc/letsencrypt:ro` + envsubst-шаблоны; postgres
  placement node.role==manager + named volume pgdata. pg-backup НЕ в стеке
  (standalone-фрагмент, joins `trendpulse_postgres_net` external; Makefile-таргеты
  backup-now/restore-check).
- `provisioning/{pg_vector_provisioner,migration_runner}` — `deploy.mode:
  replicated-job` + `restart_policy.condition: none`. `provisioning/nginx/templates/
  nginx.conf.template` — 443/ssl (TLS1.2/1.3 + strong ciphers), 80→443 redirect +
  ACME webroot, HSTS + security-headers, `${DOMAIN}` через envsubst, rate-limit зоны
  (TASK-032).
- `deployment.example/{deploy,sensitive}.env.example` (коммитятся, документируют
  каждый ключ). `env/` gitignored. `scripts/{pg_backup,pg_restore_check,smoke}.sh`
  (smoke: /ready→register→login→watchlist→/trending, параметр HOST, гейтит).
- `README.md` (runbook + update-sequence + «изменил env → make deploy, не restart»),
  `RELEASE.md` (журнал версий, v0.1.0 owner-чеклист).

**Ansible (ops/ansible):**
- `inventory/prod.example.yml` (новый шаблон: host/IP, user deploy, ssh-key,
  prod_domain, letsencrypt_email, app_version, tls_enabled). Реальный prod.yml
  gitignored.
- `playbooks/provision.yml` — preflight RAM/disk (warn), Docker, **swarm init**
  (идемпотентно: `docker info` Swarm:active → skip, advertise-addr=default_ipv4),
  ufw 22/80/443 (+ коммент docker-vs-ufw DOCKER-USER).
- `playbooks/deploy.yml` — переписан: checkout app_version → env-роль в
  `release/env` → pin APP_VERSION → build образов с тегом → `make deploy` →
  `make deploy-wait` → tls-роль → showcase-init (swarm-aware lookup api-контейнера
  по label) → smoke (последняя таска, гейтит).
- `roles/env` — env_dir default НЕ изменён (`development/env` — dev-контракт цел);
  deploy.yml оверрайдит на `release/env`. deploy.env.j2: DOMAIN + prod-URL (HTTPS)
  при `prod_domain` непустом, иначе dev-значения как раньше. FIELD_ENCRYPTION_KEY из
  vault (TASK-032) уже в sensitive.env.j2.
- `roles/tls` (новая) — certbot certonly --standalone --keep-until-expiring
  (идемпотентно) + systemd renew-timer (webroot) + deploy-hook `docker service
  update --force trendpulse_nginx` + флаг tls_enabled (skip при false для bare-IP).
- `roles/backup` — cron → `make -C release backup-now` (пути на release/scripts).
- `requirements.yml` — добавлен community.general (ufw).

**Корень/CI/доки:** root `Makefile` — `deploy` (guard «скопируй prod.example.yml»
если нет inventory/prod.yml → `ansible-playbook site.yml -l prod -i inventory/
prod.yml`), `smoke HOST=…`, help-текст. `.github/workflows/deploy-tag.yml` (новый):
push `v*` + workflow_dispatch(tag) → gate (тег reachable из main + main-integration
зелёный через `gh api check-runs`, poll ≤20мин) → setup python/ansible/galaxy →
ssh-agent (SSH_PRIVATE_KEY) + strict known_hosts (SSH_KNOWN_HOSTS) → рендер
inventory/prod.yml из secrets (PROD_HOST/PROD_DOMAIN/LETSENCRYPT_EMAIL) → vault-pass
из ANSIBLE_VAULT_PASSWORD tmpfile → `ansible-playbook site.yml -l prod -e
app_version=<tag>`; environment:production, concurrency:prod-deploy
cancel-in-progress:false, permissions:contents:read. `.gitignore` — release/env/ +
inventory/prod.yml. Доки: build-and-release.md §4 «release/ bundle + Swarm (сейчас)»
+ §5 ORAS как next-step; full-system-test §C под make deploy/swarm/smoke.

**Офлайн-валидация (live VPS недоступен):**
- `make -C release validate` падает с человеческой ошибкой при отсутствии env/*.env
  (указывает на deployment.example) и при swarm inactive — оба пути проверены.
- `make -C release render` (с example-env): `compose config | strip name |
  docker compose -f - config -q` → exit 0; 10 сервисов, 2 replicated-job, host-mode
  ports, start-first/stop-first deploy-блоки, env_file заинлайнен, top-level `name:`
  вырезан, pg-backup НЕ в стеке. j2-рендер dev/prod проверен (dev неизменен).
- `ansible-lint .` (= `make ansible-lint`) — Passed (production profile);
  `ansible-playbook site.yml --syntax-check` — зелёный. `actionlint deploy-tag.yml`
  — exit 0. `bash -n` на всех scripts — OK.
- root `make deploy` без inventory/prod.yml → падает с подсказкой «скопируй
  prod.example.yml» (AC1 anchor). `make ansible-unpack` env_dir default = development/
  env (dev-контракт цел).

**AC2-AC7 (live VPS deploy + tag-CD live run) BLOCKED:** требуют арендованного VPS
владельца + заполненный inventory/prod.yml + GitHub Secrets (SSH_PRIVATE_KEY,
SSH_KNOWN_HOSTS, ANSIBLE_VAULT_PASSWORD, PROD_HOST, PROD_DOMAIN, LETSENCRYPT_EMAIL);
бандл собран и оффлайн-валидирован.

**review/security MEDIUM исправлены (2026-06-11, checkpoint 5.5):** `no_log: true` добавлен на таску рендера `sensitive.env` в `ops/ansible/roles/env/tasks/main.yml` (секреты vault не попадают в ansible-лог). `ANSIBLE_HOST_KEY_CHECKING=True` выставлен в корневом `Makefile` target `deploy` (prod-путь — строгая проверка host key, глобальный `ansible.cfg` `host_key_checking=False` не тронут — dev-контракт цел). В `release/README.md` добавлена однострочная нота: перед первым `make deploy` нужно добавить host key VPS в `~/.ssh/known_hosts` (`ssh-keyscan -H <VPS_IP> >> ~/.ssh/known_hosts`). `ansible-lint` — Passed, `ansible-playbook --syntax-check site.yml` — зелёный.

**ship (2026-06-11, checkpoint 6):** PR открыт. AC6/AC7 остаются owner-blocked.

### Checklist владельца для перехода в online (AC6 + AC7)

Всё ниже — единственное, что нужно сделать руками. Всё остальное делает `make deploy`.

**Разовая подготовка:**
1. Арендовать VPS (Ubuntu 22.04/24.04, ≥4 GB RAM, ≥40 GB disk).
2. Скопировать шаблон и заполнить:
   ```
   cp ops/ansible/inventory/prod.example.yml ops/ansible/inventory/prod.yml
   # вписать: ansible_host (IP), ansible_user deploy, ansible_ssh_private_key_file,
   # prod_domain, letsencrypt_email, app_version (последний тег или 'main')
   ```
3. Направить DNS A-запись `prod_domain` → IP VPS (дождаться propagation).
4. Убедиться, что в ansible-vault заполнен `FIELD_ENCRYPTION_KEY` (TASK-032):
   `ansible-vault edit ops/ansible/sensitive.vault.yml` → добавить `FIELD_ENCRYPTION_KEY: <32-byte base64>`.
   Остальные ключи (SMTP Resend, NowPayments) уже в vault.
5. Добавить host key VPS в known_hosts:
   `ssh-keyscan -H <VPS_IP> >> ~/.ssh/known_hosts`
6. Первый деплой: `make deploy` (из корня `apps/trendPulse`).

**Для CD по тегу (one-time GitHub Secrets в `environment: production`):**
- `SSH_PRIVATE_KEY` — deploy-ключ (отдельный, НЕ личный; pubkey положить в authorized_keys на VPS).
- `SSH_KNOWN_HOSTS` — вывод `ssh-keyscan -H <VPS_IP>`.
- `ANSIBLE_VAULT_PASSWORD` — содержимое `.vault-pass`.
- `PROD_HOST` — IP VPS.
- `PROD_DOMAIN` — домен (напр. `foresignal.biz`).
- `LETSENCRYPT_EMAIL` — email для Let's Encrypt.

После этого каждый релиз = `git tag vX.Y.Z && git push origin vX.Y.Z`.
