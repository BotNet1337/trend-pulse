---
id: TASK-028
title: API keys for Team plan — issue/list/revoke + X-API-Key auth backend (hashed at-rest, feature-gated)
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-028-api-keys-team"
tags: [epic-d, backend, api, billing, security]
---

# TASK-028 — API keys for Team plan (Epic D)

> Team-план продаёт «API access» (`Resource.API_ACCESS`, `_TEAM_API=True` в `billing/plans.py`), но механизма ключей НЕТ. (1) Таблица `api_keys (id, user_id, key_hash, name, prefix, created_at, last_used_at, revoked_at)` (Alembic; хранить ТОЛЬКО хэш, не plaintext; plaintext показать один раз при создании). (2) Эндпоинты `POST /api-keys` (issue, feature-gate Team через `assert_within_limit(API_ACCESS)`→403 на Free/Pro), `GET /api-keys` (list, маскированно), `DELETE /api-keys/{id}` (revoke) — за `current_user`. (3) Auth-backend `X-API-Key` (header) — резолвит user по `key_hash`, для программного доступа к read-эндпоинтам (alerts/watchlists); rate-limit keying по api-key-принципалу (`api/rate_limit.py`). AC: Team-юзер создаёт ключ (plaintext один раз), ключом аутентифицируется на `GET /alerts`, Free/Pro→403 на создание, revoke отключает ключ; ключ хранится хэшированным. Security 5.5 ОБЯЗАТЕЛЬНА: хэширование, constant-time compare, feature-gate, no plaintext at-rest.

## Context

TrendPulse тарифы ([`../product/overview.md`](../product/overview.md) §6, [task-010](./task-010-billing-nowpayments.md)): Team ($79/мес) включает «API access». В `backend/src/billing/plans.py`: `Resource.API_ACCESS`, `_TEAM_API = True`, `FEATURE_RESOURCES` включает `API_ACCESS` — т.е. фича объявлена и feature-gating через `assert_within_limit`/`limits.py` существует, но **механизма выпуска и использования API-ключей НЕТ**: нельзя ни создать ключ, ни аутентифицироваться им. Пользователь Team платит за то, чего технически не существует.

Auth ([ADR-003](../architecture/adr-003-monorepo-and-auth.md), task-003): fastapi-users (`backend/src/api/auth/` — `backend.py` JWT/cookie, `users.py` UserManager, `me.py` `current_user`). Read-эндпоинты для потребления данных: `GET /alerts` ([task-016](./task-016-alerts-ui.md), `api/alerts/`), watchlists (`api/watchlist/`). Rate-limit: `backend/src/api/rate_limit.py` (slowapi, keying per-user/IP). Billing feature-gate: `billing/limits.py` `assert_within_limit(Resource.X)` (`PlanLimitExceeded`→handler→`403`/`402`). Storage-модели: `backend/src/storage/models/` (Alembic-миграции).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — секреты не в открытом виде at-rest, full type hints, Pydantic на границе, no magic literals, tenant-scoped. Security-чувствительно (выпуск/хранение/проверка ключей) → стадия 5.5 обязательна.

## Goal

После задачи: (1) Team-пользователь создаёт API-ключ (`POST /api-keys`) — plaintext-ключ возвращается РОВНО ОДИН раз при создании, в БД хранится только `key_hash` + `prefix` (для отображения) + метаданные; Free/Pro → `403` (feature-gate `API_ACCESS`). (2) `GET /api-keys` — список своих ключей маскированно (prefix + name + created/last_used/revoked, без полного ключа); `DELETE /api-keys/{id}` — revoke (ставит `revoked_at`, ключ перестаёт работать). (3) Новый auth-backend по заголовку `X-API-Key`: резолвит пользователя по `key_hash` (constant-time), отклоняет revoked/неизвестные; даёт программный доступ к read-эндпоинтам (alerts/watchlists) как `current_user`. (4) Rate-limit keyed по api-key-принципалу. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по plans.py/task-003/010/016; обратимы. -->
- Q: Что хранить в БД? → A: secret at-rest нельзя plaintext → Decision: таблица `api_keys`: `id`, `user_id` (FK, tenant), `key_hash` (хэш полного ключа), `name` (метка пользователя), `prefix` (первые символы для отображения/поиска), `created_at`, `last_used_at`, `revoked_at` (nullable). Plaintext НЕ хранится — показывается один раз в ответе `POST`.
- Q: Хэш — какой? → A: ключ = высокоэнтропийный токен (не пароль пользователя) → Decision: для случайного 256-битного токена достаточно быстрого SHA-256 хэша (не нужен bcrypt/argon — нет brute-force-риска при высокой энтропии), сравнение **constant-time** (`secrets.compare_digest`). Решение исполнителя; ключевое — НЕ plaintext + constant-time.
- Q: Формат ключа? → A: узнаваемый + индексируемый → Decision: `tp_<prefix>_<random>` (named-константа префикса бренда); `prefix` (первые ~8 символов после `tp_`) хранится отдельно для быстрого lookup-narrow + отображения, lookup финально по `key_hash` (compare_digest). Энтропия — из `secrets.token_urlsafe`, длина — named constant.
- Q: Feature-gate? → A: уже есть `assert_within_limit` → Decision: `POST /api-keys` вызывает `assert_within_limit(user, Resource.API_ACCESS)` (reuse `billing/limits.py`) → `PlanLimitExceeded`→`403`/`402` на Free/Pro; Team проходит. НЕ катать свою проверку плана.
- Q: Авторизация программная — как? → A: новый header-backend → Decision: `X-API-Key`-зависимость/backend, параллельно cookie/JWT: резолвит user по `key_hash`, проверяет `revoked_at IS NULL`, обновляет `last_used_at`. Применяется к read-эндпоинтам (alerts/watchlists) — те же сервисы, тот же tenant-scope (user_id из ключа). Мутации/billing — НЕ через API-ключ (только чтение, минимум поверхности).
- Q: Какие эндпоинты доступны ключом? → A: «read-эндпоинты» из контекста → Decision: alerts (`GET /alerts`, `GET /alerts/{id}`) и watchlists (read). НЕ открывать ключом billing/account/мутации (защита). Зависимость, принимающая cookie-user ИЛИ api-key-user, навешивается на read-роуты.
- Q: Rate-limit для ключей? → A: `api/rate_limit.py` keying → Decision: при доступе по ключу — keying по принципалу api-key (напр. `apikey:<key_id>` или `user_id`), а не по IP; чтобы лимит был per-ключ/per-tenant. Reuse существующего keying-механизма, добавить ветку api-key.
- Q: Revoke — hard delete? → A: аудит → Decision: soft (`revoked_at`), ключ перестаёт резолвиться; запись остаётся для аудита (`last_used_at`). Опц. периодическая чистка — вне скоупа.

## Scope
> **backend**: модель+миграция `api_keys`, эндпоинты issue/list/revoke (feature-gated Team, за `current_user`), `X-API-Key` auth-backend для read-эндпоинтов, rate-limit keying по ключу. Read-сервисы (alerts/watchlists) и billing feature-gate (`assert_within_limit`) — потребляем, не переписываем. Security 5.5 обязательна.

- **Touch ONLY (создать/изменить):**
  - `backend/src/storage/models/api_keys.py` — **новая** ORM-модель `ApiKey` (`id`, `user_id` FK, `key_hash`, `name`, `prefix`, `created_at`, `last_used_at`, `revoked_at`); индекс по `prefix`/`key_hash`.
  - `backend/alembic/versions/*` — **новая** миграция (таблица `api_keys`).
  - `backend/src/api/api_keys/__init__.py`, `router.py` — **новый** `APIRouter(prefix="/api-keys")`: `POST /api-keys` (issue, feature-gate `API_ACCESS`, plaintext один раз), `GET /api-keys` (list маскированно), `DELETE /api-keys/{id}` (revoke); за `Depends(current_user)`, tenant-scoped.
  - `backend/src/api/api_keys/schemas.py` — Pydantic `ApiKeyCreate` (name), `ApiKeyCreated` (plaintext — только в ответе создания), `ApiKeyRead` (маскированно: prefix/name/timestamps, без ключа).
  - `backend/src/api/api_keys/service.py` — генерация (`secrets.token_urlsafe`), хэширование (SHA-256), хранение хэша/префикса, list/revoke, `verify`/resolve по `key_hash` (constant-time) + `last_used_at`-update.
  - `backend/src/api/auth/api_key.py` — **новый**: `X-API-Key` dependency/backend (резолвит user по ключу, отклоняет revoked); комбинированная зависимость `current_user_or_api_key` для read-роутов.
  - `backend/src/api/alerts/router.py`, `backend/src/api/watchlist/router.py` — **read-роуты** принимают cookie-user ИЛИ api-key-user (заменить/расширить зависимость на `current_user_or_api_key`); мутации/прочее — без изменений.
  - `backend/src/api/rate_limit.py` — keying-ветка: при api-key-принципале лимитировать по `apikey:<id>`/user, не IP.
  - `backend/src/api/main.py` — `include_router(api_keys.router)`.
  - `backend/src/billing/constants.py` или `api/api_keys/constants.py` — `API_KEY_PREFIX="tp_"`, длина токена, prefix-length (no magic literals).
  - `backend/tests/unit/test_api_keys.py` — генерация/хэш (no plaintext), constant-time resolve, revoke, маскирование.
  - `backend/tests/integration/test_api_keys_api.py` — issue (Team) / `403` (Free/Pro) / list маскированно / revoke / `X-API-Key` на `GET /alerts` / revoked→`401`.
  - `docs/tasks/tasks-index.md` — на ship (НЕ в этой задаче-планировании).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/billing/limits.py`/`plans.py` (feature-gate `assert_within_limit`/`API_ACCESS` — reuse, не переписываем), `backend/src/api/auth/backend.py` (cookie/JWT-механика task-003 — не ломаем, добавляем параллельный backend), read-**сервисы** alerts/watchlists (только меняем зависимость авторизации на роуте, не логику чтения). Не давать API-ключом доступ к мутациям/billing/account. Не хранить plaintext.
- **Blast radius:** новая таблица `api_keys` (Alembic, additive) + новый prefix-роутер + новый auth-путь (`X-API-Key`) параллельно cookie/JWT. Read-роуты (alerts/watchlists) получают вторую авторизацию (cookie ИЛИ api-key) — нужно не сломать cookie-флоу (UI). Rate-limit keying расширяется. **Security-чувствительно** (выпуск/хранение/проверка секретов, feature-gate, поверхность доступа) → стадия 5.5 обязательна.

## Acceptance Criteria
- [ ] **AC1 — Team создаёт ключ, plaintext один раз (failing-test anchor).** Given Team-пользователь, When `POST /api-keys`, Then `201` + plaintext-ключ в ответе РОВНО один раз; в БД — только `key_hash`+`prefix` (plaintext нигде не сохранён). Тест пишется ПЕРВЫМ (RED).
- [ ] **AC2 — feature-gate Free/Pro → 403.** Given Free или Pro пользователь, When `POST /api-keys`, Then `403`/`402` (feature `API_ACCESS` не на плане, через `assert_within_limit`); ключ не создан.
- [ ] **AC3 — аутентификация по `X-API-Key`.** Given валидный ключ, When `GET /alerts` с заголовком `X-API-Key: <plaintext>` (без cookie), Then `200` + только данные владельца ключа (tenant-scope = user ключа); `last_used_at` обновлён.
- [ ] **AC4 — list маскированно + revoke.** Given пользователь с ключами, When `GET /api-keys`, Then список без полного ключа (prefix/name/timestamps); When `DELETE /api-keys/{id}`, Then `revoked_at` проставлен и этот ключ больше не аутентифицирует (`X-API-Key` им → `401`).
- [ ] **AC5 — хэширование + constant-time (security).** Given ключ at-rest, When инспекция БД, Then хранится только `key_hash` (необратимый), не plaintext; resolve по ключу — constant-time compare (`secrets.compare_digest`), нет early-return по префиксу-таймингу, раскрывающего валидность.
- [ ] **AC6 — поверхность ограничена read.** Given API-ключ, When попытка мутации/billing/account-эндпоинта с `X-API-Key`, Then доступ НЕ предоставлен (ключ авторизует только read alerts/watchlists); cookie/JWT-флоу UI не сломан (по-прежнему работает).
- [ ] **AC7 — rate-limit + поведенческая (G2) через стек.** Given доступ по ключу, When серия запросов, Then rate-limit keyed по api-key-принципалу (не IP); и: `make up` → реальный запрос `GET /alerts` с `X-API-Key` за nginx → `200`; Free/Pro create→`403`; revoke→`401`; артефакты сохранены. Security 5.5: no plaintext at-rest, constant-time, feature-gate.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-028-api-keys-team`.
1. **RED:** `test_api_keys_api.py` — Team `POST /api-keys`→201+plaintext один раз; Free/Pro→`403`. Падает (роута/таблицы нет). AC1/AC2-якорь.
2. Модель `ApiKey` + Alembic-миграция; `service.py` (gen `token_urlsafe`, SHA-256 хэш, prefix, resolve constant-time, revoke).
3. Роутер `api_keys` (issue feature-gate `assert_within_limit(API_ACCESS)`, list маскированно, revoke) + схемы (plaintext только в `ApiKeyCreated`); `include_router`. `make ci-fast` зелёный.
4. `X-API-Key` backend (`api/auth/api_key.py`) + `current_user_or_api_key`; навесить на read-роуты alerts/watchlists; rate-limit keying-ветка.
5. `test_api_keys.py` unit (хэш/no-plaintext/constant-time/маскирование) + integration AC3/AC4/AC6. **GREEN** локально.
6. **G2 + security:** `make up`; `GET /alerts` с `X-API-Key`→200 за nginx, Free/Pro create→403, revoke→401 (AC7); **5.5**: no plaintext at-rest (инспекция БД), constant-time compare, feature-gate серверный, поверхность только read, cookie-флоу не сломан.
7. Обновить `tasks-index.md` на ship.

## Invariants
- **No plaintext at-rest** — в БД только `key_hash` (необратимый) + `prefix`; plaintext возвращается РОВНО один раз при создании, нигде не логируется/не сохраняется.
- **Constant-time resolve** — сравнение ключа через `secrets.compare_digest`; prefix-индекс только сужает выборку, финальная проверка constant-time; нет тайминг-утечки валидности.
- **Feature-gate серверный (reuse)** — issue гейтится `assert_within_limit(Resource.API_ACCESS)` (`billing/limits.py`); Free/Pro→`403`/`402`; не катаем свою проверку плана.
- **Tenant-scoped** — ключ привязан к `user_id`; доступ по ключу = tenant-scope владельца (`GET /alerts` отдаёт только его данные); list/revoke — только свои ключи (`404`/`403` на чужой id).
- **Поверхность только read** — API-ключ авторизует чтение (alerts/watchlists), НЕ мутации/billing/account; минимизация ущерба при утечке ключа.
- **Cookie/JWT не сломан** — `X-API-Key` — параллельный backend; UI cookie-флоу (task-003/014) продолжает работать на read-роутах без изменений поведения.
- **No magic literals** — префикс/длина токена/prefix-length — named constants; rate-limit-параметры из settings; full type hints, Pydantic на границе; revoke — soft (`revoked_at`).

## Edge cases
- Утечка/попытка повтора показа plaintext → ключ показывается ровно один раз; забыл → создать новый, старый revoke (нет «восстановления» plaintext).
- `X-API-Key` неизвестный/подделанный → `401` (constant-time, без раскрытия «префикс есть, хэш нет»).
- Revoked-ключ (`revoked_at` set) → `401`, `last_used_at` не обновляется; не резолвится.
- Коллизия prefix у разных ключей → финальный resolve по `key_hash` (compare_digest), prefix только сужает; неоднозначность не аутентифицирует чужого.
- Одновременно cookie И `X-API-Key` в запросе → определить приоритет (напр. cookie-first или явный); не «смешивать» личности; tenant-scope консистентен.
- Free/Pro с ранее выпущенным (на Team) ключом после даунгрейда → доступ по ключу для read можно оставить или гейтить на effective-план (решение исполнителя; безопаснее — gate resolve на текущий `effective_plan` API_ACCESS). Документировать.
- Попытка мутации/billing с `X-API-Key` → не авторизовано (AC6); ключ не «прокидывается» на не-read роуты.
- Rate-limit: всплеск по одному ключу не должен бить лимит другого tenant (keying per ключ/user, не общий IP за nginx).

## Test plan
- **unit:** `test_api_keys.py` — генерация (энтропия/формат `tp_`), хэширование (no plaintext в хранимом), resolve constant-time (валид/невалид/revoked), маскирование (`ApiKeyRead` без ключа), revoke soft.
- **integration:** `test_api_keys_api.py` — AC1 (Team issue→201+plaintext один раз, БД только hash, RED-якорь), AC2 (Free/Pro→403), AC3 (`X-API-Key`→`GET /alerts` 200 tenant-scoped, last_used_at), AC4 (list маскированно, revoke→401), AC6 (мутация/billing с ключом не авторизована; cookie-флоу жив).
- **runtime/behavioral (G2):** `make up` → `GET /alerts` с `X-API-Key` за nginx→200; Free/Pro create→403; revoke→401; rate-limit keyed по ключу (серия запросов).
- **security (5.5):** no plaintext at-rest (инспекция БД/логов); constant-time compare (нет тайминг-утечки); feature-gate серверный; поверхность только read; ключ не в логах; cookie/JWT не сломан.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-028-api-keys-team"
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
(initial — план по эталону task-016/017 и контексту Epic D: Team-план продаёт API access (Resource.API_ACCESS/_TEAM_API в plans.py), механизма нет. Таблица `api_keys` (хранить только key_hash+prefix, plaintext один раз при создании; Alembic), эндпоинты issue/list/revoke за current_user (issue feature-gated через reuse `assert_within_limit(API_ACCESS)`→403 на Free/Pro), `X-API-Key` auth-backend резолвит user по key_hash constant-time для read-эндпоинтов (alerts/watchlists), rate-limit keying по api-key-принципалу (api/rate_limit.py). Read-сервисы и feature-gate не переписываем. deps: 003 (auth/fastapi-users), 010 (billing/plans/limits). Security 5.5 ОБЯЗАТЕЛЬНА: хэширование (no plaintext at-rest), constant-time compare, feature-gate серверный, поверхность только read. locate+plan выполнены этим планированием — executor стартует с «3 do».)

### Подсказки исполнителю (initial)
- **Генерация:** `secret = secrets.token_urlsafe(32)`; `plaintext = f"{API_KEY_PREFIX}{prefix}_{secret}"` (или `tp_<random>`); `prefix` = первые N символов (named const) — хранить для отображения/narrow-lookup; `key_hash = hashlib.sha256(plaintext.encode()).hexdigest()`.
- **Resolve (`api/auth/api_key.py`):** прочитать `X-API-Key` header → вычислить sha256 → найти по `key_hash` (опц. сначала narrow по `prefix`) → проверить `revoked_at IS NULL` → `secrets.compare_digest(stored_hash, computed_hash)` (constant-time) → вернуть user; обновить `last_used_at`. Неизвестный/revoked → `401` (generic, без раскрытия).
- **feature-gate:** `POST /api-keys` — `assert_within_limit(user, Resource.API_ACCESS)` из `billing/limits.py` (reuse) ДО создания; `PlanLimitExceeded` уже маппится в handler (`api/main.py`).
- **комбинированная авторизация:** `current_user_or_api_key` — попробовать cookie/JWT `current_user`, иначе `X-API-Key`; навесить на read-роуты alerts/watchlists `Depends(current_user_or_api_key)`. НЕ навешивать на мутации/billing/account.
- **rate_limit:** в `api/rate_limit.py` key-функция — если запрос аутентифицирован api-key, ключ `f"apikey:{key_id}"` (или user_id), иначе текущее (user/IP).
- **схемы:** `ApiKeyCreated` (поле `key: str` — plaintext, ТОЛЬКО ответ POST), `ApiKeyRead` (`id`,`name`,`prefix`,`created_at`,`last_used_at`,`revoked_at` — БЕЗ `key`/`key_hash`), `extra=forbid`.
- **миграция:** таблица `api_keys` с FK `user_id`→users, index(`prefix`), unique(`key_hash`); `revoked_at` nullable.
- **downgrade-кейс:** рассмотреть gate resolve на `effective_plan` API_ACCESS (после даунгрейда ключ не работает) — безопаснее; задокументировать выбор в Details при реализации.
- **security G2:** инспекция таблицы `api_keys` — нет plaintext; логи — нет ключа; constant-time подтверждён; cookie-флоу UI на `GET /alerts` по-прежнему 200.
