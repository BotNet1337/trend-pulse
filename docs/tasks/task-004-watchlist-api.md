---
id: TASK-004
title: Watchlist CRUD API — каналы, топики, alert-config (tenant-scoped, plan-limit seam)
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "bb8b74ca609aa2a22c71d395c3f6bf3908d03db6"
branch: "gsd/phase-004-watchlist-api"
tags: [backend, api, fastapi, pydantic, watchlist, multi-tenancy]
---

# TASK-004 — Watchlist CRUD API (каналы · топики · alert-config)

> Дать пользователю REST-API для управления watchlist'ами: создать/прочитать/обновить/удалить набор каналов + топик + alert-config (порог score, минимум каналов, язык уведомлений). Всё за `current_user` (task-003), изолировано по `user_id` (ADR-002), каналы как `SourceRef{kind,handle}` (ADR-001), с seam'ом под лимиты тарифа (полный enforcement — task-010).

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon. Эта задача — часть Epic A (Backend core), шаг 4 по [roadmap](../architecture/roadmap.md): watchlist CRUD после auth (task-003) поверх data model (task-002).

Watchlist (overview §3, шаги 2–3 user journey) = набор публичных каналов + выбранный топик + настройка алертов (порог score, минимум каналов, язык уведомлений). Это пользовательская сущность: изолируется по `user_id` ([ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md)), каналы хранятся как `SourceRef{kind,handle}` с `kind` по умолчанию `telegram` ([ADR-001](../architecture/adr-001-source-abstraction.md)) — schema готова к мульти-источнику. API — единственная точка входа для будущего frontend (эпик C, C3 → этот API).

Зависит от: **task-002** (таблицы `watchlists`/`channels`/junction, FK→`users`, индексы по `user_id`, поле `source_kind`), **task-003** (`current_user` dependency, JWT). Реальная валидация `@handle` через коллектор — **task-005**; здесь принимаем format-validation и оставляем seam под `validate_ref`.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — Pydantic на границе, full type hints, no magic literals, SQLAlchemy bind-params, cross-module через service-функции, репозитории принимают `user_id` обязательным.

## Goal

Аутентифицированный пользователь через REST может: создать watchlist (каналы + топик + alert-config) → `201` со строкой, несущей его `user_id`; получить список **только своих** watchlist'ов; обновить/удалить **только свои** (чужой id → 404); невалидный `@handle` отклоняется на границе (`422`); превышение лимита каналов/топиков тарифа отклоняется (`402/403`) через единый limits-seam. Все эндпоинты — за `current_user`, tenant-scoped по `user_id`. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по дефолтам ADR/overview; обратимы. -->
- Q: Что именно есть watchlist? → A: overview §3 → Decision: сущность `Watchlist{topic, channels: list[SourceRef], alert_config{score_threshold, min_channels, notification_lang}}`, привязана к `user_id`. Каналы — junction к глобальной `channels` (ADR-002 §3), хранят `source_kind` (default `telegram`, ADR-001).
- Q: Как ссылаться на канал? → A: **`SourceRef{kind,handle}`** (ADR-001) → Decision: request-модель принимает `handle` (+ опц. `kind`, default `telegram`); внутри маппится в `SourceRef`. Schema мульти-источниковая с первого дня — не привязываемся к Telegram в API-контрактах.
- Q: Валидация handle сейчас, без коллектора? → A: collector (`validate_ref`) — task-005 → Decision: **format-validation сейчас** (regex `@[A-Za-z0-9_]{4,32}` для telegram-handle) + **seam** `validate_ref` (вызов реального коллектора, если зарегистрирован в `collector/registry`; иначе stub-tolerant — принимаем формат). Реальная сетевая проверка существования канала — task-005 (rationale: не блокируем CRUD на коллекторе; контракт уже на месте).
- Q: Изоляция тенанта? → A: ADR-002 §1 → Decision: репозиторий принимает `user_id` обязательным; **нет** «глобальных» выборок; update/delete фильтруют по `(id, user_id)` — чужой id неотличим от несуществующего → `404` (не утечка существования). Где нужен явный «не твой» сигнал авторизации — `403`; дефолт для CRUD-by-id — `404`.
- Q: Лимиты тарифа (каналов/топиков)? → A: enforcement — task-010 (billing) → Decision: **seam сейчас** — `limits.check_watchlist_limits(user_id, …)` с базовой проверкой по дефолтному плану (Free: 5 каналов / 1 топик, overview §6); полный учёт плана/счётчиков — task-010. Превышение → `402 Payment Required` (или `403`, см. Edge cases) (rationale: контракт лимитов закрепляем сразу, чтобы frontend и billing не переделывали API).
- Q: Язык уведомлений? → A: overview §3 (язык уведомлений) → Decision: `notification_lang` — ISO-639-1 (`en`/`ru`/…), валидируется Pydantic-ом; дефолт из настроек, не magic literal.

## Scope
> Затрагивает **только `backend/`**, модуль `api/watchlist/`. Не трогает коллектор/pipeline/scorer/billing-реализацию — только seam'ы к ним.

- **Touch ONLY (создать/изменить):**
  - `backend/src/trendpulse/api/watchlist/__init__.py` — экспорт router'а.
  - `backend/src/trendpulse/api/watchlist/router.py` — FastAPI `APIRouter` (`prefix="/watchlists"`): `POST /` (create), `GET /` (list), `GET /{id}`, `PATCH /{id}` (update), `DELETE /{id}`; все за `Depends(current_user)`.
  - `backend/src/trendpulse/api/watchlist/schemas.py` — Pydantic request/response: `WatchlistCreate`, `WatchlistUpdate`, `WatchlistRead`, `ChannelRef` (handle+kind, format-validation), `AlertConfig` (`score_threshold`, `min_channels`, `notification_lang`).
  - `backend/src/trendpulse/api/watchlist/service.py` — domain-service (create/list/update/delete) поверх репозитория; tenant-scope по `user_id`; вызов `validate_ref` (seam) и `limits.check_watchlist_limits` (seam).
  - `backend/src/trendpulse/api/watchlist/limits.py` — seam плановых лимитов: `check_watchlist_limits(user_id, channels_count, topics_count)`; базовая проверка по дефолтному плану + точка расширения для task-010.
  - `backend/src/trendpulse/api/watchlist/refs.py` — маппинг `ChannelRef → SourceRef`, format-validation handle, stub-tolerant `validate_ref` (через `collector/registry` если есть, иначе формат).
  - `backend/src/trendpulse/api/main.py` — подключить `watchlist.router` к приложению (минимальное `include_router`).
  - `backend/tests/unit/test_watchlist_schemas.py`, `backend/tests/unit/test_watchlist_service.py`, `backend/tests/integration/test_watchlist_api.py` — TDD-якоря (AC1 = первый failing test).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`; реализацию `collector/**` (только seam через registry), `pipeline/**`, `scorer/**`, `alerts/**`, `billing/**` (только seam `limits.py`), `storage/**` модели/миграции (берём как есть из task-002). Никакой бизнес-логики коллектора/scoring — только CRUD + seam'ы.
- **Blast radius:** новые HTTP-контракты watchlist — потребители: frontend (эпик C, C3), task-005 (читает объединённый набор `SourceRef` из watchlist'ов), task-006/008 (per-user батч/scorer берут топик+порог из watchlist), task-010 (billing наполняет реальный limits-seam). Repo-слой и схема — из task-002, не меняются.

## Acceptance Criteria
- [ ] **AC1 — create → 201 + user_id (failing-test anchor).** Given аутентифицированный пользователь и валидный payload (каналы + топик + alert-config), When `POST /watchlists`, Then `201` и тело `WatchlistRead` с `id` и `user_id == current_user.id`; в БД строка с этим `user_id`. (Пишется ПЕРВЫМ, RED.)
- [ ] **AC2 — list возвращает только свои.** Given две watchlist'а у разных пользователей, When user A делает `GET /watchlists`, Then в ответе только watchlist'ы user A (чужие не видны).
- [ ] **AC3 — update/delete enforce ownership.** Given watchlist принадлежит user B, When user A делает `PATCH`/`DELETE /watchlists/{id_B}`, Then `404` (id чужого тенанта неотличим от несуществующего); свой id — `200`/`204`.
- [ ] **AC4 — невалидный handle → 422.** Given payload с `@bad handle!` (нарушает формат), When `POST`/`PATCH`, Then `422` с понятной ошибкой валидации на границе (Pydantic), строка в БД не создаётся.
- [ ] **AC5 — превышение лимита каналов → 402/403.** Given дефолтный план (5 каналов), When `POST` с 6+ каналами, Then `402` (Payment Required) с сообщением о лимите; строка не создаётся. (Seam `limits.check_watchlist_limits`; полный учёт плана — task-010.)
- [ ] **AC6 — `SourceRef` мульти-источниковость.** Given payload без `kind`, When create, Then канал сохраняется с `source_kind == "telegram"` (default); явный `kind="telegram"` эквивалентен.
- [ ] **AC7 — auth-guard.** Given запрос без валидного JWT, When любой `/watchlists`-эндпоинт, Then `401` (за `Depends(current_user)`), бизнес-логика не выполняется.

## Plan
1. **RED:** `tests/integration/test_watchlist_api.py::test_create_returns_201_with_user_id` — TestClient + override `current_user` → `POST /watchlists` валидный payload → ожидаем `201` + `user_id`. Запустить — падает (router'а нет). Это AC1-якорь.
2. `api/watchlist/schemas.py` — `ChannelRef` (`handle: str` с `field_validator`/`pattern` под telegram-handle; `kind: SourceKind = TELEGRAM`), `AlertConfig` (`score_threshold: int` 0..100, `min_channels: int ≥ 1`, `notification_lang: str` ISO-639-1), `WatchlistCreate`/`WatchlistUpdate` (partial)/`WatchlistRead` (`id`, `user_id`, `topic`, `channels`, `alert_config`). Лимиты/диапазоны — именованные константы/config, не magic literals.
3. `api/watchlist/refs.py` — `to_source_ref(ChannelRef) -> SourceRef`; `validate_ref(ref) -> bool` (если `collector/registry` есть и содержит `kind` — делегировать; иначе format-only, stub-tolerant). Формат — именованная regex-константа.
4. `api/watchlist/limits.py` — `check_watchlist_limits(user_id, *, channels_count, topics_count) -> None` (raise `LimitExceededError` при превышении дефолтного плана); дефолты из config (Free: 5/1). Точка расширения для task-010 помечена комментарием.
5. `api/watchlist/service.py` — `create/list_for_user/get/update/delete`, каждый принимает `user_id` обязательным; вызывает `validate_ref` (→ `422` через domain-error/HTTPException на роутере) и `check_watchlist_limits` (→ `402`); читает/пишет через репозиторий task-002 (фильтр по `(id, user_id)`); get/update/delete по чужому id → `None`/raise → роутер отдаёт `404`.
6. `api/watchlist/router.py` — `APIRouter(prefix="/watchlists", tags=["watchlist"])`, все хендлеры `Depends(current_user)`; мапит domain-errors → HTTP-коды (`LimitExceededError→402`, `ValidationError→422`, not-found→404). Возвращает `WatchlistRead`/`204`.
7. `api/main.py` — `app.include_router(watchlist.router)`.
8. **GREEN:** прогнать `make ci-fast`; добить unit (`test_watchlist_schemas`, `test_watchlist_service`) и integration (AC2–AC7) до зелёного.
9. **G2 behavioral:** поднять стек (`make build && up-d`), реальным curl с auth-токеном (получить через task-003 login) пройти create→list→update→delete + negative (чужой id, bad handle, over-limit).
10. Обновить `tasks-index.md` на ship.

## Invariants
- **Tenant-scope обязателен.** Репозиторий/сервис принимают `user_id` обязательным параметром; нет глобальных выборок пользовательских данных; CRUD-by-id фильтруется по `(id, user_id)` (ADR-002 §1).
- **Чужой id → 404, не 403/200.** Существование чужой строки не утекает; явный `403` — только где требуется отличить authz от not-found.
- **Pydantic валидирует на границе** — `@handle`, диапазоны порога/min_channels, ISO-язык; внешние данные не доверяются (CONVENTIONS).
- **`SourceRef` с `kind` (default `telegram`)** — API-контракт мульти-источниковый, не привязан к Telegram (ADR-001); хранится `source_kind`.
- **Seam'ы, не реализации.** `validate_ref` (real → task-005) и `check_watchlist_limits` (real → task-010) — изолированные точки; сейчас stub-tolerant/базовая проверка, контракт не меняется при доведении.
- **Cross-module через service-функции** — `api/watchlist` не лезет во внутренности `collector`/`billing`/`storage`, только публичные функции/registry.
- **No magic literals** — лимиты, диапазоны, regex, дефолтный язык — в config/именованных константах. SQL — через SQLAlchemy bind-params (репозиторий task-002), никаких f-string SQL.
- **Full type hints, no bare `Any`, no `# type: ignore`** — `mypy` зелёный.

## Edge cases
- Дубликат канала в одном watchlist'е → дедуп до сохранения (set по `(kind,handle)`), не падать.
- Пустой список каналов или пустой топик → `422` (минимум 1 канал, непустой topic).
- `min_channels` > числа каналов в watchlist'е → `422` (логически невозможный алерт).
- `score_threshold` вне 0..100 / отрицательный `min_channels` → `422`.
- Невалидный `notification_lang` (не ISO-639-1) → `422`.
- Превышение лимита: спорный код — `402 Payment Required` (нужна оплата плана) vs `403 Forbidden` (нет прав). Дефолт — `402` (монетизация, overview §6); зафиксировать и не дрейфовать. task-010 может уточнить.
- Update частичный (`PATCH`) — не сбрасывать неуказанные поля; partial-модель с `exclude_unset`.
- Гонка: одновременные `POST` на грани лимита — базовый seam не атомарен; отметить как known-limitation, атомарный учёт — task-010.
- `collector/registry` ещё нет (task-005) → `validate_ref` stub-tolerant (format-only), не падать на отсутствии коллектора.
- Каналы дедуплицируются глобально (ADR-002 §3): создание watchlist'а не дублирует строку `channels`, только junction — брать существующий `channel` или создавать (репозиторий task-002).

## Test plan
- **unit:** `test_watchlist_schemas.py` — валидация `ChannelRef`/`AlertConfig`/`WatchlistCreate` (good/bad handle, диапазоны, ISO-язык, default `kind`); `test_watchlist_service.py` — tenant-scope (чужой id → not-found), limits-seam (raise при превышении), dedup каналов, `validate_ref` stub-tolerant. Мок репозитория/коллектора.
- **integration:** `test_watchlist_api.py` — TestClient + override `current_user` + тестовая БД: AC1 (create 201 + user_id, RED-якорь), AC2 (list only own), AC3 (update/delete чужого → 404, своего → 200/204), AC4 (bad handle → 422), AC5 (over-limit → 402), AC6 (default kind telegram), AC7 (no JWT → 401). Маркер `integration`.
- **runtime/behavioral (G2):** `make build && make up-d` → получить JWT через task-003 login → реальный `curl -H "Authorization: Bearer <token>"`: create→list→get→patch→delete + negative (чужой id 404, bad handle 422, over-limit 402, без токена 401).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "bb8b74ca609aa2a22c71d395c3f6bf3908d03db6"
branch: "gsd/phase-004-watchlist-api"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — PASS, 0 blocking)
- [x] 5.5 security (PASS, 0 blocking — BOLA/IDOR mitigated; tenant-scope verified)
- [x] 6 ship (PR #5, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []   # no debug cycles — verify/review/security passed first time

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по эталону task-001 и docs/architecture; зависит от task-002 (schema/repo) и task-003 (current_user); seam'ы `validate_ref`→task-005, `check_watchlist_limits`→task-010)

### USER DECISION (override task-doc multi-channel contract)
Пользователь выбрал **«одна junction-строка = один watchlist»** (адресуется числовым `id`, один канал на watchlist; несколько каналов = несколько отдельных watchlists). Соответственно: `WatchlistCreate{topic, channel: ChannelRef, alert_config}` (singular channel) → `POST` создаёт одну строку → один `WatchlistRead{id,user_id,topic,channel,alert_config}`; лимит плана (AC5) = макс. число watchlist'ов на пользователя (Free=5); `min_channels` — параметр скоринга, не число каналов watchlist'а.

### Step 3 do · 4 verify · loop-20260608-202131 · PASS (0 debug)
- **do (TDD, FLAT layout):** `api/watchlist/` (schemas/refs/limits/exceptions/service/deps/router) + include в `api/main.py`. RED: AC1-якорь `test_create_returns_201_with_user_id` → ModuleNotFoundError; GREEN после реализации. sync-роуты (FastAPI threadpool) + sync session над репозиториями task-002; tenant-scope `(id,user_id)`; чужой/несущ. id → 404; дубликат `(user_id,channel_id,topic)` → IntegrityError→rollback→409; seam'ы `validate_ref` (stub-tolerant, collector→task-005), `check_watchlist_limits` (Free=5, billing→task-010); все литералы — именованные константы; Pydantic `extra=forbid`, anchored handle-regex. `make ci-fast` зелёный (mypy strict 38 файлов; 44 unit).
- **verify (G2):** integration 16/16 против реальной pgvector (+добавлен тест duplicate→409 по замечанию review → 8 watchlist-тестов); **behavioral curl через nginx с JWT-cookie:** no-auth 401, create 201 (kind=telegram default), list own, bad-handle 422, 5 ok→6-й 402, patch own 200 / чужой 404, delete 204 / повтор 404. migration_runner exit 0.

### Step 5 review (opus) PASS 0 blocking · Step 5.5 security (opus) PASS 0 blocking
- **review:** tenant-isolation корректна; auth на всех роутах; Pydantic boundary; seam'ы не лезут во внутренности; sync session lifecycle ок; PATCH `exclude_unset`. Non-blocking: добавлен недостающий 409-тест (MED, исправлено); TOCTOU лимита (LOW→task-010); `len(list())` count (LOW→task-010); `# type: ignore` на collector-seam (INFO, узко-обоснован, уйдёт в task-005).
- **security:** BOLA/IDOR **полностью закрыт** — нет пути выборки/мутации по id без `user_id`-фильтра (`UserScopedRepository` не наследует глобальный get_by_id); tenant из токена, не из тела; `extra=forbid` (нет mass-assignment id/user_id); 404 без утечки существования; bind-params SQL; regex anchored (no ReDoS). Non-blocking: TOCTOU/пагинация→task-010; SSRF-нота для collector→task-005. Нечего ротировать.

### Step 6 ship · PR #5 (squash-merged). Step 7 learnings · docs/learnings.md (TASK-004).
