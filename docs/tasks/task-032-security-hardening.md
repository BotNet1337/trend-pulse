---
id: TASK-032
title: Security hardening — per-route rate-limit (nginx) + CSRF/Origin на мутациях + at-rest шифрование (или accepted-risk)
status: planned             # planned → in-progress → review → done
owner: security
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-032-security-hardening"
tags: [epic-d, security, nginx, ops]
---

# TASK-032 — Security hardening: nginx rate-limit + CSRF + at-rest encryption (Epic D)

> Закрыть три security-долга из learnings. (1) **Per-route rate-limit на edge-nginx** (РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ — на edge, не slowapi-per-route): `limit_req_zone` + per-location `limit_req` на чувствительных (`/api/auth/jwt/login`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/billing/invoice`, `/api/api-keys`) в `development/provisioning/nginx/nginx.conf`; named-лимиты, `burst`+`nodelay`. (2) **CSRF на cookie-auth мутациях** (logout/delete-account/invoice/delivery-config PATCH): double-submit-токен ИЛИ **Origin/Referer-проверка на edge** (cookie `SameSite=lax` не покрывает top-level POST) — выбрать подход (Origin-check на nginx проще; задокументировать); prod cookie `Secure=true` ([task-009](./task-009-alert-delivery.md) долг). (3) **At-rest шифрование** `users.telegram_bot_token`/`webhook_url`: **nginx это НЕ может (только транспорт)** — app-level (Fernet/`cryptography` ключ из env ИЛИ Postgres pgcrypto). **ОПЦИОНАЛЬНО/твой-выбор:** если не делать — явно зафиксировать **accepted-risk** (TLS + ограниченный доступ к БД + секреты не в логах) в этом доке. Security 5.5 = суть задачи. **ОСТОРОЖНО:** rate-limit не должен ронять e2e (разумные лимиты/гард). DoD — Acceptance Criteria ниже.

## Context

TrendPulse — edge-nginx (`development/provisioning/nginx/nginx.conf`) единственный наружу ([network-design](../architecture/network-design.md)): `/api/`→`trendpulse_api` (strip `/api`), `/`→`frontend_spa`; security-заголовки (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`); HSTS закомментирован (только TLS-блок prod, локально :80). `client_max_body_size 10m`. **Нет `limit_req_zone`/`limit_req`** — rate-limit отсутствует на edge.

Backend rate-limit: глобальный slowapi **120/min** (`SlowAPIMiddleware` в `backend/src/api/main.py`, key=user_id|IP); **per-route нет**. Пользователь решил: per-route — на **edge-nginx**, не slowapi.

Security-долги (learnings):
- cookie `SameSite=lax` — не покрывает top-level POST CSRF; **нет CSRF-токена** на мутациях (logout/delete/invoice/delivery-config PATCH). OAuth уже имеет csrf double-submit cookie (`csrf_token_cookie_secure` в `api/main.py` google-router), но обычные мутации — нет.
- prod cookie `Secure` — долг [task-009](./task-009-alert-delivery.md) (локально `auth_cookie_secure=False` для http; prod должен `True`).
- `users.telegram_bot_token`/`webhook_url` — **plaintext at-rest** (хранятся как есть; в API маскируются на чтении — [task-017](./task-017-billing-account-ui.md) `mask_bot_token`, но в БД plaintext).

Мутации (cookie-auth, кандидаты на CSRF): `POST /auth/jwt/logout` (fastapi-users), `DELETE /account` (`api/routes/account.py`), `POST /billing/invoice` (`billing/router.py`), `PATCH /users/me/delivery-config` (`api/account/delivery_config.py`).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — секреты из env, no magic literals (лимиты — named в конфиге), error не течёт. nginx-конфиг mounted read-only.

## Goal

После задачи: чувствительные роуты ограничены rate-limit'ом на edge-nginx (`limit_req_zone`+`limit_req`, burst+nodelay; `curl`-burst→`429`/`503`); CSRF/Origin-проверка защищает cookie-auth мутации (Origin/Referer mismatch → отклонён; same-origin → проходит); prod cookie `Secure=true` в prod-конфиге; at-rest шифрование `telegram_bot_token`/`webhook_url` **реализовано** (Fernet/pgcrypto, ключ из env) **ИЛИ** зафиксирован осознанный **accepted-risk** в этом доке. Разумные лимиты — e2e не падают. Security 5.5 — суть задачи. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Решения по learnings + network-design; rate-limit/Origin обратимы, at-rest — решение. -->
- Q: Per-route rate-limit — где? → A: **edge-nginx** (решение пользователя) → Decision: `limit_req_zone` (по `$binary_remote_addr`, named zones) в `http{}`; per-`location` `limit_req zone=... burst=N nodelay` на чувствительных. НЕ slowapi-per-route. Лимиты named/в конфиге (no magic literals в смысле — явные именованные зоны).
- Q: Какие роуты ограничить? → A: auth + платёжные + ключи → Decision: `/api/auth/jwt/login` (brute-force), `/api/auth/register` (abuse), `/api/auth/forgot-password` (email-spam), `/api/billing/invoice` (abuse платёжки), `/api/api-keys` (если есть — иначе пропустить). Точные location-блоки внутри `location /api/` (nested) или отдельные `location = /api/auth/jwt/login`.
- Q: Лимиты не уронят e2e? → A: разумные + гард → Decision: лимиты заведомо выше e2e-нагрузки (напр. login 10r/m burst 5; forgot 5r/m). e2e не штормят эти роуты; при риске — `nodelay` + достаточный burst. Проверить в verify, что C1–C5 e2e зелёные.
- Q: CSRF-подход? → A: Origin-check на edge ИЛИ double-submit → Decision: **Origin/Referer-проверка** (проще, на edge ИЛИ app-middleware): для state-changing методов (POST/PATCH/DELETE) на cookie-auth требовать `Origin`/`Referer` совпадение с known-origin → иначе `403`. Документируем выбор. (double-submit-токен — альтернатива, сложнее; OAuth уже использует csrf-cookie — но для обычных мутаций Origin-check достаточен при `SameSite=lax`). Реализация: nginx `if`-проверка `$http_origin` ИЛИ FastAPI-middleware (app-level надёжнее — видит роут/метод). **Склоняемся к app-middleware** (Origin allow-list из settings) — переносимо, тестируемо integration.
- Q: prod cookie Secure? → A: True на prod → Decision: `auth_cookie_secure=True` в prod-конфиге (env-driven, как сейчас `csrf_token_cookie_secure` следует `auth_cookie_secure`); локально остаётся False (http). Это закрывает [task-009](./task-009-alert-delivery.md)-долг.
- Q: At-rest шифрование? → A: **опционально/выбор** → Decision: **по умолчанию реализуем** app-level Fernet (`cryptography`) на `telegram_bot_token`/`webhook_url` (ключ `FIELD_ENCRYPTION_KEY` из env/secret-manager; encrypt на write, decrypt на use — webhook send / telegram send). **Если объём/сложность велики** → зафиксировать **accepted-risk** (TLS in-transit + БД на `internal` без edge-доступа + секреты маскируются в API/логах + ограниченный operator-доступ) явно в Details как осознанное решение. **Не оставлять молча.**
- Q: nginx может at-rest? → A: НЕТ → Decision: nginx — только транспорт (TLS); at-rest — app/БД-уровень. Явно зафиксировано.

## Scope
> **nginx** (per-route rate-limit) + **backend** (CSRF/Origin-middleware на мутациях, prod cookie Secure, at-rest шифрование колонок ИЛИ accepted-risk) + prod-конфиг. Доменная логика роутов не меняется — добавляется защитный слой.

- **Touch ONLY (создать/изменить):**
  - **nginx:**
    - `development/provisioning/nginx/nginx.conf` — `limit_req_zone` (named zones в `http{}`); per-location `limit_req`+`burst`+`nodelay` на `/api/auth/jwt/login`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/billing/invoice`, (`/api/api-keys` если есть); `limit_req_status 429`. Дублировать в закомментированный prod-443-блок.
  - **Backend:**
    - `backend/src/api/security/csrf.py` (или `api/middleware/`) — **новый**: Origin/Referer-проверка для state-changing методов на cookie-auth (allow-list origins из `config`), `403` на mismatch; зарегистрировать middleware в `api/main.py`.
    - `backend/src/config.py` — `allowed_origins` (env), `auth_cookie_secure` prod=True (уже есть флаг — выставить prod-default через env), `field_encryption_key` (если at-rest реализуем).
    - `backend/src/api/main.py` — зарегистрировать CSRF/Origin-middleware (после SlowAPI, до роутов).
    - **At-rest (если реализуем):** `backend/src/storage/encryption.py` — **новый**: Fernet encrypt/decrypt (ключ из env); `storage/models/users.py` или type-decorator на колонках `telegram_bot_token`/`webhook_url` (SQLAlchemy `TypeDecorator`); decrypt в местах использования (webhook send / telegram send — [task-009](./task-009-alert-delivery.md)). Миграция данных (encrypt existing) если нужно.
    - `backend/tests/integration/test_csrf_origin.py` — **новый**: мутация без/с неверным `Origin` → `403`; same-origin → проходит; safe-методы (GET) не блокируются.
    - `backend/tests/integration/test_at_rest_encryption.py` — **новый** (если реализуем): токен/webhook хранятся зашифрованно (в БД не plaintext), читаются корректно; ИЛИ — нет файла, accepted-risk в Details.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, доменная логика роутов/биллинга/коллектора (только защитный слой), slowapi-глобальный лимит (per-route — на edge, не трогаем глобальный 120/min). SSRF-валидацию webhook ([task-009](./task-009-alert-delivery.md)) не переписываем.
- **Blast radius:** **затрагивает все запросы через edge** (rate-limit) и все cookie-auth мутации (CSRF/Origin — может отклонять при неверном origin). prod cookie Secure меняет cookie-атрибут (prod). At-rest меняет storage-формат колонок (миграция existing-данных + decrypt в send-путях [task-009](./task-009-alert-delivery.md)). **Риск ложно-positive:** rate-limit ронял бы e2e (лимиты разумные); Origin-check мог бы блокировать легитимные SSR/прокси-запросы (allow-list внутренних origins — внимание к [task-029](./task-029-frontend-ssr-enablement.md) SSR).

## Acceptance Criteria
- [ ] **AC1 — per-route rate-limit на edge (failing-test anchor).** Given nginx-конфиг с `limit_req`, When `curl`-burst на `/api/auth/jwt/login` (выше лимита+burst), Then часть запросов → `429` (`limit_req_status`); легитимный одиночный запрос проходит. Проверка пишется ПЕРВОЙ (RED — лимита нет). Лимиты named/в конфиге.
- [ ] **AC2 — rate-limit на всех чувствительных роутах.** Given конфиг, When инспекция, Then `limit_req` применён к `/api/auth/jwt/login`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/billing/invoice` (+`/api/api-keys` если есть); `burst`+`nodelay`; зоны в `http{}`; продублировано в prod-443-блок.
- [ ] **AC3 — CSRF/Origin на мутациях.** Given cookie-auth мутация (POST/PATCH/DELETE: logout/delete-account/invoice/delivery-config), When `Origin`/`Referer` не из allow-list (или отсутствует на cross-origin) → `403`; same-origin → проходит; safe-методы (GET) не блокируются. Подход (Origin-check) задокументирован.
- [ ] **AC4 — prod cookie Secure.** Given prod-конфиг, When auth-cookie ставится, Then `Secure=true` на prod (env-driven `auth_cookie_secure`); локально (http) остаётся False; закрывает [task-009](./task-009-alert-delivery.md)-долг.
- [ ] **AC5 — at-rest: реализовано ИЛИ accepted-risk.** Given `telegram_bot_token`/`webhook_url`, Then **либо** хранятся зашифрованно (Fernet/pgcrypto, ключ из env; integration: в БД не plaintext, decrypt в send-путях корректен) **либо** в Details зафиксирован явный **accepted-risk** (TLS + БД на internal + маскирование в API/логах + operator-доступ ограничен) как осознанное решение. **Не молча.**
- [ ] **AC6 — e2e не сломаны (разумные лимиты).** Given новые rate-limit + Origin-check, When прогон C1–C5 e2e через nginx, Then все зелёные (лимиты выше e2e-нагрузки; Origin-allow-list включает фронт/SSR-origin); ни один флоу не ложно-отклонён.
- [ ] **AC7 — security (5.5 = суть) + поведенческая (G2).** Given `make up`, When: `curl`-burst на чувствительный роут → `429` (AC1); мутация с чужим Origin → `403` (AC3); инспекция cookie-атрибутов (prod Secure, AC4); проверка at-rest/accepted-risk (AC5); Then наблюдаемо за nginx; integration (`test_csrf_origin`/`test_at_rest_encryption`) зелёные; артефакты on-failure. Ключи (FIELD_ENCRYPTION_KEY) из env, не в коде/логах.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-032-security-hardening`.
1. **RED:** проверка rate-limit (`curl`-burst → ожидать `429`) + `test_csrf_origin.py` (чужой Origin → `403`). Падает (нет лимита/CSRF). AC1/AC3-якорь.
2. nginx: `limit_req_zone` + per-location `limit_req`+burst+nodelay на чувствительных; `limit_req_status 429`; продублировать в prod-443. AC1/AC2.
3. Backend CSRF/Origin-middleware (`api/security/csrf.py`) — Origin allow-list из `config`, `403` на state-changing mismatch; зарегистрировать в `api/main.py`. AC3.
4. prod cookie `Secure=true` (env-driven `auth_cookie_secure`). AC4.
5. **At-rest:** реализовать Fernet-шифрование колонок (`storage/encryption.py` + TypeDecorator, ключ env, decrypt в send-путях) + миграция existing **ИЛИ** зафиксировать accepted-risk в Details (решение G1). AC5.
6. **GREEN + G2 + 5.5:** `make up`; integration зелёные; `curl`-burst→429; мутация с чужим Origin→403; C1–C5 e2e зелёные (AC6 — лимиты/allow-list разумные); проверить cookie Secure (prod-конфиг) + at-rest/accepted-risk.
7. Обновить `tasks-index.md` на ship.

## Invariants
- **Rate-limit на edge, не slowapi-per-route** (решение пользователя) — глобальный slowapi 120/min остаётся; per-route — только nginx `limit_req`.
- **Лимиты разумные — e2e не падают** — пороги заведомо выше e2e-нагрузки; `burst`+`nodelay` сглаживает; C1–C5 зелёные (AC6 — не регрессировать).
- **CSRF/Origin только на state-changing** — GET/HEAD/OPTIONS не блокируются; allow-list включает легитимные origins (фронт + SSR [task-029](./task-029-frontend-ssr-enablement.md)).
- **nginx — только транспорт** — at-rest шифрование НЕ на nginx (только TLS in-transit); at-rest — app/БД-уровень.
- **Секреты из env** — `FIELD_ENCRYPTION_KEY`/allow-list origins из env/secret-manager; никогда в коде/логах; ротация ключа предусмотрена (если at-rest).
- **At-rest решение явно** — реализовано ИЛИ accepted-risk задокументирован; никогда «молча plaintext без решения» (CONVENTIONS security).
- **prod cookie Secure** — `Secure=true` на HTTPS-prod; локально http→False (иначе cookie не ходит).
- **No magic literals** — rate-limit зоны/пороги named в конфиге; origins/ключ — конфиг/env.

## Edge cases
- e2e штормит login/forgot и ловит `429` → лимиты слишком низкие; поднять порог/burst или гард в тесте; AC6 ловит.
- SSR-сервер ([task-029](./task-029-frontend-ssr-enablement.md)) делает server-side fetch без `Origin`-заголовка → Origin-check блокирует легитимный SSR; allow-list/исключение для internal-origin (или CSRF только на browser-инициированных мутациях).
- `Origin` отсутствует на legitimate same-origin GET → safe-методы не проверяем; только state-changing.
- prod cookie `Secure=true` локально (http) → cookie не отправляется, auth ломается; Secure только на prod (env-driven), локально False.
- At-rest: existing plaintext-данные в БД при включении шифрования → миграция (encrypt existing) или dual-read (try decrypt → fallback plaintext) на переход.
- Потеря `FIELD_ENCRYPTION_KEY` → невозможно расшифровать токены; ключ в secret-manager + ротация-план; зафиксировать риск.
- pgcrypto vs app-Fernet → app-Fernet проще (не требует расширения БД), переносимо; pgcrypto — если БД-уровень предпочтительнее (решить, не оба).
- `limit_req` в nested `location` внутри `location /api/` → nginx-семантика location-приоритета; использовать `location = /api/auth/jwt/login` (exact) для точечности.
- Маскирование в API ([task-017](./task-017-billing-account-ui.md) `mask_bot_token`) + at-rest шифрование — не конфликтуют (маска на чтении API, шифр в БД); decrypt только в send-путях.

## Test plan
- **integration (backend):** `test_csrf_origin.py` — мутация без/с чужим `Origin`→`403`, same-origin→проходит, GET не блокируется (AC3); `test_at_rest_encryption.py` (если реализуем) — колонки в БД не plaintext, decrypt в send корректен (AC5).
- **runtime/behavioral (G2):** `make up` → `curl`-burst на `/api/auth/jwt/login` (и прочие) → `429` (AC1/AC2); инспекция nginx-конфига (зоны/burst/nodelay/prod-443-дубль); cookie-атрибуты (prod Secure, AC4); C1–C5 e2e зелёные за nginx (AC6 — не ложно-отклонены).
- **security (5.5 = суть):** rate-limit на чувствительных роутах активен; CSRF/Origin на всех cookie-auth мутациях; prod cookie Secure; at-rest реализовано ИЛИ accepted-risk зафиксирован; `FIELD_ENCRYPTION_KEY`/origins из env (grep — не в коде/логах); SSRF webhook ([task-009](./task-009-alert-delivery.md)) не регрессировал.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-032-security-hardening"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через nginx/стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону [task-013](./task-013-frontend-foundation.md)/[task-017](./task-017-billing-account-ui.md) и реальному коду: edge-nginx (`development/provisioning/nginx/nginx.conf`) сейчас БЕЗ `limit_req_zone`/`limit_req` — только security-заголовки + `client_max_body_size 10m`; backend slowapi глобальный 120/min (`SlowAPIMiddleware`), per-route нет. Пользователь решил: per-route rate-limit — на EDGE-nginx (не slowapi). Security-долги (learnings): cookie SameSite=lax без CSRF-токена на мутациях (logout/delete/invoice/delivery-config PATCH — OAuth уже имеет csrf double-submit cookie, обычные мутации нет); prod cookie Secure (task-009 долг, флаг `auth_cookie_secure` есть); `users.telegram_bot_token`/`webhook_url` plaintext at-rest (в API маскируются task-017 `mask_bot_token`, в БД plaintext). nginx at-rest НЕ может (только транспорт) — app-level Fernet/pgcrypto. At-rest помечено ОПЦИОНАЛЬНЫМ: по умолчанию реализуем app-Fernet (ключ env), при сложности — явный accepted-risk в Details (НЕ молча). CSRF-подход: склоняемся к app-middleware Origin/Referer allow-list (переносимо, integration-тестируемо; внимание к SSR-origin task-029). prod cookie Secure env-driven. ОСТОРОЖНО: rate-limit разумный (e2e не ронять — AC6); Origin-check не блокирует SSR-server (task-029). Security 5.5 = суть задачи. deps: 011 (compliance/logging-hygiene), 012 (предполагаемая infra/secrets). locate+plan выполнены этим планированием — executor стартует с «3 do».)
