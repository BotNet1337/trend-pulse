---
id: TASK-128
title: S7 ingest-объём — overlapping crypto-RU pack (+ pool≥3 owner-gate)
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 6c33a50
branch: ""
tags: [scoring-evolution, s7, ingest, packs, collector, ops, owner-gated, crypto-ru]
---

# TASK-128 — S7 ingest-объём: overlapping crypto-RU pack (+ pool≥3 owner-gate)

> Поднять ПЕРЕКРЫТИЕ каналов так, чтобы одно событие физически появлялось в нескольких
> каналах одновременно → субстрат для кросс-канальной широты (S2/S3) и финального
> демо ценности. Автономная половина = curated overlapping crypto-RU pack; пул≥3 = owner-gate.

## Context

S7 в [`03-scoring-evolution-plan.md`](../architecture/states/03-scoring-evolution-plan.md#s7--ingest-объём-ops-параллельно):
«поднять перекрытие каналов → физическая основа широты для S2/S3». D7
([`02-state-target.md#d7`](../architecture/states/02-state-target.md)) рек. **1+4**:
пул ≥3 сессий + **curated cross-overlapping packs** (каналы, пишущие об ОДНИХ событиях:
новостные агрегаторы + первоисточники) для гарантированного overlap.

Почему это «основа моата»: viral score детектит историю, разгоняющуюся ПОПЕРЁК каналов.
Без физического перекрытия `channels_count` остаётся ≈1 и кросс-канальная широта (цель
S2 ≥35% multi-channel) недостижима — S2/S3 упрутся в отсутствие данных (S2 §«Зависит от: S7»).

**Packs-механизм УЖЕ существует** (TASK-038, в проде):
- Каталог — статический иммутабельный `backend/src/api/packs/data.py`
  (`PackDef`/`PackChannel`/`PACK_CATALOG`, frozen dataclasses, single source of truth).
- Подписка — `POST /packs/{slug}/subscribe` → `api/packs/service.subscribe` bulk-insert
  строк watchlist с маркером `pack_slug` (идемпотентно, savepoint-per-channel skip-conflict);
  канал резолвится через `ChannelRepository.get_or_create` → попадает в набор коллектора по
  обычному watchlist→collector пути.
- Сидинг для демо — `ensure_showcase_tenant` (`backend/src/api/trending/bootstrap.py`,
  TASK-039) подписывает системного showcase-юзера на **ВСЕ** паки каталога (bypass лимита),
  вызывается из `make showcase-init` (часть `make deploy`). **Новый пак подхватывается
  автоматически** — отдельный сидинг-скрипт НЕ нужен.
- Тесты каталога — `backend/tests/unit/test_packs_catalog.py` (формат handle по kind,
  frozen, уникальность slug, per-pack счётчики) + `backend/tests/integration/test_packs_api.py`.

**Существующий `crypto-ru`** — 29 TG-каналов, добавлялся именно ради density
(`data.py:86-126` коммент: «DENSITY is the point … same crypto event must realistically
land in many of these at once»). Перекрытие там «топик-широкое» (вся крипта-RU). Эта задача
добавляет УЗКИЙ **event-overlap** пак: новостные агрегаторы + первоисточники, которые
со-репортят ОДНО событие в окне минут — прямой driver `channels_count>1` на конкретной истории.

Пул: `config.py:680 pool_min_healthy` (код-default 3 via `_DEFAULT_POOL_MIN_HEALTHY`,
прод выставляет 1); hard-floor `collector/constants.py:27 POOL_MIN=1`, `POOL_MAX=10`.
Пул≥3 = owner-gate (покупка номеров) — TASK-059 (runbook в `development/scripts/README.md`).

## Goal

В каталог паков добавлен новый curated пак `crypto-ru-overlap` (~20 публичных crypto-RU
TG-каналов, со-репортящих одни события: агрегаторы + первоисточники), помеченных как
кандидаты «public, verify live». Пак проходит unit-тесты каталога и подхватывается
`make showcase-init` без нового кода сидинга. Пул≥3 и live-подписка/проверка перекрытия —
явно задокументированы как owner/runtime-gated (НЕ выполняются в этой задаче). DoD = AC.

## Discussion
<!-- durable record of clarifications; autonomous — resolved from code/docs -->

- Q: Существует ли packs-механизм, или нужен новый сидинг? → A: исследовал код
  (`api/packs/{data,service,router}.py`, `trending/bootstrap.py`, reddit/twitter-data-guide §5).
  → **Decision:** механизм ПОЛНОСТЬЮ существует (TASK-038, в проде) — code/data-level, не
  doc-level. План = **добавить пак-запись в `data.py`** (как crypto-twitter/crypto-reddit),
  НЕ писать новый сидинг. (rationale: smallest diff; `ensure_showcase_tenant` уже подписывает
  все паки; PR-правка `data.py` — канонический способ добавления каналов, «без admin-UI».)

- Q: Новый пак или расширить существующий `crypto-ru` (29 каналов)? → A: **новый пак
  `crypto-ru-overlap`**. → **Decision:** разделяем намерения. `crypto-ru` = широкий
  топик-density (вся крипта-RU). Новый = узкий **event-overlap** (агрегаторы+первоисточники,
  со-репорт одного события в минутном окне) — это прямой и измеримый driver `channels_count>1`
  на КОНКРЕТНОЙ истории, и его можно подписать отдельно для чистого демо ценности без шума
  широкого пака. (rationale: не раздуваем 29-канальный пак до неуправляемого; отдельный slug
  = отдельная демо-подписка + отдельный замер overlap.)

- Q: Сколько каналов и как валидировать? → A: ~20, помечены «CANDIDATES — public, verify
  live». → **Decision:** как у crypto-twitter/crypto-reddit — handles = кандидаты, живость
  отсекается коллектором при чтении (dead handle → resolve None → skip, ADR-001); TG-handles
  по возможности переиспользуем уже-верифицированные из `crypto-ru` (там verified live
  2026-06-13 via t.me/s). Live-прогон перекрытия — owner/runtime-gated (нужен живой пул +
  ≥1-2 тика). (rationale: предзагрузочная live-валидация требует запущенного коллектора —
  это runtime, не plan-time; формат-валидацию даёт unit-тест.)

- Q: Пул≥3 — делаем? → A: **НЕТ, owner-gate.** → **Decision:** покупка номеров + QR-login —
  TASK-059 (⛔ owner). Эта задача его только ДОКУМЕНТИРУЕТ как owner-gate, `pool_min_healthy`
  НЕ трогаем (порядок «сессии→порог» — инвариант TASK-059). (rationale: prime directive —
  не пытаться купить номера; пул-конфиг вне scope.)

- Q: Нужен ли отдельный сидинг-скрипт под `backend/scripts/`? → A: **НЕТ.** → **Decision:**
  `ensure_showcase_tenant` + `make showcase-init` уже сидят все паки идемпотентно; новый
  скрипт = дублирование. (rationale: smallest diff; recommended fallback из брифа — «no new
  code, use existing subscription» — здесь даже лучше: пак-запись + существующий showcase-сид.)

- Q: Точный slug нового пака? → A: `crypto-ru-overlap`. → **Decision:** lowercase,
  совпадает с конвенцией существующих slug'ов (`crypto-ru`/`crypto-en`/`crypto-twitter`);
  `_DEFAULT_MIN_CHANNELS`/`threshold` дефолты пака — как у crypto-ru (наследуют PackDef-дефолты).

## Scope
> **backend (data-only) + docs.** Один рантайм-файл правится append-only (новая
> tuple + новая запись в catalog). Никакого нового кода/схемы/API/миграции.

- **Touch ONLY:**
  - `backend/src/api/packs/data.py` — новая tuple `_CRYPTO_RU_OVERLAP_CHANNELS`
    (~20 `PackChannel(..., kind=SourceKind.TELEGRAM)`) + новая `PackDef(slug="crypto-ru-overlap", …)`
    добавлена в `PACK_CATALOG`; docstring-шапка обновлена (упомянуть 6-й пак).
  - `backend/tests/unit/test_packs_catalog.py` — 1 тест `test_crypto_ru_overlap_pack`
    (kind=TELEGRAM, ≥15 каналов, topic="crypto", handle-формат) — зеркало
    `test_crypto_reddit_pack_is_all_reddit_kind`.
  - `docs/tasks/task-128-ingest-overlapping-packs.md` — этот док (checkpoints на ship).
  - `docs/tasks/tasks-index.md` — строка (этот PR).
- **Do NOT touch:**
  - `api/packs/{service,router,schemas}.py` — механизм подписки готов, не меняется.
  - `api/trending/bootstrap.py` / `make showcase-init` — новый пак подхватывается без правок.
  - `config.py::pool_min_healthy`, `collector/constants.py::POOL_MIN/POOL_MAX` — пул вне scope
    (owner-gate TASK-059; порядок «сессии→порог» — чужой инвариант).
  - `collector/**`, `pipeline/**`, `scorer/**` — overlap влияет на них downstream БЕЗ правок кода.
  - vault / сессии / `development/scripts/README.md` — owner-gated ops (TASK-059).
- **Blast radius:** НЕТ изменения схемы/API/openapi (пак-запись — статические данные за
  существующим `GET /packs` контрактом; `channels_count` уже отдаётся). НЕТ Celery-контракта.
  Единственный рантайм-эффект: после live-подписки коллектор начнёт читать +~20 TG-каналов —
  нагрузка на пул (поэтому пул≥3 — owner-gate перед live-прогоном).

## Acceptance Criteria

- [ ] **AC1 — пак в каталоге.** Given импорт `api.packs.data` When читаем `PACK_CATALOG`
  Then присутствует `PackDef` со slug `crypto-ru-overlap`, topic `crypto`, ≥15 каналами,
  все `kind=SourceKind.TELEGRAM`, формат handle = `@`+[A-Za-z0-9_]{4,32}.
- [ ] **AC2 — каталог-тесты зелёные.** Given `make ci` (или backend unit) When гоняем
  `test_packs_catalog.py` Then все тесты (включая новый `test_crypto_ru_overlap_pack` и
  существующие unique-slug / handle-format / frozen) проходят; slug уникален.
- [ ] **AC3 — подписка работает (integration).** Given showcase/тестовый юзер When
  `POST /packs/crypto-ru-overlap/subscribe` Then `created>0`, в watchlist появляются строки
  с `pack_slug="crypto-ru-overlap"`; повторная подписка → `created=0` (идемпотентно);
  `GET /packs` показывает пак с корректным `channels_count`.
- [ ] **AC4 — сидинг без нового кода.** Given `make showcase-init` (или вызов
  `ensure_showcase_tenant`) When прогоняем Then showcase-юзер подписан в т.ч. на
  `crypto-ru-overlap` — БЕЗ правок `bootstrap.py`/Makefile.
- [ ] **AC5 — owner-gate задокументирован.** Этот док §Owner-gates явно фиксирует: пул≥3
  (TASK-059) + live-замер перекрытия — owner/runtime-gated, не выполнены здесь; никакого
  изменения `pool_min_healthy`/сессий в диффе (`git diff` по config/vault = 0).

## Plan

1. `backend/src/api/packs/data.py` — добавить `_CRYPTO_RU_OVERLAP_CHANNELS: tuple[PackChannel, ...]`
   (~20 handles из §«Curated channel list», `kind=SourceKind.TELEGRAM`, комментарий-источник
   у каждого) + `PackDef(slug="crypto-ru-overlap", title="Crypto RU Overlap", topic="crypto",
   channels=_CRYPTO_RU_OVERLAP_CHANNELS)` в `PACK_CATALOG`; обновить docstring-шапку (6-й пак).
2. `backend/tests/unit/test_packs_catalog.py` — `test_crypto_ru_overlap_pack` (зеркало reddit-теста:
   present, topic, ≥15, all TELEGRAM, handle-format).
3. `make ci` (backend unit+integration) — AC2/AC3 зелёные; `make showcase-init` на dev — AC4.
4. Обновить `docs/tasks/tasks-index.md`; ship PR (data+docs в одном PR — CONVENTIONS git).

## Invariants

- Каталог иммутабелен в рантайме (frozen tuple/dataclass — CONVENTIONS «no mutable globals»).
- НЕТ изменения схемы/API/openapi → openapi-drift-check НЕ должен сработать (пак — данные за
  существующим контрактом; новых полей нет).
- Slug `crypto-ru-overlap` уникален в `PACK_CATALOG` (unique-slug тест держит).
- Handles = публичные каналы, читаем ТОЛЬКО публичное (CONVENTIONS compliance, ADR-001);
  dead/squatted → коллектор молча скипает (resolve None).
- `pool_min_healthy` и сессии НЕ трогаются (порядок «сессии→порог» — инвариант TASK-059).
- Существующий `crypto-ru` пак (29 каналов) не изменяется (отдельный slug).

## Edge cases

- Handle уже есть в `crypto-ru` (перекрытие паков) → подписка обоих паков: `service.subscribe`
  savepoint-skip-conflict на uq `(user_id, channel_id, topic)` → строка считается `skipped`,
  не дубль, не падение. ОК by design.
- Dead/переименованный/squatted handle-кандидат → коллектор resolve→None→skip при чтении
  (ADR-001), пак не ломается; живая чистка — owner-gated после live-прогона.
- Пустой/невалидный handle в tuple → unit-тест `test_all_handles_match_format_for_kind`
  (существующий) + новый per-pack тест валят сборку до мерджа (fail-fast).
- Live-подписка на пустом/≤1 пуле → коллектор не успевает читать +20 каналов → overlap не
  вырастет: поэтому live-замер ЗА owner-gate (пул≥3).

## Test plan

- **unit:** `test_packs_catalog.py::test_crypto_ru_overlap_pack` (новый) + существующие
  (unique-slug, handle-format-by-kind, frozen, non-empty) автоматически покрывают новый пак.
- **integration:** `test_packs_api.py` — subscribe/idempotency/unsubscribe для нового slug
  (расширить параметризацию если она slug-driven; иначе 1 кейс).
- **e2e/live (owner/runtime-gated, НЕ в этой задаче):** после пула≥3 — подписать
  `crypto-ru-overlap`, дождаться 1-2 тиков, увидеть рост доли `channels_count>1` (psql) —
  фиксируется в §Owner-gates как follow-up.

## Curated channel list — `crypto-ru-overlap` (~20, public, verify live)

> Цель подбора: каналы, которые со-репортят ОДНО событие (breaking crypto-RU) в окне минут —
> новостные агрегаторы + первоисточники. Многие уже verified live 2026-06-13 в `crypto-ru`
> (помечено ✓reused) → переиспользуем верифицированный handle; остальные — кандидаты «verify
> live» (коллектор скипнёт мёртвые). Все `kind=SourceKind.TELEGRAM`, формат `@`+[A-Za-z0-9_]{4,32}.

**Новостные агрегаторы / медиа (быстрый со-репорт одного события):**
- `@forklog` — ForkLog ✓reused
- `@RBCCrypto` — РБК Крипто ✓reused
- `@if_market_news` — InvestFuture Market News ✓reused
- `@cryptodaily` — Crypto Daily ✓reused
- `@web3news` — Web3 News RU ✓reused
- `@incrypted` — Incrypted ✓reused
- `@bitsmedia` — BITS.MEDIA ✓reused
- `@hashtelegraph` — Hash Telegraph ✓reused
- `@coin_post` — CoinPost ✓reused
- `@crypto_hd` — Crypto Headlines ✓reused
- `@cryptodaily_ru` — Crypto Daily RU (candidate, verify live)
- `@bitnovosti` — BitNovosti (candidate, verify live)
- `@cryptorussia_news` — CryptoRussia (candidate, verify live)

**Первоисточники / биржи / экосистемные (origin-каналы события):**
- `@binance_ru` — Binance Новости RU ✓reused
- `@toncoin_rus` — Toncoin RUS ✓reused
- `@tonblockchain` — TON Blockchain ✓reused
- `@decenter` — DeCenter ✓reused
- `@crypto_sekta` — Криптосекта ✓reused
- `@bybite_ru` — Bybit RU (candidate, verify live)
- `@okx_russian` — OKX Russian (candidate, verify live)

> Подбор co-report-плотный: при breaking-новости (листинг, хак, регуляторка) она реалистично
> падает в большинство этих каналов в течение минут → `channels_count` на кластере растёт.
> Кандидаты без ✓ — best-effort публичные имена, отсеиваются коллектором если мёртвы; финальную
> live-чистку (как validate_ref у twitter/reddit) делает owner-прогон после пула≥3.

## Owner-gates (нужно решение/действие владельца — НЕ выполняется в этой задаче)

1. **Пул ≥3 сессий — TASK-059 (⛔ owner).** Купить ≥2 TG-номера (физ. SIM / надёжный
   виртуальный оператор — НЕ одноразовые SMS), QR-login по runbook
   `development/scripts/README.md` §«Пул технических аккаунтов», append в vault, поднять
   `pool_min_healthy` 1→3 ПОСЛЕ заполнения (порядок «сессии→порог» обязателен). Без пула≥3
   live-чтение +20 overlap-каналов перегружает один аккаунт (FLOOD_WAIT-инцидент).
   ⚠ Hazard: НЕ backfill-ить на live-pool-сессии (AuthKeyDuplicated, [[trendpulse-tg-session-incident]]).
2. **Live-замер перекрытия (runtime-gated).** После пула≥3 + деплоя нового пака: подписать
   `crypto-ru-overlap` (showcase или тест-юзер), дождаться 1-2 тиков, подтвердить psql'ом рост
   доли `channels_count>1` кластеров. Это фактическая проверка ценности S7 → питает S2 (≥35%
   multi-channel). Owner/loop-прогон, не plan/executor-стадия.
3. **Live-чистка мёртвых handle-кандидатов (после ключей/пула).** Как validate_ref у
   twitter/reddit паков — отсеять переименованные/squatted; до этого коллектор молча скипает.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 4
baseline_commit: 6c33a50
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing catalog test → pack entry)
- [ ] 4 verify (G2 — unit+integration tests + showcase-init seeding)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (N/A — no auth/input/secret surface; data-only)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-17. S7 из scoring-evolution; D7 рек.1+4. Автономная половина = data-only
пак-запись + 1 unit-тест (packs-механизм TASK-038 уже в проде; сидинг через
`ensure_showcase_tenant`/`make showcase-init` — без нового кода). Owner-половина = пул≥3
(TASK-059) + live-замер overlap — задокументированы как owner/runtime-gate, не выполняются.
Зависимости концептуальные: TASK-038 (packs), TASK-039 (showcase-bootstrap), TASK-059 (пул).
Питает: S2/TASK-123 (кросс-канальная широта ≥35%), S3/TASK-124 (breadth-velocity).)
</content>
</invoke>
