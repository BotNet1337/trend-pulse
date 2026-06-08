---
id: TASK-003
title: Auth — fastapi-users (email/пароль + Google OAuth, JWT + cookie)
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: ""    # set by executor at ship time
branch: ""             # set by executor at ship time
tags: [backend, auth, oauth, jwt, security]
---

# TASK-003 — Auth (fastapi-users · email/пароль + Google OAuth · JWT + httpOnly cookie)

> Подключить аутентификацию TrendPulse на готовой библиотеке **`fastapi-users`** (НЕ катаем свой auth, ADR-003): регистрация/вход по email+паролю (хэш argon2 из коробки), вход через Google OAuth (через `httpx-oauth` GoogleOAuth2), JWT + httpOnly-cookie транспорт для SPA, и переиспользуемая FastAPI-зависимость `current_user`, которой защищаются все пользовательские эндпоинты. Мы **конфигурируем** библиотеку, а не реализуем хэширование/токены/OAuth-flow руками. Тенант-скоуп — `user_id` из токена (ADR-002). Все секреты — из `sensitive.env` (ADR-005), не в коде.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §3) — multi-tenant SaaS; auth — **готовая библиотека `fastapi-users`**, без внешнего SaaS-провайдера (Clerk/Auth0), решено в [ADR-003](../architecture/adr-003-monorepo-and-auth.md): email+пароль (хэш argon2/passlib из коробки) **и** Google OAuth (через `httpx-oauth` GoogleOAuth2), JWT access + refresh, для SPA — httpOnly cookie-транспорт fastapi-users, все пользовательские эндпоинты за зависимостью `current_user` от fastapi-users, тенант-скоуп по `user_id` (ADR-002). Это первая задача, которая вводит понятие «залогиненный пользователь» в API — она задаёт контракт защиты для всех последующих роутов (watchlist task-004, billing task-010, alert-config task-009).

Зависит от **task-002** (data model + миграции + multi-tenancy): таблица `users` и базовый tenant-scope (`user_id`) приходят оттуда; здесь таблица `users` выравнивается с базовой user-таблицей fastapi-users (`SQLAlchemyBaseUserTable`: `id`, `email`, `hashed_password`, `is_active`, `is_superuser`, `is_verified`) и добавляется OAuth-аккаунт-таблица fastapi-users (`SQLAlchemyBaseOAuthAccountTable`) через Alembic-миграцию.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — **Auth = `fastapi-users` (+ httpx-oauth Google), не катаем свой**; full type hints, no magic literals (TTL/секреты в pydantic-settings, Pydantic validates at boundary, SQL via SQLAlchemy bind params, secrets via env только). Источник секретов — `sensitive.env` (ADR-005), материализуется через `make ansible-unpack`.

## Goal

После задачи: новый пользователь делает `POST /auth/register` → `POST /auth/jwt/login` (роуты fastapi-users) и получает валидный JWT; защищённый эндпоинт отдаёт `401` без токена и `200` с валидным; httpOnly-cookie сессия работает (логин ставит cookie, refresh/redeem обновляет её); `GET /auth/google/authorize` → `…/callback` создаёт или линкует пользователя по Google-идентичности (`httpx-oauth`); неверный пароль отклоняется. Все секреты (Google client id/secret, JWT secret) — из `sensitive.env`. Всё через root `make`. DoD — Acceptance Criteria ниже.

## Discussion
<!-- durable record of clarifications. Решения по дефолтам ADR-003; обратимы. -->
- Q: Катать свой auth или библиотека? → A: **библиотека** → Decision: **`fastapi-users`** (ADR-003). Auth — частый источник уязвимостей; зрелая либа корректно закрывает хэширование/JWT/cookie/OAuth-flow. Мы конфигурируем, не реализуем сами. Стадия 5.5 `trendpulse-security` всё равно обязательна.
- Q: Какие пакеты? → A: `fastapi-users[sqlalchemy]` + `fastapi-users-db-sqlalchemy` (адаптер под нашу SQLAlchemy-БД) + `httpx-oauth` (Google) → Decision: добавляются в backend-deps; `pyproject.toml` из task-001 получает эти зависимости (см. Plan §1).
- Q: Хэш пароля? → A: argon2 из коробки fastapi-users (passlib) → Decision: используем встроенный `PasswordHelper`/argon2, ничего не пишем сами; параметры — дефолты библиотеки (OWASP-совместимы).
- Q: JWT — какой транспорт и где живёт? → A: для SPA — httpOnly cookie → Decision: auth-backend fastapi-users = JWT-стратегия (`get_strategy`, `lifetime_seconds` из settings) + **`CookieTransport`** (httpOnly + Secure + SameSite). TTL — named constant/settings (`jwt_lifetime_seconds`), не магический литерал (CONVENTIONS).
- Q: Google OAuth — flow? → A: OAuth-router fastapi-users + `httpx-oauth` `GoogleOAuth2` → Decision: `fastapi_users.get_oauth_router(google_oauth_client, auth_backend, state_secret, …)` отдаёт `/auth/google/authorize` и `/auth/google/callback`; flow (state/обмен кода/верификация) — внутри библиотеки. `state_secret` — из settings.
- Q: Линковка Google-аккаунта с существующим email? → A: `associate_by_email` fastapi-users → Decision: включаем `associate_by_email=True` в OAuth-роутере — линковка по верифицированному email через `OAuthAccount`-таблицу; иначе создаётся новый пользователь.
- Q: JWT secret/state secret — откуда? → A: из `sensitive.env` (ADR-005) → Decision: `jwt_secret`, `oauth_state_secret`, `google_client_id/secret` — в pydantic-settings, читаются из env (`sensitive.env`), валидируются на старте (fail-fast), никогда не хардкодятся.
- Q: Где живёт auth-код? → A: модуль `api/auth/` — тонкая обвязка над fastapi-users → Decision: `api/auth/` конфигурирует `FastAPIUsers`-инстанс, auth-backend, OAuth-клиент/роутер, user-manager; `current_user` re-export для других роутеров (CONVENTIONS — cross-module через публичные функции).

## Scope
> **Раскладка:** задача трогает **только `backend/`** (+ `pyproject.toml` deps, +`sensitive.env`/`deploy.env` примеры). Auth-модуль `api/auth/` — конфигурация fastapi-users, не реализация. Затрагивает `trendpulse-security` (auth, OAuth, JWT, cookie, секреты) — стадия 5.5 **обязательна**.

- **Touch ONLY (создать/изменить):**
  - `backend/pyproject.toml` — добавить deps: `fastapi-users[sqlalchemy]`, `fastapi-users-db-sqlalchemy`, `httpx-oauth` (база из task-001 их получает).
  - `backend/src/trendpulse/api/auth/__init__.py` — публичный экспорт `current_user` (re-export для других роутеров) и сборки роутеров.
  - `backend/src/trendpulse/api/auth/users.py` — `User`/`OAuthAccount` SQLAlchemy-модели на базе fastapi-users (`SQLAlchemyBaseUserTable`, `SQLAlchemyBaseOAuthAccountTable`), `get_user_db` (через `SQLAlchemyUserDatabase`), `UserManager` (`on_after_register`/`on_after_*` hooks, `password_helper` argon2).
  - `backend/src/trendpulse/api/auth/backend.py` — `AuthenticationBackend` (имя, `CookieTransport` httpOnly+Secure+SameSite, `JWTStrategy` с `lifetime_seconds`/`secret` из settings); `FastAPIUsers` инстанс; `current_user = fastapi_users.current_user(active=True)`.
  - `backend/src/trendpulse/api/auth/oauth.py` — `GoogleOAuth2` клиент (`httpx-oauth`) из settings; конфиг OAuth-роутера (`associate_by_email=True`, `state_secret`).
  - `backend/src/trendpulse/api/auth/schemas.py` — `UserRead`/`UserCreate`/`UserUpdate` (наследники `schemas.BaseUser*` fastapi-users) — Pydantic на границе.
  - `backend/src/trendpulse/api/deps.py` — re-export `current_user` как общая FastAPI-зависимость для прочих роутеров; helper извлечения тенант `user_id` из объекта пользователя.
  - `backend/src/trendpulse/storage/` — выравнивание `users` с базовой user-таблицей fastapi-users (`hashed_password`, `is_active/is_superuser/is_verified`), добавление `oauth_accounts` (fastapi-users); Alembic-миграция.
  - `backend/src/trendpulse/config.py` — добавить settings: `jwt_secret`, `jwt_lifetime_seconds`, `oauth_state_secret`, `google_client_id`, `google_client_secret` (pydantic-settings, из env), валидация обязательности на старте.
  - `backend/src/trendpulse/api/main.py` — подключить роутеры fastapi-users: `get_auth_router` (`/auth/jwt`), `get_register_router` (`/auth`), `get_oauth_router` (`/auth/google`), опц. reset/verify; пример защищённого роута через `current_user` для AC2.
  - `development/env/deploy.env` / `development/env/sensitive.env` — примеры ключей: `JWT_SECRET`, `JWT_LIFETIME_SECONDS`, `OAUTH_STATE_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (секреты → `sensitive.env`, gitignored; реальные значения из Ansible, ADR-005).
  - `backend/tests/unit/test_auth.py`, `backend/tests/integration/test_auth_flow.py` — RED→GREEN якоря (AC1 ниже) + интеграционный flow.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`, `collector/**`, `pipeline/**`, `scorer/**`, `alerts/**`, `billing/**`. Не вводить plan-gating/лимиты тарифа (это task-010). Не менять multi-tenancy-ядро из task-002 (только выровнять `users` под fastapi-users + добавить `oauth_accounts`). Не реализовывать хэширование/JWT/OAuth-flow руками — это даёт библиотека.
- **Blast radius:** вводит `current_user`-зависимость fastapi-users — контракт защиты для всех последующих пользовательских роутов (task-004 watchlist, task-009 alert-config, task-010 billing). Меняет схему `users` (выравнивание) и добавляет `oauth_accounts` (миграция). Затрагивает безопасность (хэш паролей, JWT, OAuth-callback, cookie, секреты) → **`trendpulse-security` обязателен** (стадия 5.5).

## Acceptance Criteria
- [ ] **AC1 — register→login выдаёт валидный JWT (failing-test anchor).** Given чистая БД, When `POST /auth/register {email,password}` затем `POST /auth/jwt/login` (form `username`+`password`), Then `200` + валидный JWT, выданный backend'ом fastapi-users (декодируется секретом из settings, `sub == user_id`, не просрочен), и установлена httpOnly auth-cookie. Тест пишется ПЕРВЫМ (RED).
- [ ] **AC2 — защищённый роут 401 без токена / 200 с токеном.** Given защищённый `current_user`-эндпоинт, When запрос без cookie/Authorization, Then `401`; When с валидной auth-cookie (или Bearer), Then `200` и доступен `user_id` тенанта из объекта пользователя.
- [ ] **AC3 — cookie/refresh работает.** Given успешный login (auth-cookie установлена), When повторный запрос к защищённому роуту с этой cookie, Then `200`; When `POST /auth/jwt/logout`, Then cookie сбрасывается и последующий запрос → `401`.
- [ ] **AC4 — Google OAuth callback создаёт/линкует пользователя.** Given `GET /auth/google/authorize` вернул redirect на Google со `state`, When `GET /auth/google/callback?code&state` (обмен кода через `httpx-oauth` замокан/тестовый), Then пользователь по Google-идентичности создан или слинкован с существующим верифицированным email (`associate_by_email`), запись в `oauth_accounts`, выданы токены.
- [ ] **AC5 — неверный пароль отклоняется.** Given существующий пользователь, When `POST /auth/jwt/login` с неверным паролем, Then `400/401` от fastapi-users (без утечки, существует ли email).
- [ ] **AC6 — секреты только из env.** Given отсутствует `JWT_SECRET`/`OAUTH_STATE_SECRET`/Google creds в окружении, When старт приложения, Then явная ошибка валидации settings (fail-fast); в коде нет хардкод-секретов; секреты — из `sensitive.env`.
- [ ] **AC7 — поведенческая (G2) проверка реальным curl.** Given `make up`, When `curl` через nginx по сценарию register→login→protected(401/200)→logout, Then наблюдаемое поведение совпадает с AC1–AC3 на запущенном API.

## Plan
0. Executor фиксирует `baseline_commit` от текущего HEAD; ветка `gsd/phase-3-auth`.
1. `backend/pyproject.toml` — добавить deps `fastapi-users[sqlalchemy]`, `fastapi-users-db-sqlalchemy`, `httpx-oauth` (база из task-001 их получает); `config.py` — settings (`jwt_secret`, `jwt_lifetime_seconds`, `oauth_state_secret`, `google_client_id/secret`), валидация обязательности на старте; примеры в `development/env/deploy.env`+`sensitive.env`. (AC6)
2. `storage/` + `api/auth/users.py` — выровнять `users` под `SQLAlchemyBaseUserTable` (`hashed_password`, `is_active/is_superuser/is_verified`), добавить `OAuthAccount` (`SQLAlchemyBaseOAuthAccountTable`); `get_user_db` через `SQLAlchemyUserDatabase`; Alembic-миграция (`oauth_accounts` + выравнивание `users`).
3. `api/auth/users.py` — `UserManager` (`reset_password_token_secret`/`verification_token_secret` из settings, `password_helper` argon2, `on_after_register` hook); `get_user_manager` dependency.
4. `api/auth/backend.py` — `CookieTransport` (httpOnly+Secure+SameSite), `JWTStrategy` (`secret`/`lifetime_seconds` из settings), `AuthenticationBackend`; `FastAPIUsers[User, UUID]` инстанс; `current_user = fastapi_users.current_user(active=True)`.
5. `api/auth/oauth.py` — `GoogleOAuth2(client_id, client_secret)` из settings; параметры OAuth-роутера (`associate_by_email=True`, `state_secret=oauth_state_secret`).
6. `api/auth/schemas.py` — `UserRead`/`UserCreate`/`UserUpdate` на базе `schemas.BaseUser*`.
7. `api/deps.py` — re-export `current_user` как общая зависимость; helper тенант `user_id`.
8. `api/main.py` — `include_router` для `get_auth_router` (`/auth/jwt`), `get_register_router` (`/auth`), `get_oauth_router(google, backend, state_secret, associate_by_email=True)` (`/auth/google`); навесить `current_user` на пример защищённого роута для AC2.
9. Тесты: `tests/unit/test_auth.py` (AC1 RED первым: register→login→валидный JWT; затем AC5 неверный пароль), `tests/integration/test_auth_flow.py` (AC4 Google callback с замоканным обменом через `httpx-oauth`, AC3 cookie/logout против реальной БД).
10. `make ci-fast` (ruff+mypy+pytest) зелёный; затем `make up` и G2-проверка AC7 реальным `curl` через nginx.

## Invariants
- **НЕ катаем свой auth** — хэширование, JWT, cookie, OAuth-flow дают `fastapi-users` + `httpx-oauth`; мы только конфигурируем (ADR-003). Никакой собственной реализации хэшей/токенов/обмена кода.
- **Секреты только из env/`sensitive.env`** (`jwt_secret`, `oauth_state_secret`, Google creds) — никаких хардкодов; валидируются на старте (fail-fast). `sensitive.env` в `.gitignore`, источник — Ansible (`make ansible-unpack`, ADR-005).
- **Никаких магических литералов** для TTL — `jwt_lifetime_seconds` в settings, время в секундах (CONVENTIONS).
- **Все пользовательские эндпоинты — за `current_user`** (зависимость fastapi-users, `Depends`); тенант-скоуп строго по `user_id` из токена/пользователя (ADR-002), не из тела запроса.
- **JWT + httpOnly cookie для SPA** — auth-backend = JWTStrategy + CookieTransport (httpOnly+Secure+SameSite); access подписывается серверным секретом, короткий TTL.
- **Google OAuth — через библиотеку** — `get_oauth_router` + `httpx-oauth GoogleOAuth2`; state/обмен кода/верификация внутри либы; линковка `associate_by_email`.
- **Пароли — argon2 (PasswordHelper fastapi-users)**, никогда не хранятся/логируются в открытом виде; ответ при неверном email/пароле неразличим (no user enumeration — поведение библиотеки).
- **Pydantic валидирует вход на границе** (схемы `BaseUser*`); full type hints, no bare `Any`/`# type: ignore`; SQL — только через SQLAlchemy bind params (адаптер fastapi-users-db-sqlalchemy).

## Edge cases
- Повторная регистрация с тем же email → `400` (`REGISTER_USER_ALREADY_EXISTS` от fastapi-users), не молчаливый дубль.
- Просроченный/искажённый/неподписанный JWT (cookie или Bearer) → `401`, единообразно (поведение JWTStrategy), не `500`.
- Logout с уже истёкшей/несуществующей сессией → корректный сброс cookie, без `500`.
- Google `state` mismatch / отсутствует / истёк → библиотека отклоняет callback, не создавать пользователя.
- Google email совпадает с существующим, но `associate_by_email=False`/конфликт → поведение по конфигу либы; не молчаливый небезопасный merge (выбран `associate_by_email=True` для верифицированного email).
- Часовые сдвиги/clock skew в `exp` → дефолтное поведение JWTStrategy; TTL из настройки, не хардкод.
- Отсутствие `JWT_SECRET`/`OAUTH_STATE_SECRET`/Google creds в окружении → fail-fast валидацией settings на старте, не «работает наполовину».
- Выравнивание `users` под fastapi-users не должно ломать tenant-scope task-002 — миграция аддитивная/совместимая.

## Test plan
- **unit:** `tests/unit/test_auth.py` — AC1 (register→login→декодируемый валидный JWT с `sub==user_id`, секрет из settings) пишется ПЕРВЫМ (RED); неверный пароль → отказ (AC5); decode просроченного/искажённого JWT через JWTStrategy → ошибка; UserManager hooks (`on_after_register`) вызываются.
- **integration:** `tests/integration/test_auth_flow.py` — против реальной БД (поднятый compose, маркер `integration`): полный register→login(auth-cookie)→`current_user`(401/200, AC2)→logout(сброс cookie, AC3); Google callback (AC4) с замоканным обменом `code` через `httpx-oauth GoogleOAuth2`, проверка create+link (`associate_by_email`) и записи в `oauth_accounts`.
- **runtime/behavioral (G2):** `make up` → реальный `curl` через nginx, сценарий AC7: register, login (получить auth-cookie), запрос защищённого роута без/с cookie (401/200), logout (сброс cookie → 401).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED — auth, OAuth, JWT, cookie, password hashing, secrets → triggers `trendpulse-security`)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по обновлённому ADR-003 (auth = готовая библиотека `fastapi-users` + `httpx-oauth` Google, JWT + httpOnly cookie, `current_user`-зависимость, тенант-скоуп ADR-002) и overview §3; секреты из `sensitive.env` (ADR-005); зависит от task-002 (data model + multi-tenancy). Ключевое: конфигурируем библиотеку, не катаем свой auth. Стадия 5.5 security обязательна.)
</content>
</invoke>
