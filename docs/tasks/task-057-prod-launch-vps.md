---
id: TASK-057
title: Прод-запуск на VPS — make deploy (provision→deploy→showcase-init→smoke) одной командой
status: planned             # planned → in-progress → review → done
owner: infra
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-launch-prod-vps"
tags: [launch, infra, ansible, ops]
---

# TASK-057 — Прод-запуск на VPS одной командой (Launch)

> Финальная миля E0→продакшн: владелец вписывает ТОЛЬКО креды (IP VPS + SSH-ключ + домен +
> недостающие vault-ключи) — всё остальное делает `make deploy`: provision (Docker и пр.) →
> deploy (env+stack) → миграции → showcase-init → TLS → smoke-тест «регистрация → сигнал».
> Принцип владельца: «всё настраивается само, без мануальных действий».

## Context

Уже есть: `ops/ansible/site.yml` = provision.yml (Docker engine+compose) + deploy.yml
(git checkout по `app_version` → env-роль (рендер deploy/sensitive.env из vault) →
backup-роль (cron pg_backup, TASK-034) → `docker_compose_v2 up` с env_files —
интерполяция починена 2026-06-10). Vault разблокирован (`make ansible-unpack` зелёный).
`make showcase-init` существует (exec api python -m api.trending) — но ЛОКАЛЬНЫЙ make,
на прод-хосте его надо вызывать через ansible. TLS: nginx.conf слушает только 80; 443 +
certbot НЕ настроены (комментарий в compose/nginx.yml). Inventory: `group_vars/prod.yml`
есть; hosts/inventory-файл с реальным IP — нет (creds-вход владельца). Бэкапы: cron от
backup-роли; restore-check (make backup-restore-check) — локальная команда. Smoke:
`docs/full-system-test.md` §A3 — curl-сценарий через nginx.

## Goal

`make deploy` (обёртка `ansible-playbook site.yml -l prod`) доводит ГОЛЫЙ Ubuntu-VPS до
работающего HTTPS-продакшна и зелёного smoke-теста без ручных шагов. Вход владельца —
один файл `ops/ansible/inventory/prod.yml` (IP/ssh-ключ/домен; шаблон-example в гите) +
заполненный vault. Smoke: автоматический сценарий register→login→watchlist→/ready после
деплоя (playbook-таска), фейл = фейл деплоя. showcase-init и cron бэкапов — идемпотентные
таски deploy.yml. TLS — certbot-контейнер/роль + nginx 443 (прод-профиль). DoD = AC.

## Discussion
- Q: TLS как? → Decision: certbot standalone в ansible-роли (issue/renew systemd-timer) +
  nginx-прод-конфиг с 443/ssl + редирект 80→443. Прод-nginx.conf — отдельный шаблон в
  ansible (роль рендерит), dev-конфиг не трогаем. Cloudflare/др. — нет (меньше движущихся
  частей).
- Q: Smoke где живёт? → Decision: bash/python-скрипт `ops/scripts/smoke.sh` (curl-сценарий
  из full-system-test §A3 + проверка /trending non-empty после прогрева) — вызывается
  последней таской deploy.yml И доступен локально (`make smoke HOST=…`).
- Q: showcase-init на проде? → Decision: таска deploy.yml: `docker compose exec api
  uv run python -m api.trending` (идемпотентен по построению TASK-039) — после up.
- Q: Что владелец делает руками? → Decision (исчерпывающий список, всё остальное — само):
  (1) арендовать VPS (Ubuntu 22.04/24.04, ≥4GB), вписать IP в inventory/prod.yml;
  (2) направить A-запись домена на IP; (3) дозаполнить vault: OPS_TELEGRAM_BOT_TOKEN
  (опц.), SMTP_* (для прод-писем), showcase-ключи (когда будет TASK-044);
  (4) `make deploy`. Всё.
- Q: Образы build-on-host или registry? → Decision: build на хосте (как сейчас deploy.yml
  через compose build при up) — ORAS/registry это ADR-006/future, не тащить сюда.

## Scope
- **Touch ONLY:**
  - `ops/ansible/inventory/prod.example.yml` — **новый** (шаблон: host/IP, user, ssh-key,
    domain, letsencrypt_email); реальный `inventory/prod.yml` — gitignored.
  - `ops/ansible/roles/tls/` — **новая роль**: certbot issue + renew-timer + рендер
    прод-nginx.conf (443/ssl/redirect) + публикация 443 (compose override или
    nginx-прод-фрагмент).
  - `ops/ansible/playbooks/deploy.yml` — таски: showcase-init (после up), smoke (последняя).
  - `ops/ansible/playbooks/provision.yml` — убедиться в идемпотентности на чистом Ubuntu
    (ufw: только 22/80/443 — если нет, добавить).
  - `ops/scripts/smoke.sh` — **новый** (register→login→watchlist→/ready→/trending).
  - `Makefile` — `deploy` (site.yml -l prod), `smoke` (HOST=…), help-текст.
  - `.gitignore` — inventory/prod.yml.
  - `docs/full-system-test.md` §C — актуализация под make deploy.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** dev-compose/dev-nginx (локальный путь не меняется), terraform
  (Hetzner-бакет уже есть; VPS-provision через terraform — отдельная задача, вход MVP —
  готовый IP), CI-workflows.
- **Blast radius:** deploy.yml (прод-путь) — каждая новая таска идемпотентна; критично
  не сломать существующий env/backup-флоу.

## Acceptance Criteria
- [ ] **AC1 — inventory-шаблон + make deploy (failing-check anchor).** Без inventory/prod.yml
  `make deploy` падает с ЧЕЛОВЕЧЕСКОЙ ошибкой («скопируй prod.example.yml»); с заполненным —
  ansible достигает хоста. ansible-lint/syntax-check зелёные (это RED-якорь до реализации).
- [ ] **AC2 — голый VPS → работающий стек.** На чистом Ubuntu один `make deploy`:
  Docker установлен, стек up (все healthy), миграции применены, showcase-init выполнен,
  бэкап-cron стоит.
- [ ] **AC3 — TLS.** https://домен отдаёт валидный LE-сертификат, 80→443 редирект,
  renew-timer активен. 22/80/443 — единственные открытые порты (ufw).
- [ ] **AC4 — smoke зелёный и гейтит.** smoke.sh: register→login→watchlist create→
  /ready 200→/trending 200; фейл любого шага = ненулевой exit deploy.
- [ ] **AC5 — идемпотентность.** Повторный `make deploy` на живом хосте — без даунтайма
  смысла (compose present), без дублей cron/затирания данных.
- [ ] **AC6 — G2 (боевой).** Реальный VPS владельца: make deploy с нуля → браузерный прогон
  «регистрация → сигнал ≤60с» (full-system-test §B-сценарий с реальными TG-кредами из vault);
  make backup-restore-check PASS против прод-бакета.

## Plan
1. **RED:** AC1 — make deploy + guard на inventory; ansible-lint в ci-режиме.
2. inventory-example + .gitignore + Makefile targets.
3. tls-роль (certbot + прод-nginx-шаблон + 443).
4. deploy.yml: showcase-init + smoke-таски; provision.yml: ufw.
5. smoke.sh (использует curl-сценарий §A3).
6. Verify: дешёвый прогон на одноразовом VPS/мультипасс-VM (AC2–AC5) → G2 на боевом (AC6).

## Invariants
- Один вход владельца: inventory/prod.yml + vault. Никаких ручных ssh-шагов в runbook.
- Все таски идемпотентны (повторный deploy безопасен) — ansible-идиоматика, не shell-скрипты
  где есть модуль.
- Секреты только через vault→env-роль; ничего секретного в inventory-example/гите.
- Dev-флоу (make up локально) не меняется.

## Edge cases
- Домен ещё не резолвится на IP → certbot fail: TLS-роль даёт понятную ошибку и НЕ валит
  http-деплой (флаг tls_enabled, default true, можно выключить для smoke-прогона по IP).
- Повторный certbot issue при существующем серте → renew-only (идемпотентность).
- VPS с малым диском/без swap → preflight-чек в provision (assert RAM/disk, warning).
- ufw включается ДО docker — docker сам управляет iptables: проверить совместимость
  (известная грабля docker+ufw — зафиксировать решение в роли).

## Test plan
- **static:** ansible-lint + syntax-check + make-таргеты (ci-fast не задет).
- **AC2–AC5:** одноразовый VPS (или локальная VM) — полный прогон с нуля, повторный прогон.
- **G2:** боевой VPS + браузерный сценарий + restore-check (AC6).
- **security (5.5):** ОБЯЗАТЕЛЬНО — поверхность хоста (ufw, ssh), TLS-конфиг (современные
  шифры), секреты не в логах ansible (no_log на чувствительных тасках).

## Checkpoints
current_step: 1
baseline_commit: ""
branch: "gsd/phase-launch-prod-vps"
lock: ""
- [ ] 1 locate (scope + patterns + blast radius)
- [ ] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED — host surface + TLS + secrets)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(planned 2026-06-10 — задача «последней мили» до продакшна; блокирует монетизацию больше,
чем любой код. Вход владельца сведён к: VPS+IP, A-запись, vault-ключи, make deploy.
Зависимости: vault разблокирован (2026-06-10), интерполяция env починена (PR #45),
showcase-init идемпотентен (TASK-039), backup-cron в deploy.yml (TASK-034).)
