---
id: TASK-092
title: Reddit source readiness — третий SourceCollector (ADR-001), OAuth2 app-only клиент, регистрация, per-source handle
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-092-reddit-source"
tags: [backend, collector, source-abstraction, reddit, reddit-loop, phase-r, R1]
deps: []
---

# TASK-092 — Reddit source readiness (reddit-loop ФАЗА R ядро)

> **Зеркало [TASK-031](./task-031-twitter-source.md)** (Twitter-источник) для Reddit. Реализовать
> **третий источник** по [ADR-001](../architecture/adr-001-source-abstraction.md) (source abstraction):
> (1) `backend/src/collector/reddit/` — реализация `SourceCollector` Protocol (Reddit OAuth2
> application-only, read-only публичные данные — **бесплатно**); маппинг метрик submission→`PostMetrics`
> (`score`→`reactions`, `num_crossposts`→`forwards`, `views`→0; прочее в `extra`); `RawPost`. (2) Регистрация
> в `collector/registry.py` (`_build_reddit_collector` + `register(SourceKind.REDDIT, ...)`). (3) Расширить
> `collector/base.py::SourceKind` ровно одним значением `REDDIT = "reddit"` (контракт неизменен — ADR-001 scope
> guard). (4) Watchlist API знает `source_kind=reddit` (per-source `REDDIT_HANDLE_PATTERN`). **Ядро
> (`base.py` кроме +1 enum, pipeline, scorer, API-логика) НЕ трогать** — платформо-независимо. Reddit API
> доступ — **внешняя зависимость** (мок API в тестах — respx/fake). DoD — Acceptance Criteria ниже.

## Context

TrendPulse — [ADR-001](../architecture/adr-001-source-abstraction.md): source-abstraction готова под
мульти-источник, Twitter добавлен ([TASK-031](./task-031-twitter-source.md)) как точная калька TG. Ядро в
`backend/src/collector/base.py` (SDK-free):
- `SourceKind(StrEnum)` — `TELEGRAM`, `TWITTER`; **добавить `REDDIT = "reddit"`** (единственное допустимое
  изменение base.py — расширение enum, контракт `SourceCollector`/`RawPost`/`PostMetrics` неизменен).
- `SourceRef(kind, handle)`, `PostMetrics(views, forwards, reactions, extra: Mapping[str,int])`,
  `RawPost(source, external_id, author, text, media_hashes, metrics, posted_at)`.
- `SourceCollector(Protocol)` (`@runtime_checkable`): атрибут `kind`; `async validate_ref(ref) -> bool`;
  `read(refs, since) -> AsyncIterator[RawPost]`. Rate-limit/backoff/token-refresh — **внутри** реализации.

`collector/registry.py` — lazy in-code mapping `SourceKind→factory`: `register/is_registered/get`; есть
`register(TELEGRAM, ...)` и `register(TWITTER, _build_twitter_collector)`. **REDDIT отсутствует** — добавить.
Код-эталон — `collector/twitter/{__init__,client,reader,mapper,dedup}.py` (зеркалить, не изобретать).

`Channel.source_kind` = `native_enum=False` VARCHAR без CHECK (migration 0001, как у Twitter) → **миграция НЕ
нужна**. Pipeline/scorer зависят ТОЛЬКО от `RawPost`/`PostMetrics` (платформо-независимо). Celery —
`collector/tasks.py::collect_watched_sources` уже source-agnostic (группирует refs by_kind, зовёт
`registry.get(kind).read`) → **новый таск НЕ нужен**.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, Pydantic на границе, no magic literals,
секреты (Reddit client_id/secret) только из env, маскировать в логах. **Ядро SDK-free — `base.py` НЕ
импортирует platform SDK.**

## Goal

После задачи: `collector/reddit/` реализует `SourceCollector` Protocol (Reddit OAuth2 application-only,
token-refresh; метрики маппятся в `PostMetrics`; `RawPost` нормализован, `posted_at` tz-aware UTC из
`created_utc`, `external_id`=`t3_…` dedup); `register(SourceKind.REDDIT, ...)` — `is_registered(REDDIT)` True,
`get(REDDIT)` строит collector лениво (ключи из env, None-guard); watchlist можно создать с
`source_kind=reddit` (per-source `REDDIT_HANDLE_PATTERN`); pipeline/scorer/API не тронуты; `SourceKind`
расширен ровно `REDDIT`. Reddit API доступ — внешняя зависимость (тесты на моке). Security: client_id/secret/
user-agent из env (не в коде/логах); Reddit rate-limit (429 / `X-Ratelimit-*`) инкапсулирован внутри
collector. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Defaults из reddit-loop runbook §Reddit-spec — выводимы из Reddit API, ничего не спрашиваем. -->
- Q: Структура reddit-collector? → A: зеркалит twitter/telegram → Decision: `collector/reddit/` =
  `__init__.py`, `client.py` (OAuth2 application-only клиент + token-refresh), `reader.py`
  (`RedditCollector(SourceCollector)` с `kind=REDDIT`/`validate_ref`/`read`), `mapper.py` (submission→
  `RawPost`/`PostMetrics`), `dedup.py`. Адаптируем паттерн twitter, не катаем новый.
- Q: Доступ/тариф? → A: Reddit OAuth2 **application-only** (app «script»/«web»), read-only публичные данные —
  **бесплатно** (в отличие от Twitter pay-per-use). Токен: `POST https://www.reddit.com/api/v1/access_token`
  (`grant_type=client_credentials`, Basic-auth `client_id:client_secret`), API после auth —
  `https://oauth.reddit.com`. Reddit **требует уникальный `User-Agent`**.
- Q: Env-имена? → A: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` (+ optional
  `REDDIT_API_BASE_URL`). Пусто = Reddit-ингест выключен (warn-once no-op, как пустой TG-пул / пустой
  Twitter-Bearer). В `config.Settings` — optional None-guard; маскировать в логах.
- Q: handle-формат? → A: `handle` = сабреддит без префикса `r/`, 3–21 символ `[A-Za-z0-9_]` →
  `REDDIT_HANDLE_PATTERN`. В data.py/watchlist хранить без `r/`.
- Q: Эндпоинты? → A: `GET /r/{sub}/about` (validate_ref — сабреддит существует/публичный),
  `GET /r/{sub}/new?limit=N` (свежие посты; фильтр `created_utc >= since`).
- Q: Маппинг метрик submission→PostMetrics (всегда int, не None)? → A: Decision: `score`(ups)→`reactions`,
  `num_crossposts`→`forwards`, `views`→**0** (Reddit не отдаёт просмотры в API); `num_comments` /
  `upvote_ratio`×100 / `total_awards_received`→`extra` (named ints). `external_id` = id поста (`t3_…`),
  `posted_at` = `created_utc` (epoch) → tz-aware UTC.
- Q: Кадэнс/лимиты? → A: named-константы в `collector/constants.py`: `REDDIT_COLLECT_INTERVAL_SECONDS = 300`
  (5 мин — Reddit дешевле Twitter, но не спамим), `REDDIT_MAX_RESULTS_PER_TICK = 50`. Rate-limit: free OAuth
  ~100 QPM; уважать `X-Ratelimit-Remaining`/`X-Ratelimit-Reset` и 429-backoff внутри collector (как Twitter
  429-cap / TG FLOOD_WAIT). **Жёсткий месячный read-budget НЕ нужен** (нет per-read цены — в отличие от
  Twitter) — достаточно rate-limit-aware backoff; зафиксировано как осознанное решение.
- Q: Reddit API доступ для тестов? → A: внешняя зависимость → Decision: тесты против **замоканного API**
  (respx/fake-клиент); реальный Reddit не дёргаем в CI. Реальный ключ — owner-gated live-verify (ФАЗА 2).
- Q: Лимиты планов? → A: оставить **суммарный** `Resource.CHANNELS` (как решено для Twitter в ADR-001
  §schema) — минимальный путь, без per-source разбивки.
- Q: Ядро? → A: НЕ трогать → Decision: `base.py` (кроме +1 значения `REDDIT` в enum), pipeline, scorer,
  API-логика остаются; добавление источника = новая реализация Protocol + регистрация (ровно как ADR-001).

## Scope
> **backend collector** (`collector/reddit/` + registry-регистрация + `SourceKind.REDDIT`) + **config**
> (Reddit settings) + **watchlist** (per-source `REDDIT_HANDLE_PATTERN`-валидация) + **env-примеры**. Ядро
> (`base.py` кроме +1 enum / pipeline / scorer / API-логика), telegram- и twitter-collector НЕ трогаем.

- **Touch ONLY (создать/изменить):**
  - **Backend:**
    - `backend/src/collector/reddit/__init__.py`, `client.py`, `reader.py`, `mapper.py`, `dedup.py` —
      **новые**: `RedditCollector` (реализует `SourceCollector`: `kind=REDDIT`, `validate_ref`, `read`),
      OAuth2 application-only клиент + token-refresh, метрик-маппер, dedup.
    - `backend/src/collector/base.py` — `SourceKind` += `REDDIT = "reddit"` (**единственное** изменение
      base.py — расширение enum; контракт `SourceCollector`/`RawPost`/`PostMetrics` неизменен).
    - `backend/src/collector/registry.py` — `_build_reddit_collector()` (lazy, ключи из
      `config.get_settings()`) + `register(SourceKind.REDDIT, _build_reddit_collector)`.
    - `backend/src/collector/constants.py` — Reddit-константы (`REDDIT_COLLECT_INTERVAL_SECONDS=300`,
      `REDDIT_MAX_RESULTS_PER_TICK=50`, 429-backoff cap, endpoints/UA/grant-type, token-refresh leeway).
    - `backend/src/config.py` — `reddit_client_id`/`reddit_client_secret`/`reddit_user_agent`/
      `reddit_api_base_url` — из env, optional (None-guard, как `twitter_bearer_token`).
    - `backend/src/api/watchlist/schemas.py` — per-source `REDDIT_HANDLE_PATTERN` + валидация по
      `source_kind` (Reddit-handle принимается, TG/Twitter-валидаторы не ломаются).
    - `backend/tests/unit/collector/test_reddit_collector.py` — **новый**: `RedditCollector` реализует
      Protocol (`isinstance`-check `@runtime_checkable`), маппинг метрик (мок API submission→RawPost/
      PostMetrics), `posted_at` UTC, `external_id` dedup, OAuth2 token-refresh на моке.
    - `backend/tests/integration/test_reddit_watchlist.py` — **новый**: `is_registered(REDDIT)` True,
      watchlist create `source_kind=reddit` + сбор с замоканным API.
  - **env-примеры:** `.env.example` + `release/deployment.example/sensitive.env.example` —
    `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT` (+ optional `REDDIT_API_BASE_URL`).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `collector/base.py` кроме +1 enum-значения
  (контракт неизменен — ADR-001), `collector/telegram/**` и `collector/twitter/**` (эталоны, не трогаем),
  pipeline/scorer (`backend/src/pipeline/**`, scorer — платформо-независимы), `billing/**` (суммарный лимит
  CHANNELS — без изменений). Не катать plugin-loader/config-DSL (ADR-001 scope guard — только in-code register).
- **Blast radius:** добавляет третий источник в registry (`is_registered(REDDIT)` → True; поведение
  `get(REDDIT)`); `SourceKind` получает значение `REDDIT`; watchlist-create принимает `source_kind=reddit`.
  Pipeline/scorer не затронуты (контракт `RawPost` стабилен). Внешняя зависимость от Reddit API (тесты на
  моке — CI не зависит от реального ключа). Лимиты планов не меняются (суммарный CHANNELS).

## Acceptance Criteria
- [ ] **AC1 — RedditCollector реализует Protocol (failing-test anchor).** Given `collector/reddit/reader.py::
  RedditCollector`, When `isinstance(collector, SourceCollector)` (`@runtime_checkable`) и вызовы, Then
  `kind==SourceKind.REDDIT`, `validate_ref`/`read` реализованы; unit с **замоканным API** проверяет маппинг
  submission→`RawPost`. Пишется ПЕРВЫМ (RED — модуля нет).
- [ ] **AC2 — метрики маппятся в PostMetrics.** Given Reddit submission, When маппер, Then `score→reactions`,
  `num_crossposts→forwards`, `views→0` (всегда int, не None); прочие (`num_comments`/`upvote_ratio`×100/
  `total_awards_received`)→`extra`; `posted_at` (`created_utc`→tz-aware UTC), `external_id`=`t3_…` стабилен
  (dedup).
- [ ] **AC3 — OAuth2 application-only + регистрация.** Given `_build_reddit_collector` + `register(REDDIT)`,
  When `is_registered(SourceKind.REDDIT)`, Then True; `get(REDDIT)` лениво строит `RedditCollector` (ключи из
  env, None-guard); клиент получает token через `client_credentials` (Basic-auth) и рефрешит по истечении —
  проверено на моке.
- [ ] **AC4 — watchlist с source_kind=reddit.** Given create-API, When создание watchlist с
  `source_kind=reddit` (handle=сабреддит без `r/`), Then принят (registry знает REDDIT,
  `REDDIT_HANDLE_PATTERN` валиден), сбор идёт через `RedditCollector` (integration с замоканным API);
  `source_kind=telegram` остаётся default (backward-compat), TG/Twitter-валидаторы не ломаются.
- [ ] **AC5 — rate-limit без read-budget.** Given Reddit free OAuth (~100 QPM, нет per-read цены), When
  инспекция, Then collector уважает `X-Ratelimit-Remaining`/`Reset` и 429-backoff внутри; жёсткого месячного
  read-budget НЕТ (осознанное решение зафиксировано); кадэнс/лимиты — named-константы (no magic literals).
- [ ] **AC6 — ядро не тронуто.** Given дифф, When инспекция, Then `collector/base.py` изменён ТОЛЬКО
  добавлением `REDDIT="reddit"` в `SourceKind` (контракт неизменен); pipeline/scorer/billing/API-логика не
  изменены; `base.py` остаётся SDK-free (reddit-клиент только в `collector/reddit/`).
- [ ] **AC7 — security + поведенческая (G2).** Given Reddit client_id/secret/user-agent, When инспекция,
  Then из env (не в коде/логах, маскированы); rate-limit/backoff/token-refresh инкапсулирован внутри
  collector; и: `make ci-fast` → unit (`test_reddit_collector`) + integration (`test_reddit_watchlist` с
  моком) зелёные; реальный Reddit не дёргается в CI (внешняя зависимость отмечена).

## Plan
0. Executor фиксирует `baseline_commit` (8debda0); ветка `gsd/phase-092-reddit-source`.
1. **base.py:** `SourceKind` += `REDDIT = "reddit"` (только enum, контракт неизменен). `constants.py` —
   Reddit-константы. `config.py` — Reddit settings (env, optional None-guard).
2. **RED:** `test_reddit_collector.py` — `isinstance(collector, SourceCollector)` + маппинг метрик (мок
   submission) + OAuth2 token-refresh. Падает (модуля нет). AC1/AC2/AC3-якорь.
3. `collector/reddit/` — `mapper.py` (submission→RawPost/PostMetrics), `client.py` (OAuth2 application-only +
   token-refresh, httpx; rate-limit/backoff/429 внутри), `dedup.py`, `reader.py` (`RedditCollector`).
4. `collector/registry.py` — `_build_reddit_collector` + `register(SourceKind.REDDIT, ...)`. AC3.
5. Watchlist create-API — per-source `REDDIT_HANDLE_PATTERN` + валидация по `source_kind`. `.env.example` +
   `release/deployment.example/sensitive.env.example`.
6. **RED integration:** `test_reddit_watchlist.py` — create `source_kind=reddit` + сбор с замоканным API.
   Реализовать до GREEN. AC4.
7. **GREEN + G2 + 5.5:** `make ci-fast` — unit+integration зелёные (мок API); проверить ядро не тронуто
   кроме +1 enum (AC6); security — ключи из env/маскированы, rate-limit инкапсулирован (AC5/AC7).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Ядро-контракт неизменен (ADR-001)** — `base.py` (`SourceCollector`/`RawPost`/`PostMetrics`) и
  pipeline/scorer не меняются; единственное изменение base.py = `SourceKind` += `REDDIT`.
- **`base.py` SDK-free** — Reddit httpx-клиент только в `collector/reddit/`; ядро не импортирует platform SDK.
- **PostMetrics: int, не None** — `views`(=0)/`forwards`/`reactions` всегда целые; платформо-специфика — в
  `extra` (named int counts).
- **Rate-limit инкапсулирован** — Reddit 429/`X-Ratelimit-*`/token-refresh внутри `RedditCollector`, не в
  `SourceCollector`-интерфейсе (ADR-001).
- **Lazy registration** — `_build_reddit_collector` ленив (импорт registry без Reddit-ключей side-effect-free).
- **Секреты из env** — `REDDIT_CLIENT_ID`/`SECRET`/`USER_AGENT` — `config.get_settings()` из env, None-guard;
  никогда в коде/логах, маскировать (CONVENTIONS).
- **Backward-compat watchlist** — `source_kind` default telegram; существующие watchlist'ы не ломаются.
- **No magic literals** — кадэнс/лимиты/эндпоинты — именованные константы в `constants.py`; метрик-маппинг —
  именованные ключи.
- **Нет read-budget** — в отличие от Twitter, Reddit free OAuth не имеет per-read цены → только
  rate-limit-aware backoff (осознанное решение).

## Edge cases
- Reddit ключи отсутствуют в env → `_build_reddit_collector` → warn-once no-op (как пустой TG-пул / пустой
  Twitter-Bearer); registry-импорт side-effect-free (lazy); CI на моке не зависит от ключа.
- OAuth2 token истёк во время `read` → клиент рефрешит (`client_credentials`) и повторяет; refresh-фейл →
  per-ref `SourceUnavailableError`, не краш тика.
- `views` отсутствует у submission (Reddit не отдаёт просмотры) → `views=0` (PostMetrics: не None).
- `upvote_ratio` float (0.0–1.0) → в `extra` как int (×100); отсутствует → 0.
- сабреддит приватный/забанен/удалён → `validate_ref` False (через `GET /r/{sub}/about` 403/404), не 500.
- watchlist `source_kind=reddit` при незарегистрированном collector (ключи не настроены) → `is_registered`
  False → 422/feature-not-available (не 500).
- Reddit 429 (rate-limit) внутри `read` → backoff/retry по `X-Ratelimit-Reset` внутри collector, не
  пробрасывать как краш pipeline.
- `created_utc` (epoch float) → нормализовать в tz-aware UTC (контракт RawPost).
- `external_id` коллизия между источниками → dedup в пределах source (`SourceRef.kind`), не глобально;
  `t3_`-префикс Reddit стабилен.
- `User-Agent` не задан → Reddit отдаёт 429/403 на старте; UA обязателен (валидировать наличие при build).

## Test plan
- **unit (backend):** `test_reddit_collector.py` — `isinstance(.., SourceCollector)` (`@runtime_checkable`,
  AC1), маппинг submission→`PostMetrics` (мок, AC2), `posted_at` UTC, `external_id` dedup, OAuth2
  token-refresh (мок `access_token` истёк→рефреш, AC3), 429-backoff. Мок API (respx/fake-клиент).
- **integration (backend):** `test_reddit_watchlist.py` — `is_registered(REDDIT)` True (AC3), watchlist
  create `source_kind=reddit` + сбор с замоканным API (AC4); per-source handle-валидация.
- **runtime/behavioral (G2):** `make ci-fast` → unit+integration зелёные на моке API; ручная проверка:
  ядро (`base.py` кроме +1 enum / pipeline) не в диффе (AC6); реальный Reddit не дёргается (внешняя
  зависимость). Live-verify на проде — owner-gated (ФАЗА 2 runbook).
- **security (5.5):** Reddit client_id/secret/user-agent из env (grep — нет в коде/логах, маскированы);
  rate-limit/backoff/token-refresh инкапсулирован в collector (не в интерфейсе/наружу).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-092-reddit-source"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved; зеркало TASK-031, defaults из runbook §Reddit-spec)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior на моке API)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план = точная калька [TASK-031](./task-031-twitter-source.md) (Twitter-источник) для Reddit, по
[ADR-001](../architecture/adr-001-source-abstraction.md) и реальному коду: `collector/base.py` SDK-free
(`SourceCollector` Protocol `@runtime_checkable`, `RawPost`/`PostMetrics`, `SourceKind` enum TELEGRAM+TWITTER →
+REDDIT); `collector/registry.py` lazy in-code register (TELEGRAM+TWITTER есть, REDDIT нет);
`collector/twitter/` — свежий эталон реализации (client/reader/mapper/dedup). `Channel.source_kind` =
native_enum=False VARCHAR (migration 0001) → миграция НЕ нужна, как у Twitter. Celery
`collect_watched_sources` source-agnostic → новый таск НЕ нужен. Reddit OAuth2 application-only (бесплатно, в
отличие от Twitter pay-per-use) → НЕТ read-budget, только rate-limit-aware backoff. Reddit API доступ =
ВНЕШНЯЯ зависимость → тесты на замоканном API (respx/fake), CI не дёргает реальный Reddit; live-verify —
owner-gated ФАЗА 2. Ядро/pipeline/scorer/billing НЕ трогаем (платформо-независимы; base.py — только +1 enum).
deps: нет (source-abstraction + Twitter-эталон уже на main). locate+plan выполнены этим планированием —
executor стартует с «3 do». Run в изолированном git worktree `apps/trendPulse-reddit` — основное дерево
занято параллельной TASK-031d-сессией.)
