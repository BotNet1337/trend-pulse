---
id: TASK-025
title: Templates service (port) + SMTP email transport + mailpit (инфра-фундамент email)
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "c954af0e7f89d4d64d3a37d77fdd6acf01d19736"
branch: "gsd/phase-025-templates-email-service"
tags: [epic-d, backend, email, infra, templates]
---

# TASK-025 — Templates service + SMTP transport + mailpit (Epic D)

> Перенести templates-сервис целиком из `/Users/macbookpro16/work/postbridge/apps/templates/` в `apps/trendPulse/templates/` (Node/Fastify + react-email; эндпоинты `/render`/`/preview`/`/health`); **отбросить** `src/templates/publications/` (PostBolt-specific), оставить/адаптировать `src/templates/auth/` под бренд TrendPulse (verify-email, reset-password). Добавить compose-сервис `templates` (internal-сеть, EXPOSE 3100 внутр., Node из `version.env`) + provisioning-дефолты, и **mailpit** compose-сервис как локальный catch-all SMTP (web-ui). Backend email-модуль: generic SMTP-транспорт (host/port/user/pass/from из settings/sensitive.env — **без вендор-лока**), рендер письма HTTP-вызовом к templates-сервису (`/render`), отправка по SMTP. AC: `make up` поднимает templates+mailpit; backend рендерит письмо через templates и доставляет в mailpit (видно в web-ui/API); SMTP-конфиг из env; нет секретов в коде. Фундамент для TASK-026/027. Security 5.5: SMTP creds из env, no hardcode.

## Context

TrendPulse не имеет email-инфраструктуры — нет ни рендеринга HTML-писем, ни SMTP-транспорта. Эти возможности нужны для завершения auth-флоу (verify-email/reset-password, [task-026](./task-026-auth-verify-reset.md)) и для уведомлений о продлении подписки ([task-027](./task-027-subscription-renewal-notifications.md)). Вместо написания с нуля — **порт готового, проверенного сервиса** из соседнего проекта PostBridge: `/Users/macbookpro16/work/postbridge/apps/templates/` — Node/Fastify + `@react-email/components`+`@react-email/render`, рендерит HTML-письма по template-id + props.

Структура источника (порт): `server/{main,config,server.factory,registry,logger,types,utils}.ts`, `server/handlers/{health,preview,render}.handler.ts`; `src/components/{brand-header,button,footer,layout}.tsx`; `src/templates/auth/{verify-email,reset-password,welcome,email-change-requested,email-changed}.tsx` (**оставить/адаптировать**) + `src/templates/publications/published.tsx` (**отбросить** — PostBolt-specific). Dockerfile — multi-stage `node:22-alpine` (deps→builder→production), `EXPOSE 3100`, `npm run build` = `tsc -p tsconfig.server.json`, `CMD ["node","dist/server/main.js"]`. Эндпоинты: `POST /render` (HTML по template-id+props), `/preview`, `/health`.

compose/infra: `development/compose/*.yml` (по сервису: `api.yml`/`worker.yml`/`beat.yml`/`nginx.yml`/`postgres.yml`/`redis.yml`/`frontend.yml`); `development/provisioning/`; `development/env/{deploy,sensitive}.env` (Ansible — source of truth, `make ansible-unpack`); `development/version.env` (пины образов/версий — `NODE_VERSION=22.15.1`). Сети: edge (nginx-only) + internal (см. [`../architecture/network-design.md`](./../architecture/network-design.md)). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — no magic literals, секреты только из env, generic (не вендор-лок).

## Goal

После задачи: (1) `apps/trendPulse/templates/` — перенесённый Node/Fastify+react-email сервис, рендерит брендированные TrendPulse-письма (verify-email, reset-password) через `POST /render`; publications-шаблоны удалены. (2) `make up` поднимает сервис `templates` (internal-сеть, порт 3100 только внутри) и `mailpit` (локальный catch-all SMTP + web-ui для просмотра). (3) Backend `notifications/email`-модуль: рендерит письмо HTTP-вызовом `templates` `/render`, отправляет через generic SMTP (host/port/user/pass/from/TLS из settings; в dev → mailpit). (4) Конфиги — из env (`deploy.env`/`sensitive.env`), provisioning-дефолты заданы, секретов в коде нет. DoD ниже.

## Discussion
<!-- durable record of clarifications. Обратимы. -->
- Q: Порт целиком или выборочно? → A: сервис проверенный → Decision: перенести `server/**`, `src/components/**`, `src/templates/auth/**`, `Dockerfile`, `package.json`/lock, tsconfig'и, eslint — **целиком**; `src/templates/publications/**` и связанный registry-эндпоинт-маппинг **отбросить**; `public/`/assets — перенести только нужные бренду.
- Q: Чей бренд в письмах? → A: TrendPulse, не PostBolt → Decision: адаптировать `src/components/{brand-header,footer,layout}.tsx` и тексты `auth/*.tsx` под TrendPulse (название, цвета, ссылки); ассеты (hero/logo) заменить. Логику рендера/handler'ы не переписывать.
- Q: Где взять Node-версию? → A: единый источник → Decision: `version.env` `NODE_VERSION` для compose/Dockerfile build-arg (Dockerfile источника `node:22-alpine` → параметризовать на `NODE_VERSION`). Никаких floating-тегов.
- Q: Сеть templates-сервиса? → A: internal-only (network-design: nginx-only-edge) → Decision: `templates` в internal-сети, порт 3100 НЕ публикуется наружу; backend (api/worker) ходит к нему по DNS-имени сервиса `http://templates:3100`. URL — из settings (`templates_service_url`), не inline.
- Q: SMTP — какой провайдер? → A: без вендор-лока → Decision: **generic SMTP** (stdlib/aiosmtplib): host/port/user/pass/from/STARTTLS — из settings. В dev → mailpit (host `mailpit`, порт 1025, без auth/TLS). Прод-провайдер задаётся теми же env — код не привязан к конкретному вендору.
- Q: mailpit — зачем? → A: видеть письма локально без реальной отправки → Decision: `mailpit` compose-сервис (catch-all SMTP `:1025`, web-ui `:8025`); backend в dev шлёт туда; e2e/проверка через mailpit HTTP API (`/api/v1/messages`).
- Q: Рендер — где? → A: разделение ответственности → Decision: backend НЕ рендерит HTML сам — делает `POST templates:3100/render` с `{template, props}`, получает HTML, кладёт в SMTP-письмо. Email-модуль = thin client + SMTP-sender.
- Q: Контракт `/render`? → A: из источника → Decision: сохранить контракт источника (`template-id` + `props`, zod-валидация на границе сервиса); backend-клиент типизирует запрос/ответ; ошибки рендера → понятная ошибка, не молча.

## Scope
> **infra + backend + node-сервис**: новый каталог `templates/` (порт), два compose-сервиса (`templates`, `mailpit`), backend `notifications/email`-модуль (SMTP + render-client), settings + env-дефолты. Auth-флоу/уведомления (task-026/027) — НЕ в этой задаче (только фундамент).

- **Touch ONLY (создать/изменить):**
  - **Node templates-сервис (порт):**
    - `templates/server/**`, `templates/src/components/**`, `templates/src/templates/auth/**` — **перенести** из источника (адаптировать бренд).
    - `templates/Dockerfile` (multi-stage `node:${NODE_VERSION}-alpine`, EXPOSE 3100), `templates/package.json`+`package-lock.json`, `templates/tsconfig*.json`, `templates/eslint.config.js`, `templates/public/**` (бренд-ассеты) — **перенести**.
    - **НЕ переносить:** `src/templates/publications/**`; почистить `server/registry.ts` от publications-маппинга.
  - **Compose/infra:**
    - `development/compose/templates.yml` — **новый** сервис `templates` (image из Dockerfile/`version.env`, internal-сеть, EXPOSE 3100 внутр., healthcheck `/health`).
    - `development/compose/mailpit.yml` — **новый** сервис `mailpit` (catch-all SMTP `:1025` + web-ui `:8025`, internal-сеть; web-ui опц. проброшен в dev).
    - `development/version.env` — пин образа `mailpit` (`MAILPIT_IMAGE`), при необходимости `TEMPLATES_IMAGE`.
    - `development/provisioning/**`, `development/env/deploy.env`, `development/env/sensitive.env` — дефолты: `TEMPLATES_SERVICE_URL=http://templates:3100`, `SMTP_HOST=mailpit`/`SMTP_PORT=1025`/`SMTP_FROM=...`/`SMTP_STARTTLS=false` (dev); креды (`SMTP_USER`/`SMTP_PASSWORD`) — в `sensitive.env` (dev пусто).
    - Корневой `compose`/`Makefile` include — добавить `templates.yml`/`mailpit.yml` в стек `make up` (если стек собирается из списка файлов).
  - **Backend email-модуль:**
    - `backend/src/notifications/__init__.py`, `backend/src/notifications/email.py` — **новый**: `render_email(template, props) -> str` (HTTP `POST templates/render`), `send_email(to, subject, html) -> None` (generic SMTP, aiosmtplib), оркестратор `send_templated_email(...)`.
    - `backend/src/config.py` — settings: `templates_service_url`, `smtp_host`/`smtp_port`/`smtp_user`/`smtp_password`/`smtp_from`/`smtp_starttls`.
    - `backend/tests/unit/test_email.py` — render-client (mock HTTP), SMTP-sender (mock), no-hardcode-config.
    - `backend/tests/integration/test_email_delivery.py` — AC: backend рендерит + шлёт → письмо в mailpit (mailpit API).
  - `docs/tasks/tasks-index.md` — на ship (НЕ в этой задаче-планировании).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/alerts/notifier.py` (Telegram-доставка — отдельный канал, не email), `frontend/**` (auth-страницы — task-026), bestseller-логику billing/scorer. Не реализовывать auth-router монтаж и уведомления (task-026/027). Не переносить publications-шаблоны. Никакого вендор-лока (SendGrid/SES SDK) — только generic SMTP.
- **Blast radius:** новый каталог `templates/` (Node) + два compose-сервиса в internal-сети + новый backend-модуль `notifications/`. Расширяет `make up` (две новые контейнера). Новые settings — обратносовместимые дефолты (dev → mailpit). Telegram-доставка alert'ов (notifier.py) не затрагивается. Фундамент, который потребляют 026/027.

## Acceptance Criteria
- [ ] **AC1 — templates-сервис рендерит брендированное письмо (failing-test anchor).** Given сервис `templates` поднят, When `POST /render` с `{template:"verify-email", props}`, Then `200` + HTML с брендом TrendPulse (не PostBolt); publications-шаблоны отсутствуют. Тест/проверка пишется ПЕРВЫМ (RED).
- [ ] **AC2 — `make up` поднимает templates + mailpit.** Given стек, When `make up`, Then контейнеры `templates` (healthcheck `/health` зелёный, порт 3100 только в internal-сети) и `mailpit` (SMTP `:1025`, web-ui `:8025`) запущены.
- [ ] **AC3 — backend рендерит через templates-сервис.** Given email-модуль, When `render_email("verify-email", props)`, Then делается HTTP `POST templates:3100/render`, возвращается HTML; ошибка сервиса → понятная ошибка (не молча).
- [ ] **AC4 — backend доставляет письмо в mailpit (SMTP).** Given dev SMTP-конфиг (host=mailpit:1025), When `send_email(...)`, Then письмо приходит в mailpit и видно в web-ui/через mailpit API (`/api/v1/messages`).
- [ ] **AC5 — SMTP-конфиг из env, generic.** Given settings, When отправка, Then host/port/user/pass/from/STARTTLS берутся из env; нет хардкода вендора/кредов в коде; смена провайдера = смена env, без правки кода.
- [ ] **AC6 — поведенческая (G2) через стек.** Given `make up`, When backend (скрипт/тест) рендерит verify-email через templates и шлёт в mailpit, Then письмо наблюдаемо в mailpit web-ui/API с брендированным HTML; артефакты (скриншот web-ui/JSON ответа API) при необходимости сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-025-templates-email-service`.
1. **Порт node-сервиса:** скопировать `server/**`, `src/components/**`, `src/templates/auth/**`, Dockerfile, package(+lock), tsconfig, eslint в `templates/`; удалить `publications/**` и почистить registry; адаптировать бренд (header/footer/layout/auth-тексты/ассеты). `npm ci && npm run build` зелёный.
2. **RED:** проверка `/render` верни TrendPulse-HTML (curl/тест). AC1-якорь.
3. compose: `templates.yml` + `mailpit.yml` (internal-сеть, версии из `version.env`); include в `make up`. AC2.
4. Backend `notifications/email.py` (render-client + SMTP-sender) + settings; env-дефолты (dev→mailpit). `test_email.py` (mock). 
5. `test_email_delivery.py` — рендер+отправка → mailpit API. **GREEN** локально (или через стек).
6. provisioning-дефолты + `sensitive.env` плейсхолдеры (creds пусто в dev).
7. **G2:** `make up` → templates+mailpit healthy; backend рендерит verify-email + шлёт → письмо в mailpit web-ui/API (AC4/AC6). Security 5.5: creds из env, no hardcode.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Generic SMTP, без вендор-лока** — транспорт = stdlib/aiosmtplib + env-конфиг; смена провайдера через env, не код. Никаких вендор-SDK.
- **Секреты только из env** — SMTP user/pass из `sensitive.env`/secret-manager; в dev пусто (mailpit без auth); ноль кредов в коде/образе.
- **templates-сервис internal-only** — порт 3100 не публикуется наружу (network-design nginx-only-edge); backend ходит по DNS-имени; URL из settings.
- **Разделение ответственности** — рендер HTML в node-сервисе (react-email), отправка в backend (SMTP); backend не дублирует рендеринг.
- **Версии из единого источника** — Node/образы из `version.env`; no floating tags (детерминированная сборка).
- **No magic literals** — URL сервиса/SMTP-параметры/template-id — из settings/констант; ошибки рендера/SMTP обрабатываются явно (не молча).
- **Только auth-шаблоны** — publications (PostBolt) удалены; в TrendPulse рендерятся только нужные письма.

## Edge cases
- templates-сервис недоступен (down) → backend `render_email` отдаёт явную ошибку; вызывающий (026/027) решает retry/деградацию, не молчит.
- SMTP недоступен/таймаут → `send_email` бросает обработанную ошибку; письмо не «теряется тихо».
- Невалидные `props` для шаблона → zod-валидация на границе node-сервиса → `4xx`; backend получает понятную ошибку.
- mailpt vs прод-SMTP: dev без TLS/auth (1025), прод с STARTTLS/auth — переключение только env (`SMTP_STARTTLS`/creds).
- Большой HTML/инлайн-картинки → проверить лимиты SMTP/размер письма; ассеты предпочтительно по URL, не тяжёлый base64.
- Дубли портов/имён сервисов в compose → не конфликтовать с существующими (`api`/`frontend`/`nginx`); 3100/1025/8025 свободны.
- Локализация писем (если потребуется позже) → шаблоны параметризуемы props; не хардкодить язык в этой задаче (минимально — текущий бренд-язык).

## Test plan
- **unit (backend):** `test_email.py` — `render_email` делает корректный HTTP-вызов (mock transport), `send_email` формирует MIME + шлёт через SMTP (mock), конфиг читается из settings (no-hardcode), ошибки render/SMTP пробрасываются.
- **integration (backend):** `test_email_delivery.py` — рендер verify-email через templates (или mock) + отправка в mailpit → письмо в mailpit API (`/api/v1/messages`), HTML содержит бренд.
- **node-сервис:** `npm run build` зелёный; smoke `/health`=200, `/render` верни TrendPulse-HTML, `/render` с publications-id → 404/нет шаблона.
- **runtime/behavioral (G2):** `make up` → templates+mailpit healthy; backend-скрипт рендерит+шлёт → письмо в mailpit web-ui/API; скриншот/JSON-артефакт.
- **security (5.5):** SMTP creds из env (grep на отсутствие хардкода/секретов в `templates/` и `backend/`); templates-порт не наружу; mailpit web-ui не публикуется в прод-профиле.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "c954af0e7f89d4d64d3a37d77fdd6acf01d19736"
branch: "gsd/phase-025-templates-email-service"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior через стек)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (opus — обязательна; SMTP header-injection, XSS в письмах, секреты)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-016/017 и контексту Epic D: порт проверенного templates-сервиса (Node/Fastify+react-email) из postbridge → `apps/trendPulse/templates/` (отбросить publications, адаптировать auth-шаблоны под бренд), compose-сервисы `templates`+`mailpit` (internal-сеть, версии из version.env), backend generic-SMTP email-модуль (`notifications/email.py`: render-client к templates `/render` + aiosmtplib SMTP-sender; конфиг из env, без вендор-лока). Это инфра-фундамент для task-026 (verify/reset письма) и task-027 (renewal-уведомления). deps: 001 (dev-environment/compose/Makefile/version.env). Security 5.5: SMTP creds из env, no hardcode. locate+plan выполнены этим планированием — executor стартует с «3 do».)

### do (loop-025, 2026-06-09)
Порт сервиса `templates/` из postbridge ЦЕЛИКОМ (server/**, src/components/**, src/templates/auth/** [5 шаблонов], Dockerfile [параметризован NODE_VERSION], package(+lock), все tsconfig*, eslint, public/, src/assets/) — publications отброшены; бренд PostBolt/PostBridge → TrendPulse (grep=0 по всем файлам вкл. SVG). Создан `templates.json` (TrendPulse auth-схема: verify-email/reset-password/welcome/email-change-requested/email-changed с props). Compose: `templates.yml` (internal, build NODE_VERSION, SCHEMA_PATH, healthcheck /health) + `mailpit.yml` (`axllent/mailpit:v1.21`, SMTP :1025 internal, web-ui :8025 dev-only); добавлены в include; `version.env` +MAILPIT_IMAGE/TEMPLATES_IMAGE. Backend `notifications/email.py`: `render_email` (httpx sync POST `/render/<template>`), `send_email` (stdlib smtplib+EmailMessage), `send_templated_email`; settings templates_service_url/smtp_*; `httpx` добавлен в [project].dependencies. Env в ansible-источник (deploy.env.j2/group_vars + sensitive.env.j2 SMTP_USER/PASSWORD с `| default('')`). Тесты: unit test_email 12 (mock httpx/SMTP, no-hardcode, ошибки), integration test_email_delivery (mailpit API, skip без стека).
**Проверки:** node build+lint зелёные; smoke /health={status:ok,templates:5}, /render/auth/verify-email→200 TrendPulse-HTML, /render/publications/published→404; `make ci-fast` 295 passed; test-cov 82.54%; import-check OK; grep чужого бренда=0.
**Steering пользователя (mid-do):** «скопируй всё из проекта, удали лишние templates, backend адаптируй под схему» → довёл порт до ПОЛНОЙ копии (докопированы tsconfig.app/node.json, public/, src/assets/ — email-флоу их не использует [inline data-URI иконки, нет static-сервинга], но порт теперь дословный); publications удалены; backend = thin render-client + SMTP под контракт сервиса. Ребренд TrendPulse сохранён (требование + no-foreign-brand).

### verify + review + security (loop-025, 2026-06-09)
**verify (G2 за стеком):** ci-fast 295, test-cov 82.54%; node build/lint + smoke (/health, /render/auth/verify-email→200 TrendPulse, publications→404); `make up` — templates+mailpit healthy (3100 internal-only, web-ui 8025 dev); backend рендерит verify-email через templates и **доставляет письмо в mailpit** (subject «Verify your TrendPulse email», HTML с TrendPulse+verifyUrl — дословно через mailpit API). 1 фикс: healthcheck `localhost`→`127.0.0.1` (Alpine резолвит localhost в IPv6, Fastify слушает IPv4).
**review (opus): 0 CRITICAL, 1 HIGH — исправлен.** HIGH: `render_email` не оборачивал транспортные ошибки httpx (down/timeout/bad-json) → нарушал инвариант «errors always explicit» → обёрнуто в `EmailRenderError` (+2 теста). MEDIUM/LOW (render.handler try/catch, loadComponent catch{}, main.ts console) — унаследованы из дословного порта, internal-only → follow-up.
**security (opus, обязательна): 0 CRITICAL, 2 HIGH-эквивалент — исправлены.**
- SMTP header-injection — PASS by-design (stdlib `EmailMessage` отклоняет CRLF в заголовках).
- HIGH (XSS): URL-props (verifyUrl/resetUrl/dashboardUrl/confirmUrl) не ограничены `http(s)` → `javascript:`/`data:` href в письмах → добавлен `safeHref()` guard в button.tsx (все кнопки) + raw `<a>` в welcome.tsx (не-http(s) → `#`).
- MEDIUM (worker hang): `smtplib.SMTP` без timeout → `timeout=smtp_timeout_seconds` (новый setting) + except расширен на `OSError`/socket.timeout.
- MEDIUM (plaintext creds в проде): `smtp_starttls` дефолт False (dev/mailpit) → `group_vars/prod.yml smtp_starttls:"true"` (прод-креды только по TLS).
- SSRF/path-traversal/секреты/USER node/non-root/preview-prod-off — PASS. DoS bodyLimit + interpolate-whitelist — follow-up (internal-only).
Перепроверка: node build/lint зелёные, ci-fast 297, test-cov ≥80%, бренд-grep=0.
**Follow-up для TASK-026/027:** валидировать `to`/`subject` на входе backend (defense-in-depth); не прокидывать `template`/URL из сырого user-ввода; (port-inherited) bodyLimit на render-сервисе.

### Подсказки исполнителю (initial)
- **Источник порта:** `/Users/macbookpro16/work/postbridge/apps/templates/` — копировать `server/`, `src/components/`, `src/templates/auth/`, `Dockerfile`, `package.json`, `package-lock.json`, `tsconfig*.json`, `eslint.config.js`, нужные `public/` ассеты. НЕ копировать `src/templates/publications/`, `node_modules/`.
- **registry чистка:** `server/registry.ts` маппит template-id → компонент; убрать `published`/publications-записи, оставить auth (verify-email/reset-password/welcome/email-change*).
- **Бренд-адаптация:** `src/components/{brand-header,footer,layout}.tsx` — название/лого/цвета/ссылки TrendPulse; тексты в `auth/*.tsx`; заменить `public/hero.png` на бренд-ассет.
- **Dockerfile:** параметризовать `node:22-alpine` → `node:${NODE_VERSION}-alpine` (build-arg из `version.env`); сохранить multi-stage (deps→builder→production, `npm ci --omit=dev` в проде, EXPOSE 3100, `CMD node dist/server/main.js`).
- **mailpit:** официальный образ `axllent/mailpit` (пин тег в `version.env`); env `MP_SMTP_BIND_ADDR=0.0.0.0:1025`; web-ui `:8025` — пробросить наружу ТОЛЬКО в dev-профиле, не в прод.
- **backend SMTP:** `aiosmtplib` (async, FastAPI/Celery-friendly) ИЛИ stdlib `smtplib` в threadpool. Параметры из settings: `smtp_host`/`smtp_port`/`smtp_user`/`smtp_password`/`smtp_from`/`smtp_starttls`. Dev: host=`mailpit`, port=1025, без auth/TLS.
- **render-client:** httpx `POST {templates_service_url}/render` JSON `{template, props}` → `resp.text`/`{html}`; таймаут из settings; 4xx/5xx → понятный exception.
- **make up include:** проверить, как стек собирает compose-файлы (список в Makefile/`COMPOSE_FILE`); добавить `templates.yml`+`mailpit.yml` тем же механизмом, что api/worker/beat.
- **G2-проверка mailpit:** `GET http://localhost:8025/api/v1/messages` → последнее письмо; ассертить subject/HTML-фрагмент бренда.
