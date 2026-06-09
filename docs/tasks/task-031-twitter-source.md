---
id: TASK-031
title: Twitter/X source readiness — второй SourceCollector (ADR-001), регистрация, per-source лимиты, выбор источника
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-031-twitter-source"
tags: [epic-d, backend, collector, source-abstraction]
---

# TASK-031 — Twitter/X source readiness (Epic D)

> Реализовать **второй источник** по [ADR-001](../architecture/adr-001-source-abstraction.md) (source abstraction). (1) `backend/src/collector/twitter/` — реализация `SourceCollector` Protocol (Twitter API v2, OAuth2; маппинг метрик `likes`→`reactions` / `retweets`→`forwards` / `impressions`→`views` в `PostMetrics`, прочее в `extra`; `RawPost`). (2) Регистрация в `collector/registry.py` (`register(SourceKind.TWITTER, _build_twitter_collector)` — сейчас TWITTER объявлен в enum, но НЕ зарегистрирован). (3) Уточнить **лимиты по источникам** (`_FREE_CHANNELS` и т.д. — per-source или суммарно; решить + отразить в watchlist/billing; ADR-001 §schema). (4) Watchlist API/UI знают `source_kind` (default telegram) — добавить выбор источника при создании. **Ядро (pipeline/scorer/API) НЕ трогать** — платформо-независимо. Twitter API доступ — **внешняя зависимость** (мок/стаб API v2 в тестах). DoD — Acceptance Criteria ниже.

## Context

TrendPulse — [ADR-001](../architecture/adr-001-source-abstraction.md): source-abstraction готова под мульти-источник. Ядро в `backend/src/collector/base.py` (SDK-free):
- `SourceKind(StrEnum)` — `TELEGRAM = "telegram"`, `TWITTER = "twitter"` (комментарий: «future marker — declared, not implemented (ADR-001 scope guard)»).
- `SourceRef(kind, handle)`, `PostMetrics(views, forwards, reactions, extra: Mapping[str,int])`, `RawPost(source, external_id, author, text, media_hashes, metrics, posted_at)`.
- `SourceCollector(Protocol)` (`@runtime_checkable`): атрибут `kind: SourceKind`; `async validate_ref(ref) -> bool`; `read(refs, since) -> AsyncIterator[RawPost]`. Rate-limit/backoff/rotation — **внутри** реализации, не в интерфейсе.

`collector/registry.py` — lazy in-code mapping `SourceKind→factory`: `register/is_registered/get`; `register(SourceKind.TELEGRAM, _build_telegram_collector)` зарегистрирован; **TWITTER намеренно отсутствует** (AC7 task-005). `collector/telegram/` — эталон реализации (`reader.py::TelegramCollector`, `client.py`, `account_pool.py`, `mapper.py`, `dedup.py`).

Pipeline/scorer зависят ТОЛЬКО от `RawPost`/`PostMetrics` (платформо-независимо — `base.py` docstring: «Adding a source means a new SourceCollector implementation — these contracts do not change»). `Channel.source_kind` default telegram.

Лимиты: `backend/src/billing/plans.py` — `Resource.CHANNELS`, `PLAN_LIMITS[plan][CHANNELS]` (`_FREE_CHANNELS=5`/`_PRO=100`/`_TEAM=500`); `billing/limits.py::assert_within_limit` считает usage по storage-репам. **Сейчас лимит суммарный по каналам, без разбивки по источнику.**

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, Pydantic на границе, no magic literals, секреты (Twitter API keys/OAuth) только из env. **Ядро SDK-free — `base.py` НЕ импортирует platform SDK.**

## Goal

После задачи: `collector/twitter/` реализует `SourceCollector` Protocol (Twitter API v2, OAuth2; метрики маппятся в `PostMetrics`; `RawPost` нормализован, `posted_at` tz-aware UTC, `external_id` dedup); `register(SourceKind.TWITTER, ...)` в registry — `is_registered(TWITTER)` теперь True, `get(TWITTER)` строит collector лениво; лимиты по источникам определены (per-source ИЛИ суммарно — решено + зафиксировано в ADR-001 §schema, отражено в watchlist/billing); watchlist можно создать с `source_kind=twitter` и он собирается (integration с замоканным API v2); pipeline/scorer/API не тронуты. Twitter API доступ — внешняя зависимость (тесты на моке/стабе). Security: OAuth-токены/ключи из env (не в коде); Twitter rate-limit/FLOOD-эквивалент инкапсулирован внутри collector. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Решения по ADR-001 + plans.py; ADR-001 §schema может дополняться. -->
- Q: Структура twitter-collector? → A: зеркалит telegram → Decision: `collector/twitter/` = `reader.py` (`TwitterCollector(SourceCollector)`), `client.py` (API v2 HTTP-клиент + OAuth2 bearer), `mapper.py` (Twitter-tweet → `RawPost`/`PostMetrics`); rate-limit/backoff внутри (как telegram FLOOD). Адаптируем паттерн telegram, не катаем новый.
- Q: Маппинг метрик Twitter→PostMetrics? → A: общая тройка + extra → Decision: `public_metrics.like_count`→`reactions`, `retweet_count`→`forwards`, `impression_count`(или `view_count`)→`views`; `reply_count`/`quote_count`/`bookmark_count`→`extra` (named ints). Всегда int, не None (контракт PostMetrics).
- Q: Twitter API доступ для тестов? → A: внешняя зависимость → Decision: тесты гоняют против **замоканного API v2** (httpx-mock/respx или fake-клиент); реальный Twitter не дёргаем в CI. Реальный ключ — отдельный долг (live-verify). Помечаем как внешнюю зависимость (может отсутствовать).
- Q: Лимиты per-source или суммарно? → A: **решить + ADR-001** → Decision: **per-source** предпочтительно (Free: 5 telegram-каналов независимо от twitter-источников), т.к. источники разной природы/стоимости сбора. Зафиксировать в ADR-001 §schema: `Resource.CHANNELS` считается **per `source_kind`** ИЛИ оставить суммарным с явным обоснованием. Решение влияет на `billing/limits.py::assert_within_limit` usage-подсчёт (фильтр по source_kind). **Минимальный путь:** если per-source усложняет → оставить суммарный лимит, зафиксировать как осознанное решение в ADR-001 (избегаем over-engineering).
- Q: Выбор источника в watchlist? → A: `source_kind` уже на Channel → Decision: watchlist create-API принимает `source_kind` (default telegram, сохраняем backward-compat); валидация: `is_registered(source_kind)` → иначе 422/422-feature. UI добавляет селектор источника (telegram/twitter).
- Q: handle-формат Twitter? → A: `SourceRef.handle` → Decision: Twitter `handle` = username (`@acme` → `acme`) или hashtag/query (ADR-001 §schema уточнить); `validate_ref` проверяет читаемость публичного ref через API v2 (как telegram public-channel check).
- Q: Ядро? → A: НЕ трогать → Decision: `base.py`/pipeline/scorer/API остаются; добавление источника = новая реализация Protocol + регистрация (ровно как ADR-001 проектировал).

## Scope
> **backend collector** (`collector/twitter/` + registry-регистрация) + **billing/watchlist** (per-source лимиты решение + source_kind-валидация при создании) + **frontend** (селектор источника в watchlist-create) + **ADR-001 §schema** (лимиты/handle-формат). Ядро (`base.py`/pipeline/scorer) и telegram-collector НЕ трогаем.

- **Touch ONLY (создать/изменить):**
  - **Backend:**
    - `backend/src/collector/twitter/__init__.py`, `reader.py`, `client.py`, `mapper.py` — **новые**: `TwitterCollector` (реализует `SourceCollector`: `kind=TWITTER`, `validate_ref`, `read`), API v2 OAuth2-клиент, метрик-маппер.
    - `backend/src/collector/registry.py` — `_build_twitter_collector()` (lazy, ключи из `config.get_settings()`) + `register(SourceKind.TWITTER, _build_twitter_collector)`.
    - `backend/src/config.py` — Twitter API settings (`twitter_bearer_token`/OAuth2 client id/secret) — из env, optional (как `telegram_api_id` None-guard).
    - `backend/src/billing/plans.py` / `billing/limits.py` — **если решено per-source**: usage-подсчёт `CHANNELS` с фильтром по `source_kind`; иначе — без изменений + обоснование в ADR.
    - `backend/src/api/watchlist/schemas.py` / `router.py` / `service.py` — create принимает `source_kind` (default telegram), валидирует `is_registered`; tenant-scope не меняется.
    - `backend/tests/unit/collector/test_twitter_collector.py` — **новый**: `TwitterCollector` реализует Protocol (`isinstance`-check `@runtime_checkable`), маппинг метрик (мок API v2 tweet→RawPost/PostMetrics).
    - `backend/tests/integration/test_twitter_watchlist.py` — **новый**: watchlist с `source_kind=twitter` создаётся (registry знает TWITTER), сбор с замоканным API v2.
  - **Frontend:**
    - `frontend/src/features/watchlists/**` (create-форма) — селектор `source_kind` (telegram/twitter); `gen.types.ts` регенерировать если схема create изменилась.
    - `frontend/tests/unit/watchlists/**` — выбор источника.
  - **ADR:**
    - `docs/architecture/adr-001-source-abstraction.md` — §schema: лимиты per-source vs суммарно (решение), Twitter `handle`-формат, метрик-маппинг.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/collector/base.py` (ядро-контракт неизменен — ADR-001), `collector/telegram/**` (эталон, не трогаем), pipeline/scorer (`backend/src/pipeline/**`, scorer — платформо-независимы). Не катать plugin-loader/config-DSL (ADR-001 scope guard — только in-code register).
- **Blast radius:** добавляет второй источник в registry (`is_registered(TWITTER)` меняется на True — поведение `get(TWITTER)`); watchlist-create принимает новый `source_kind`; **возможно** меняет usage-подсчёт лимитов (если per-source — затрагивает billing C5). Pipeline/scorer не затронуты (контракт `RawPost` стабилен). Внешняя зависимость от Twitter API (тесты на моке — CI не зависит от реального ключа).

## Acceptance Criteria
- [ ] **AC1 — TwitterCollector реализует Protocol (failing-test anchor).** Given `collector/twitter/reader.py::TwitterCollector`, When `isinstance(collector, SourceCollector)` (`@runtime_checkable`) и вызовы, Then `kind==SourceKind.TWITTER`, `validate_ref`/`read` реализованы; unit с **замоканным API v2** проверяет маппинг tweet→`RawPost`. Пишется ПЕРВЫМ (RED — модуля нет).
- [ ] **AC2 — метрики маппятся в PostMetrics.** Given Twitter `public_metrics`, When маппер, Then `like_count→reactions`, `retweet_count→forwards`, `impression_count→views` (всегда int, не None); прочие (`reply/quote/bookmark`)→`extra`; `posted_at` tz-aware UTC, `external_id` стабилен (dedup).
- [ ] **AC3 — регистрация в registry.** Given `register(SourceKind.TWITTER, ...)`, When `is_registered(SourceKind.TWITTER)`, Then True (раньше False — task-005 AC7); `get(TWITTER)` лениво строит `TwitterCollector` (ключи из env, None-guard как telegram).
- [ ] **AC4 — watchlist с source_kind=twitter.** Given create-API, When создание watchlist с `source_kind=twitter`, Then принят (registry знает TWITTER), сбор идёт через `TwitterCollector` (integration с замоканным API v2); `source_kind=telegram` остаётся default (backward-compat).
- [ ] **AC5 — лимиты по источникам определены.** Given ADR-001 §schema, When инспекция, Then решение per-source-vs-суммарно зафиксировано; `billing/limits.py` реализует выбранную стратегию (per-source фильтр ИЛИ суммарно с обоснованием); no magic literals (из `plans.py`).
- [ ] **AC6 — ядро не тронуто.** Given дифф, When инспекция, Then `collector/base.py` (контракт) и pipeline/scorer не изменены; добавление источника = новая реализация Protocol + регистрация (ADR-001 соблюдён); `base.py` остаётся SDK-free (twitter-SDK только в `collector/twitter/`).
- [ ] **AC7 — security + поведенческая (G2).** Given Twitter API ключи/OAuth-токены, When инспекция, Then из env (не в коде/логах); rate-limit/backoff инкапсулирован внутри collector (не в интерфейсе); и: `make up`/`make ci-fast` → unit (`test_twitter_collector`) + integration (`test_twitter_watchlist` с моком) зелёные; реальный Twitter не дёргается в CI (внешняя зависимость отмечена).

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-031-twitter-source`.
1. **ADR-001 §schema:** зафиксировать лимиты (per-source vs суммарно), Twitter `handle`-формат, метрик-маппинг. G1-решение.
2. **RED:** `test_twitter_collector.py` — `isinstance(collector, SourceCollector)` + маппинг метрик (мок API v2 tweet). Падает (модуля нет). AC1/AC2-якорь.
3. `collector/twitter/` — `mapper.py` (tweet→RawPost/PostMetrics), `client.py` (API v2 OAuth2, httpx; rate-limit/backoff внутри), `reader.py` (`TwitterCollector`); `config.py` Twitter settings (env, optional).
4. `collector/registry.py` — `_build_twitter_collector` + `register(SourceKind.TWITTER, ...)`. AC3.
5. Watchlist create-API — `source_kind` (default telegram, валидация `is_registered`); billing-лимиты per выбранной стратегии (шаг 1). Frontend селектор источника + gen.types.
6. **RED integration:** `test_twitter_watchlist.py` — create `source_kind=twitter` + сбор с замоканным API v2. Реализовать до GREEN. AC4/AC5.
7. **GREEN + G2 + 5.5:** `make ci-fast`/`make up` — unit+integration зелёные (мок API); проверить ядро не тронуто (AC6); security — ключи из env, rate-limit инкапсулирован.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Ядро-контракт неизменен (ADR-001)** — `base.py` (`SourceCollector`/`RawPost`/`PostMetrics`) и pipeline/scorer не меняются; новый источник = новая реализация Protocol.
- **`base.py` SDK-free** — Twitter SDK/httpx-клиент только в `collector/twitter/`; ядро не импортирует platform SDK (как telegram).
- **PostMetrics: int, не None** — `views`/`forwards`/`reactions` всегда целые; платформо-специфика — в `extra` (named int counts).
- **Rate-limit инкапсулирован** — Twitter rate-limit/backoff/токен-ротация внутри `TwitterCollector`, не в `SourceCollector`-интерфейсе (ADR-001).
- **Lazy registration** — `_build_twitter_collector` ленив (импорт registry без Twitter-ключей/SDK side-effect-free, как telegram).
- **Секреты из env** — Twitter API key/OAuth2 — `config.get_settings()` из env, None-guard; никогда в коде/логах (CONVENTIONS).
- **Backward-compat watchlist** — `source_kind` default telegram; существующие watchlist'ы не ломаются.
- **No magic literals** — лимиты из `plans.py`/`PLAN_LIMITS`; метрик-маппинг — именованные константы.

## Edge cases
- Twitter API ключ отсутствует в env → `_build_twitter_collector` бросает config-error (как `PoolConfigError` telegram); registry-импорт всё равно side-effect-free (lazy); CI на моке не зависит от ключа.
- `impression_count` недоступен на free Twitter-tier → fallback `views=0` или `view_count` (не падать); зафиксировать в mapper.
- `public_metrics` отсутствует у некоторых tweet → дефолт нули (PostMetrics: не None).
- watchlist `source_kind=twitter` при незарегистрированном collector (ключи не настроены в окружении) → create → понятная ошибка/`is_registered` False → 422/feature-not-available (не 500).
- per-source лимит выбран → usage-подсчёт должен фильтровать по `source_kind`, иначе telegram+twitter суммируются неверно; integration ловит.
- Twitter rate-limit (429 от API v2) внутри `read` → backoff/retry внутри collector, не пробрасывать наружу как краш pipeline.
- `posted_at` от Twitter в ISO с Z → нормализовать в tz-aware UTC (контракт RawPost).
- `external_id` коллизия между источниками → dedup в пределах source (`SourceRef.kind`), не глобально.

## Test plan
- **unit (backend):** `test_twitter_collector.py` — `isinstance(.., SourceCollector)` (`@runtime_checkable`, AC1), маппинг `public_metrics`→`PostMetrics` (мок tweet, AC2), `posted_at` UTC, `external_id` dedup. Мок API v2 (respx/fake-клиент).
- **integration (backend):** `test_twitter_watchlist.py` — `is_registered(TWITTER)` True (AC3), watchlist create `source_kind=twitter` + сбор с замоканным API v2 (AC4); per-source лимит-подсчёт (AC5, если выбран).
- **unit (frontend):** `tests/unit/watchlists/**` — селектор источника, дефолт telegram.
- **runtime/behavioral (G2):** `make ci-fast`/`make up` → unit+integration зелёные на моке API; ручная проверка: ядро (`base.py`/pipeline) не в диффе (AC6); реальный Twitter не дёргается (внешняя зависимость).
- **security (5.5):** Twitter API key/OAuth2 из env (grep — нет в коде/логах); rate-limit/backoff инкапсулирован в collector (не в интерфейсе/наружу).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-031-twitter-source"
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
(initial — план по эталону [task-013](./task-013-frontend-foundation.md)/[task-017](./task-017-billing-account-ui.md) и реальному коду: [ADR-001](../architecture/adr-001-source-abstraction.md) source-abstraction готова — `collector/base.py` SDK-free (`SourceCollector` Protocol `@runtime_checkable`, `RawPost`/`PostMetrics`, `SourceKind` enum с TELEGRAM+TWITTER где TWITTER — «future marker, declared not implemented»); `collector/registry.py` lazy in-code register, `register(TELEGRAM, ...)` есть, TWITTER намеренно НЕ зарегистрирован (task-005 AC7); `collector/telegram/` — эталон (reader/client/account_pool/mapper/dedup). Ядро готово к Twitter на ~80% — нужен `collector/twitter/` + регистрация. Лимиты: `billing/plans.py` `_FREE_CHANNELS=5`/`PLAN_LIMITS[plan][CHANNELS]`, сейчас суммарный — решить per-source в ADR-001 §schema (минимальный путь — оставить суммарный с обоснованием, избегая over-engineering). Watchlist уже знает `source_kind` (default telegram) — добавить выбор источника. Twitter API доступ = ВНЕШНЯЯ зависимость → тесты на замоканном API v2 (respx/fake), CI не дёргает реальный Twitter; реальный live-verify — отдельный долг. Ядро/pipeline/scorer НЕ трогаем (платформо-независимы). deps: 005 (collector/source-abstraction). ADR-001 §schema дополняется ПЕРВЫМ (G1). locate+plan выполнены этим планированием — executor стартует с «3 do».)
