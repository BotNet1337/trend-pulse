---
id: TASK-014
title: Auth flow UI — register/login/logout (httpOnly-cookie), Google OAuth, guarded-роуты, current_user
status: in-progress      # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "2f90fcfa51ad3282978dc5c403f2c22e917d278f"
branch: "gsd/phase-014-auth-flow-ui"
tags: [frontend, auth, oauth, e2e, security]
---

# TASK-014 — Auth flow UI (Epic C · C2)

> Реализовать auth-флоу SPA TrendPulse поверх готового backend (task-003): регистрация/вход/выход на **httpOnly-cookie** (адаптировать страницы реф-проекта `pages/auth/*` под TrendPulse-эндпоинты), кнопка **Google OAuth** (→ `/auth/google/authorize`), **guarded-роуты** (неавторизованного редиректим на `/login`, после логина возвращаем на исходный роут), и `current_user` во фронте из **`GET /users/me`** — тонкая backend-добавка этого read-роута (смонтировать `fastapi-users` `get_users_router` ИЛИ собственный тонкий read-роут: email, plan, is_verified). e2e на весь флоу через nginx. Без секретов на фронте.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §3) — multi-tenant SaaS; auth — `fastapi-users` (httpOnly-cookie), реализован в [task-003](./task-003-auth.md). Backend-роуты (источник истины): `POST /auth/register` (`UserCreate`: email+password), `POST /auth/jwt/login` (form `username`+`password` → ставит httpOnly-cookie), `POST /auth/jwt/logout`, `GET /auth/google/authorize` → redirect на Google, `GET /auth/google/callback` (CSRF double-submit cookie; `associate_by_email`). Protected-пример: `GET /users/me/tenant` → `{user_id}`. **Полноценного `GET /users/me` (email/plan/is_verified) НЕТ** — UI его требует для `current_user`, поэтому C2 добавляет тонкий read-роут.

База — [task-013](./task-013-frontend-foundation.md) (C1): дизайн-система, API-клиент (cookie-auth, baseURL `/api`, `withCredentials: true`), типы из TrendPulse OpenAPI, Playwright-харнесс, `frontend` за nginx. Реф-проект уже содержит `pages/auth/*` (sign-in/sign-up/forgot/reset/confirm) — адаптируем под TrendPulse-эндпоинты (forgot/reset/confirm-verify оставляем только если backend их монтирует; иначе скрываем/помечаем как out-of-scope).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — для backend-добавки `GET /users/me`: full type hints, Pydantic на границе, no magic literals, `current_user`-зависимость, секреты из env. Frontend: cookie-auth, no secrets в бандле.

## Goal

После задачи: пользователь регистрируется (`POST /auth/register`), логинится (`POST /auth/jwt/login` → httpOnly-cookie), выходит (`POST /auth/jwt/logout` → cookie сбрасывается); кнопка «Войти через Google» ведёт на `GET /auth/google/authorize`; неавторизованный на protected-роуте редиректится на `/login`, после успешного логина возвращается на исходный роут; `current_user` (email, plan, is_verified) читается из нового `GET /users/me`; неверный пароль показывает понятную ошибку (без user-enumeration). e2e покрывают happy + negative + guard + OAuth-redirect через nginx. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по task-003 контракту; обратимы. -->
- Q: Откуда фронт берёт `current_user`? → A: backend `GET /users/me` → Decision: **тонкая backend-добавка** — смонтировать `fastapi-users` `get_users_router` (даёт `GET /users/me` с `UserRead`: email, is_verified, …) ИЛИ собственный read-роут `GET /users/me` (email, plan, is_verified) за `current_user`. `plan` берётся из User/биллинга (task-010). Минимальный additive read-роут, без мутаций (UserUpdate в C2 не требуется).
- Q: Login-форма — какой контракт? → A: `POST /auth/jwt/login` — form `username`+`password` (OAuth2 password flow fastapi-users) → Decision: фронт шлёт `application/x-www-form-urlencoded` с `username=email`; cookie ставится backend'ом, фронт её не читает (httpOnly).
- Q: Google OAuth — как из SPA? → A: редирект на `GET /auth/google/authorize` → Decision: кнопка = переход браузера (не fetch) на `/api/auth/google/authorize`; backend ведёт через Google и `…/callback` (CSRF double-submit cookie внутри либы), затем редирект обратно в SPA с установленной cookie.
- Q: Guard и возврат после логина? → A: protected-роуты за guard → Decision: guard проверяет `current_user` (через `GET /users/me`, 401 → не авторизован); редирект на `/login?next=<path>`; после логина — возврат на `next` (валидируем, что `next` — внутренний путь, не open-redirect).
- Q: forgot/reset/confirm-email страницы реф-проекта? → A: только если backend монтирует соответствующие роутеры fastapi-users → Decision: по умолчанию вне scope C2 (task-003 их явно не подключал); страницы скрываем/помечаем «не активны», чтобы не вести на несуществующие эндпоинты. Активация — отдельная задача при включении reset/verify-роутеров.
- Q: Где брать `plan` для UI? → A: из `GET /users/me` → Decision: read-роут отдаёт `plan` (Free/Pro/Team) — используется и в C3 (лимиты) и C5 (биллинг); единый источник current_user во фронте.

## Scope
> Затрагивает **`frontend/`** (auth-страницы, guard, current_user-entity, e2e) + **тонкую backend-добавку** `GET /users/me` (read-only, за `current_user`) и её тест. Auth-механику (хэш/JWT/cookie/OAuth) НЕ трогаем — она в task-003.

- **Touch ONLY (создать/изменить):**
  - **Backend (тонкая additive-добавка):**
    - `backend/src/trendpulse/api/auth/schemas.py` — `UserRead` (email, is_verified, plan) если не покрыт; или dedicated read-схема.
    - `backend/src/trendpulse/api/main.py` — смонтировать `get_users_router` (`/users`, даёт `GET /users/me`) ИЛИ `include_router` собственного тонкого `GET /users/me` (за `current_user`, read-only).
    - `backend/src/trendpulse/api/auth/me.py` — **(если собственный роут)** тонкий `GET /users/me` → `UserRead` (email, plan, is_verified) из `current_user`; full type hints, Pydantic, no magic literals.
    - `backend/tests/integration/test_users_me.py` — AC: `GET /users/me` 401 без cookie / 200 c cookie (email/plan/is_verified).
  - **Frontend:**
    - `frontend/src/pages/auth/sign-in.tsx`, `sign-up.tsx`, `layout.tsx` — адаптировать под TrendPulse-эндпоинты (`/auth/register`, `/auth/jwt/login` form-urlencoded), копи/бренд.
    - `frontend/src/pages/auth/{forgot-password,reset-password,confirm-email,confirm-email-change}.tsx` — пометить out-of-scope/скрыть, если backend не монтирует reset/verify-роутеры (не вести на несуществующее).
    - `frontend/src/features/auth/**` — **новый/адаптированный** feature: `register`, `login` (form-urlencoded), `logout` (`POST /auth/jwt/logout`), Google-кнопка (редирект на `/api/auth/google/authorize`).
    - `frontend/src/entities/viewer/**` (или `entities/user`) — `current_user` из `GET /users/me`; query/hook `useCurrentUser`.
    - `frontend/src/app/router/**` — guarded-роуты: redirect на `/login?next=` при 401; возврат после логина (валидация `next` — internal-only).
    - `frontend/src/shared/api/client.ts` — 401-interceptor → guard-redirect (если не выставлен в C1).
    - `frontend/tests/e2e/auth.spec.ts` — **новый** e2e: register/login/logout happy, неверный пароль, guard-redirect+возврат, OAuth-redirect.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/trendpulse/api/auth/{backend,oauth,users}.py` ядро auth (хэш/JWT/cookie/OAuth — task-003; меняем только монтирование users-роутера/добавляем read-схему), `collector/**`/`pipeline/**`/`scorer/**`/`alerts/**`/`billing/**`. Не реализовывать watchlists/alerts/billing-экраны (C3–C5). Не вводить мутации пользователя (UserUpdate) — только read `GET /users/me`.
- **Blast radius:** добавляет `current_user`-источник (`GET /users/me`) — потребляется C3 (лимиты по plan), C5 (биллинг/plan). Guard-инфраструктура — основа для всех protected-страниц C3–C5. Backend-добавка аддитивна (новый read-роут за `current_user`), ядро auth не меняется.

## Acceptance Criteria
- [ ] **AC1 — register→login ставит cookie, `GET /users/me` отдаёт юзера (failing-test anchor).** Given чистый пользователь, When UI делает `POST /auth/register` затем `POST /auth/jwt/login` (form `username`+`password`), Then httpOnly-cookie установлена и `GET /users/me` → `200` с `email`/`plan`/`is_verified`; UI показывает залогиненное состояние. e2e + integration-тест пишутся ПЕРВЫМИ (RED).
- [ ] **AC2 — `GET /users/me` 401 без cookie / 200 с cookie (backend-добавка).** Given новый read-роут, When запрос без auth-cookie, Then `401`; с валидной cookie — `200` `UserRead` (email, plan, is_verified); за `current_user`, tenant-scoped.
- [ ] **AC3 — logout сбрасывает сессию.** Given залогиненный пользователь, When UI делает `POST /auth/jwt/logout`, Then cookie сбрасывается, `GET /users/me` → `401`, UI редиректит на `/login`.
- [ ] **AC4 — guard + возврат после логина.** Given неавторизованный пользователь заходит на protected-роут, When нет cookie, Then редирект на `/login?next=<path>`; после успешного логина — возврат на `<path>` (внутренний путь; внешний `next` игнорируется — no open-redirect).
- [ ] **AC5 — неверный пароль → понятная ошибка, без enumeration.** Given существующий email + неверный пароль, When login, Then UI показывает дружелюбную ошибку (не raw-JSON/стек), сообщение не раскрывает, существует ли email (поведение fastapi-users).
- [ ] **AC6 — Google OAuth redirect.** Given кнопка «Войти через Google», When клик, Then браузер уходит на `GET /api/auth/google/authorize` (302 на Google); e2e проверяет переход на authorize-URL (внешний Google-flow — мок/стоп на редиректе).
- [ ] **AC7 — поведенческая (G2) проверка через nginx.** Given `make up`, When Playwright `auth.spec.ts` гоняется против реального стека за nginx, Then AC1/AC3/AC4/AC5/AC6 наблюдаемы; артефакты (trace/screenshot/video on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-014-auth-flow-ui`.
1. **RED (backend):** `backend/tests/integration/test_users_me.py` — `GET /users/me` 401 без cookie / 200 c cookie. Падает (роута нет). AC2-якорь.
2. Backend-добавка: смонтировать `get_users_router` (`/users`) или тонкий `GET /users/me` (`api/auth/me.py`) → `UserRead` (email, plan, is_verified) за `current_user`; `make ci-fast` зелёный.
3. **RED (frontend):** `frontend/tests/e2e/auth.spec.ts` — register→login→`/users/me` показывает залогиненное состояние. Падает. AC1-якорь.
4. `features/auth/**` — `register`, `login` (form-urlencoded), `logout`; `entities/viewer` — `useCurrentUser` из `GET /users/me`; адаптировать `pages/auth/{sign-in,sign-up}`.
5. `app/router` — guard: 401 → `/login?next=`; возврат после логина (валидация internal `next`); скрыть/отключить неактивные forgot/reset/confirm-страницы.
6. Google-кнопка → редирект на `/api/auth/google/authorize`.
7. **GREEN/G2:** `make up`; Playwright `auth.spec.ts` зелёный через nginx (AC1/AC3/AC4/AC5/AC6/AC7); backend integration зелёный (AC2).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Cookie-auth, никаких токенов в JS** — httpOnly-cookie ставит/сбрасывает backend; фронт не читает/не хранит токены (контракт task-003); `withCredentials: true`.
- **`current_user` только из `GET /users/me`** (за `current_user`, tenant-scoped) — единый источник для C3/C5; никаких клиентских «фейковых» сессий.
- **No open-redirect** — `next` после логина валидируется как внутренний путь; внешние URL отбрасываются.
- **No user-enumeration** — ошибка логина единообразна (поведение fastapi-users), UI не раскрывает существование email.
- **No secrets в бандле** — Google client id/secret живут на backend; фронт только инициирует редирект на authorize-URL.
- **Backend-добавка — read-only, full type hints, Pydantic на границе, no magic literals** (CONVENTIONS); ядро auth (хэш/JWT/cookie/OAuth) не трогается.
- **Единая дизайн-система** (C1) — auth-страницы используют общие токены/компоненты; responsive + базовая a11y (label/aria/focus).

## Edge cases
- `next` = внешний URL (`//evil.com`) → отбросить, редиректить на дефолтный домашний роут (no open-redirect).
- Повторная регистрация существующего email → backend `400`; UI показывает понятную ошибку, не падает.
- Google callback вернулся, но cookie не установилась (CSRF/state mismatch) → UI остаётся на `/login` с понятным сообщением, не зацикливается.
- `GET /users/me` 401 во время сессии (cookie истекла) → guard ловит, редиректит на `/login`, не показывает raw-401.
- forgot/reset/confirm-страницы ведут на несмонтированный backend-роутер → отключены в C2 (не 404-ить пользователя).
- Двойной сабмит login-формы → дизейбл кнопки на время запроса (idempotent UX), без двойного запроса.
- `plan` отсутствует у нового пользователя → дефолт `Free` (источник — backend, не magic literal на фронте).

## Test plan
- **integration (backend):** `test_users_me.py` — AC2 (`GET /users/me` 401/200, email/plan/is_verified, за `current_user`); RED-якорь.
- **e2e (Playwright):** `tests/e2e/auth.spec.ts` — AC1 (register→login→залогинен, RED-якорь), AC3 (logout→401→`/login`), AC4 (guard+возврат, no open-redirect), AC5 (неверный пароль → дружелюбная ошибка, no enumeration), AC6 (Google → authorize-redirect). Артефакты on-failure.
- **runtime/behavioral (G2):** `make up` → Playwright против реального стека за nginx (AC7); ручная проверка cookie httpOnly (не читается из JS) + logout-сброс.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "2f90fcfa51ad3282978dc5c403f2c22e917d278f"
branch: "gsd/phase-014-auth-flow-ui"
lock: "loop-014"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — build + Playwright e2e + real behavior через nginx)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (XSS/санитизация, secrets не в бандле, cookie/CSRF, SSRF в webhook-полях)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-003/004 и контексту: auth-флоу SPA на httpOnly-cookie поверх task-003 (register/login/logout, Google OAuth redirect, guard+возврат), `current_user` из новой тонкой backend-добавки `GET /users/me` (read-only, за `current_user`). deps: 013 (C1 фундамент), backend 003 (auth). Ядро auth не трогаем — только монтируем users-read-роут. locate+plan выполнены этим планированием — executor стартует с «3 do».)
