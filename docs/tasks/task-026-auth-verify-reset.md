---
id: TASK-026
title: Auth completeness — email verification + reset-password (backend routers + email + frontend enable)
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-026-auth-verify-reset"
tags: [epic-d, backend, frontend, auth, security]
---

# TASK-026 — Auth completeness: verify + reset-password (Epic D)

> Смонтировать `fastapi_users.get_verify_router` + `get_reset_password_router` в `api/main.py` (секреты `verification_token_secret`/`reset_password_token_secret` уже инициализированы в `users.py`); on-after-хуки UserManager шлют письмо через email-модуль+templates ([task-025](./task-025-templates-email-service.md)). Email-verification: запрос → письмо (verify-token) → `POST /auth/verify`; reset: `POST /auth/forgot-password` → письмо → `POST /auth/reset-password`. Frontend ([task-014](./task-014-auth-flow-ui.md)): **включить** ранее скрытые `pages/auth/{forgot-password,reset-password,confirm-email}` — подключить к реальным эндпоинтам, убрать «не активны». Опц.: gate `associate_by_email` на `is_verified` (learnings task-003). Security 5.5 ОБЯЗАТЕЛЬНА: токены verify/reset, **no-enumeration** на forgot-password (единообразный ответ). AC: register→verify-письмо в mailpit→verify→`is_verified=true`; forgot→reset-письмо→смена пароля→login новым; страницы фронта работают; integration+e2e.

## Context

Auth построен на fastapi-users ([ADR-003](../architecture/adr-003-monorepo-and-auth.md), [task-003](./task-003-auth.md)): `backend/src/api/auth/` (`users.py` UserManager, `backend.py`, `oauth.py`, `schemas.py`, `me.py`). `api/main.py` монтирует `get_auth_router` (login/logout JWT) + `get_register_router` + `get_oauth_router` — но **НЕ** `get_verify_router` и **НЕ** `get_reset_password_router`. При этом `UserManager.__init__` уже задаёт `reset_password_token_secret` и `verification_token_secret` — т.е. крипто-фундамент верификации/сброса готов, не хватает (а) монтирования роутеров, (б) доставки писем в `on_after_*`-хуках.

Frontend (C2, [task-014](./task-014-auth-flow-ui.md)) уже содержит страницы `pages/auth/{forgot-password,reset-password,confirm-email,confirm-email-change}`, но они **СКРЫТЫ/отключены** — потому что backend не монтировал соответствующие роутеры. Email-инфраструктура (templates-сервис `/render` + SMTP + mailpit) добавлена в [task-025](./task-025-templates-email-service.md) — это hard-dep: без неё письма слать некуда.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, Pydantic на границе, no magic literals, секреты из env, **no PII/secrets в логах**. Security-чувствительно (токены, перечисление пользователей) → стадия 5.5 обязательна.

## Goal

После задачи: (1) backend монтирует verify-router (`POST /auth/request-verify-token`, `POST /auth/verify`) и reset-password-router (`POST /auth/forgot-password`, `POST /auth/reset-password`); `on_after_register`/`on_after_request_verify`/`on_after_forgot_password` шлют брендированное письмо через email-модуль+templates (task-025). (2) Флоу verify: регистрация → письмо с verify-токеном → `POST /auth/verify` → `is_verified=true`. (3) Флоу reset: `POST /auth/forgot-password` (единообразный ответ, no-enumeration) → письмо с reset-токеном → `POST /auth/reset-password` (новый пароль) → login новым паролем. (4) Frontend-страницы `forgot-password`/`reset-password`/`confirm-email` **включены**, подключены к реальным эндпоинтам, «не активны»-заглушки убраны. (5) Опц.: `associate_by_email` (OAuth) гейтится на `is_verified`. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по ADR-003/task-003/014/025; обратимы. -->
- Q: Что монтировать? → A: fastapi-users генераторы → Decision: `fastapi_users.get_verify_router(UserRead)` и `fastapi_users.get_reset_password_router()` в `api/main.py` под тем же prefix `/auth`, что и существующие auth-роуты. Секреты уже в `users.py` — не дублировать.
- Q: Где слать письма? → A: UserManager-хуки → Decision: переопределить `on_after_register` (опц. авто-request-verify), `on_after_request_verify(user, token, request)` (шлёт verify-письмо с deeplink, содержащим token), `on_after_forgot_password(user, token, request)` (шлёт reset-письмо). Тело письма — `render_email("verify-email"/"reset-password", {url, ...})` через task-025; отправка `send_email` (SMTP→mailpit в dev).
- Q: Deeplink — куда? → A: на фронт-страницы C2 → Decision: ссылка в письме ведёт на frontend `…/auth/confirm-email?token=…` (verify) и `…/auth/reset-password?token=…` (reset); base-URL фронта из settings (`frontend_base_url`), не inline.
- Q: no-enumeration на forgot-password? → A: безопасность → Decision: `POST /auth/forgot-password` ВСЕГДА отвечает одинаково (`202`/`200` без признака существования email) независимо от того, есть ли пользователь — fastapi-users так и делает (`on_after_forgot_password` вызывается только для существующего, но HTTP-ответ единообразен). UI показывает «если email существует — письмо отправлено».
- Q: Frontend «включить» — что значит? → A: страницы есть, но disabled → Decision: убрать заглушки/«не активны», подключить формы к реальным эндпоинтам (`forgot-password`→POST, `reset-password`→POST с token из query, `confirm-email`→POST verify с token из query); регенерить `gen.types.ts` если роуты меняют OpenAPI; роуты — публичные (без guard), т.к. пользователь не залогинен.
- Q: `associate_by_email` gate? → A: learnings task-003 (OAuth-связывание по email — риск захвата) → Decision (опц., если в скоупе): связывать OAuth-аккаунт с существующим только если тот `is_verified`; иначе не сливать. Помечено опциональным — не блокирует AC ядра.
- Q: Авто-verify при register? → A: UX-выбор → Decision: после register сразу триггерить `request_verify` (письмо приходит без отдельного действия пользователя); либо UI показывает «подтвердите email» с кнопкой повторной отправки. Решение исполнителя; AC требует, чтобы письмо в итоге пришло.

## Scope
> **backend** (монтаж verify/reset-роутеров + email в UserManager-хуках) + **frontend** (включить 3 ранее скрытые auth-страницы, подключить к эндпоинтам). Email-инфра (task-025) и auth-ядро (task-003) — НЕ переписываем (потребляем). Security 5.5 обязательна.

- **Touch ONLY (создать/изменить):**
  - **Backend:**
    - `backend/src/api/main.py` — `include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])` + `include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])`.
    - `backend/src/api/auth/users.py` — переопределить `on_after_register` (опц. триггер verify), `on_after_request_verify`, `on_after_forgot_password`: рендер+отправка письма через `notifications/email` (task-025); deeplink на фронт (base-URL из settings). **No PII/token в логах.**
    - `backend/src/api/auth/oauth.py` (опц.) — gate `associate_by_email` на `is_verified`.
    - `backend/src/config.py` — `frontend_base_url` (для deeplink), если ещё нет.
    - `backend/tests/integration/test_auth_verify.py` — register→request-verify→письмо→`POST /auth/verify`→`is_verified=true`.
    - `backend/tests/integration/test_auth_reset.py` — forgot-password (no-enumeration единообразный ответ)→письмо→`POST /auth/reset-password`→login новым; невалидный/протухший token→ошибка.
  - **Frontend:**
    - `frontend/src/pages/auth/forgot-password/**`, `reset-password/**`, `confirm-email/**` — **включить** (убрать disabled/«не активны»), подключить к эндпоинтам (token из query для reset/confirm).
    - `frontend/src/features/auth/**` — query/mutation: `requestPasswordReset`, `resetPassword`, `verifyEmail` (на типах gen.types).
    - `frontend/src/shared/api/gen.types.ts` — **регенерировать** (новые auth-роуты в OpenAPI).
    - `frontend/src/app/router/**` — маршруты публичные (без guard).
    - `frontend/tests/e2e/auth-verify-reset.spec.ts` — **новый** e2e: verify-флоу + reset-флоу через mailpit.
    - `frontend/tests/unit/auth/**` — формы forgot/reset/confirm, token-from-query, единообразный ответ forgot.
  - `docs/tasks/tasks-index.md` — на ship (НЕ в этой задаче-планировании).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/notifications/**` (email-модуль — task-025, потребляем), `templates/**` (node-сервис — task-025, шаблоны verify/reset оттуда), `backend/src/api/auth/backend.py` (JWT-механика — task-003), billing/scorer. Не реализовывать email-change-флоу (`confirm-email-change` оставить как есть, вне скоупа). Не катать свою крипто-токенизацию (fastapi-users делает).
- **Blast radius:** новые публичные auth-эндпоинты (verify/reset) + UserManager-хуки шлют письма (зависят от task-025 — если email-инфра down, register всё равно проходит, письмо best-effort). Frontend: 3 ранее скрытые страницы становятся активными. Регенерация типов добавляет auth-операции. Security-поверхность растёт (токены, эндпоинты сброса) → 5.5 обязательна.

## Acceptance Criteria
- [ ] **AC1 — email-verification end-to-end (failing-test anchor).** Given новый пользователь регистрируется, When срабатывает request-verify, Then verify-письмо приходит в mailpit с токеном; переход по `POST /auth/verify` с этим токеном → `is_verified=true`. Тест пишется ПЕРВЫМ (RED).
- [ ] **AC2 — reset-password end-to-end.** Given существующий пользователь, When `POST /auth/forgot-password`, Then reset-письмо в mailpit; `POST /auth/reset-password` с токеном+новым паролем → пароль сменён; login новым паролем → `200`, старым → `401`.
- [ ] **AC3 — no-enumeration на forgot-password (security).** Given несуществующий email vs существующий, When `POST /auth/forgot-password`, Then HTTP-ответ единообразен (нет различия по статусу/телу/таймингу-признаку), не раскрывает существование аккаунта.
- [ ] **AC4 — роутеры смонтированы.** Given `api/main.py`, When OpenAPI/routes, Then `POST /auth/request-verify-token`, `POST /auth/verify`, `POST /auth/forgot-password`, `POST /auth/reset-password` присутствуют; письма шлются через email-модуль (task-025), не заглушка.
- [ ] **AC5 — невалидный/протухший токен отклоняется.** Given истёкший/подделанный verify- или reset-токен, When `POST /auth/verify`/`/auth/reset-password`, Then `400`/`4xx` (токен невалиден), `is_verified`/пароль не меняются; ошибка не раскрывает детали.
- [ ] **AC6 — frontend-страницы работают.** Given включённые `forgot-password`/`reset-password`/`confirm-email`, When пользователь проходит флоу из UI (token из query), Then запросы к реальным эндпоинтам успешны; «не активны»-заглушки отсутствуют.
- [ ] **AC7 — security + поведенческая (G2) через стек.** Given `make up` (api+templates+mailpit+frontend за nginx), When Playwright `auth-verify-reset.spec.ts`, Then verify- и reset-флоу наблюдаемы (письмо читается из mailpit API, токен извлекается, флоу завершается); токены/PII НЕ в логах; артефакты on-failure сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-026-auth-verify-reset`.
1. **RED (backend):** `test_auth_verify.py` — register→verify→`is_verified=true` (через mailpit). Падает (роутер не смонтирован). AC1-якорь.
2. Монтаж `get_verify_router`+`get_reset_password_router` в `api/main.py`; UserManager-хуки (`on_after_request_verify`/`on_after_forgot_password`/опц. `on_after_register`) шлют письма через `notifications/email` (task-025), deeplink на фронт (settings). `make ci-fast` зелёный.
3. `test_auth_reset.py` — forgot (no-enumeration)→reset→login новым; невалидный token→4xx. **GREEN**.
4. Регенерировать `gen.types.ts` (новые auth-роуты).
5. **RED (frontend):** `auth-verify-reset.spec.ts` — verify-флоу из UI. Падает (страницы disabled). 
6. Включить `forgot-password`/`reset-password`/`confirm-email` (убрать заглушки, подключить эндпоинты, token из query) + features-мутации; unit-тесты. **GREEN** локально.
7. **G2 + security:** `make up`; Playwright верифицирует verify+reset через mailpit за nginx (AC7); integration зелёный; **5.5**: no-enumeration (AC3), токены/PII не в логах, токены protected (fastapi-users), HTTPS-deeplink.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Крипто-токены — fastapi-users** — verify/reset-токены генерит fastapi-users из секретов в `users.py`; не катаем свою токенизацию; секреты из env.
- **No-enumeration на forgot-password** — единообразный ответ независимо от существования email (статус/тело/тайминг); UI: «если email существует — письмо отправлено».
- **No PII/secrets в логах** — токены/email/пароли не логируются (hygiene-helper task-011); deeplink с токеном не пишется в лог целиком.
- **Email — best-effort, register не блокируется** — если email-инфра (task-025) недоступна, регистрация проходит, отправка письма обрабатывается как ошибка отправки (повторная отправка возможна), но не валит auth.
- **Deeplink через settings** — base-URL фронта из settings, HTTPS в проде; не inline.
- **Frontend публичные роуты** — verify/reset/forgot страницы доступны без логина (пользователь не аутентифицирован); cookie-auth не требуется для этих форм.
- **Токены одноразовые/протухающие** — истёкший/использованный токен → `4xx`; не позволять повторную смену пароля одним токеном.

## Edge cases
- forgot-password для несуществующего email → единообразный ответ (no-enumeration), письмо не шлётся, утечки нет (AC3).
- Протухший/использованный verify- или reset-токен → `4xx`, состояние не меняется (AC5).
- Двойной клик по reset-ссылке / повторный `POST /auth/reset-password` тем же токеном → второй раз `4xx` (токен израсходован).
- Email-сервис (task-025) недоступен в момент request-verify → register/forgot не падают; письмо не пришло → пользователь может запросить повторно (`request-verify-token`).
- Verify уже verified-пользователя → идемпотентно/понятный ответ, не ошибка `500`.
- OAuth-пользователь без пароля делает forgot-password → корректная обработка (fastapi-users) — не падать.
- Токен в URL → не логировать целиком; фронт читает из query и сразу шлёт, не хранит в localStorage.
- `associate_by_email` (опц.): попытка связать OAuth с unverified-аккаунтом → не сливать (защита от захвата).

## Test plan
- **integration (backend):** `test_auth_verify.py` — register→request-verify→письмо в mailpit→`POST /auth/verify`→`is_verified=true` (AC1-якорь); `test_auth_reset.py` — forgot (no-enumeration единообразный ответ, AC3)→reset-письмо→`POST /auth/reset-password`→login новым/старым (AC2); невалидный/протухший токен→`4xx` (AC5); роутеры в OpenAPI (AC4).
- **unit (frontend):** формы forgot/reset/confirm (token из query, единообразное сообщение forgot, валидация пароля), мутации на gen.types.
- **e2e (Playwright):** `auth-verify-reset.spec.ts` — verify-флоу (register→читать письмо из mailpit API→перейти confirm-email с токеном→is_verified), reset-флоу (forgot→письмо→reset→login новым). Артефакты on-failure.
- **runtime/behavioral (G2):** `make up` (api+templates+mailpit+frontend за nginx) → Playwright против реального стека; письма из mailpit API.
- **security (5.5):** no-enumeration forgot-password; токены/PII не в логах; токены одноразовые/протухающие; deeplink HTTPS в проде; (опц.) associate_by_email gate на is_verified.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-026-auth-verify-reset"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-016/017 и контексту Epic D: завершить auth — смонтировать fastapi-users verify/reset-роутеры в api/main.py (секреты уже в users.py), on-after-хуки UserManager шлют брендированные письма через email-модуль+templates (task-025), deeplink на фронт-страницы; включить ранее скрытые frontend `pages/auth/{forgot-password,reset-password,confirm-email}` (task-014) и подключить к реальным эндпоинтам. Опц. gate associate_by_email на is_verified (learnings task-003). deps: 003 (auth-ядро/fastapi-users), 014 (auth-UI/скрытые страницы), 025 (email-инфра — hard-dep). Security 5.5 ОБЯЗАТЕЛЬНА: no-enumeration на forgot-password, токены/PII не в логах, токены одноразовые. locate+plan выполнены этим планированием — executor стартует с «3 do».)

### Подсказки исполнителю (initial)
- **Монтаж:** в `api/main.py` рядом с существующими auth-include — `app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])` и `app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])`. Сверить сигнатуры с версией fastapi-users в проекте.
- **UserManager-хуки (`users.py`):** уже есть `on_after_register`; добавить `async def on_after_request_verify(self, user, token, request)` и `async def on_after_forgot_password(self, user, token, request)` — внутри собрать deeplink (`{frontend_base_url}/auth/confirm-email?token={token}` / `…/reset-password?token={token}`), `html = await render_email("verify-email"/"reset-password", {"url": link, "name": user.email or ...})`, `await send_email(user.email, subject, html)`. Логировать факт отправки БЕЗ токена/email-в-открытую.
- **Авто-verify после register:** опц. в `on_after_register` вызвать `await self.request_verify(user, request)` (если позволяет версия) — письмо без отдельного действия.
- **no-enumeration:** не добавлять собственную ветку «email not found → 404» — оставить дефолтное поведение fastapi-users (единообразный `202`/ответ). UI-копия нейтральная.
- **frontend enable:** найти флаг/условие, которым страницы помечены «не активны» (из task-014), снять; `reset-password`/`confirm-email` читают `token` из `useSearchParams`; submit → мутация на gen.types; показать success/expired-token состояния.
- **e2e mailpit:** после register/forgot — poll `GET http://mailpit:8025/api/v1/messages` → достать письмо → распарсить токен из ссылки (regex по `token=`) → выполнить verify/reset; ассертить итог (is_verified / login новым паролем).
- **security:** проверить, что в логах api нет токенов/паролей (grep); deeplink в проде https; токен повторно не срабатывает.
