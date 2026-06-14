---
id: TASK-093
title: Reddit seed-pack «Crypto Reddit (RU+EN)» через packs-фичу + per-source handle-валидация
status: done           # код+pack merged; live validate_ref owner-gated на ключ
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-093-reddit-seed-pack"
tags: [collector, reddit, packs, watchlist, reddit-loop, phase-r, R2]
deps: [092]
---

# TASK-093 — Reddit seed-pack «Crypto Reddit (RU+EN)» (reddit-loop ФАЗА R / R2)

> **Зеркало [TASK-089](./task-089-twitter-seed-pack.md)** (Twitter seed-pack) для Reddit.
> Зависит от [TASK-092](./task-092-reddit-source.md) (collector/reddit + регистрация + `SourceKind.REDDIT` +
> per-source `REDDIT_HANDLE_PATTERN`).

## Goal
Собрать pack из сабреддитов РОВНО как pack из TG-каналов / Twitter-аккаунтов, переиспользуя существующую
packs-фичу (`api/packs/*`), НЕ плодя новую сущность. Сабреддит = `PackChannel(handle, kind=REDDIT)`.
Перед добавлением — провалидировать каждый через `RedditCollector.validate_ref()`; невалидные (приватные/
мёртвые/переименованные) отсечь с причиной (лог + отчёт). Цель ~20–30 живых.

## Discussion (дефолты)
- packs УЖЕ поддерживают `PackChannel.kind` (default TELEGRAM, Twitter добавлен в TASK-089) → Reddit-pack =
  новый `PackDef` с `kind=REDDIT`. Подписка создаёт watchlist-строки тем же `service.subscribe`.
- Валидация handle: сабреддит без `r/`, 3–21 символ `[A-Za-z0-9_]` (per-source `REDDIT_HANDLE_PATTERN`,
  пререквизит из TASK-092). В `data.py` хранить без `r/`.
- live-`validate_ref` требует реальных Reddit-ключей (`REDDIT_CLIENT_ID`/`SECRET`/`USER_AGENT`) →
  **owner-gated**: до ключа фиксируем список-кандидатов + код/тесты на моках; живой прогон (валидация→pack→
  ингест→viral_score) — ФАЗА 2 по появлению ключа (MANUAL-TODO).
- Кандидаты-сабреддиты (валидировать, оставить живых, приватные/мёртвые — в отчёт; имена без `r/`):
  - EN: CryptoCurrency CryptoMarkets Bitcoin BitcoinMarkets ethereum ethtrader ethfinance defi
    CryptoCurrencyTrading altcoin Crypto_com binance solana CardanoCoin Monero litecoin dogecoin
    CryptoMoonShots SatoshiStreetBets BitcoinBeginners
  - RU: Bitcoin_ru CryptoCurrencyRU (узких RU-крипто-сабов мало — большинство RU-аудитории на TG; список
    RU валидируется живьём в ФАЗА 2, мёртвые молча отсекаются).

## Acceptance Criteria
- AC1: новый `PackDef(slug="crypto-reddit", topic="crypto", channels=(PackChannel(.., kind=REDDIT)…))` в
  `backend/src/api/packs/data.py`; финальный валидированный список зафиксирован в docs/ (RU/EN + почему).
- AC2: per-source handle-валидация (`REDDIT_HANDLE_PATTERN`) в watchlist-create — Reddit-handle (сабреддит
  без `r/`) принимается, TG/Twitter-валидаторы не ломаются.
- AC3: подписка на pack создаёт watchlist-строки с `source_kind=reddit`; backward-compat TG/Twitter packs.
- AC4 (owner-gated, live): прогон `validate_ref` по кандидатам, отсев мёртвых в отчёт; ингест по pack'у →
  посты с `viral_score`. До ключа — на моках; живой — ФАЗА 2.
- AC5: тесты ≥80% нового кода; `make ci-fast` зелёный; ядро/pipeline не тронуты.

## Scope
- **Touch ONLY:** `backend/src/api/packs/data.py` (новый `PackDef` `crypto-reddit`); тесты
  `backend/tests/unit/api/packs/**` (или зеркало twitter-pack теста) — pack-определение валидно, subscribe
  создаёт reddit-watchlist (мок); `docs/tasks/tasks-index.md` на ship; (опц.) docs-файл со списком
  сабреддитов + обоснованием.
- **Do NOT touch:** `collector/**` (готов в TASK-092), pipeline/scorer, billing, `_bmad/.claude/landing`.
- **Blast radius:** добавляет Reddit-pack в каталог packs; подписка создаёт `source_kind=reddit` watchlist.
  Backward-compat TG/Twitter packs.

## Verify
- unit: pack-определение валидно, handle-валидатор per-source (`REDDIT_HANDLE_PATTERN`); subscribe создаёт
  reddit-watchlist (мок). live behavioral — owner-gated MANUAL-TODO (нужны Reddit-ключи) → ФАЗА 2.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-093-reddit-seed-pack"
lock: ""
- [x] 1 locate (scope + patterns)
- [x] 2 plan (this doc, зеркало TASK-089)
- [x] 3 do (PackDef crypto-reddit ~22 субов + catalog-тесты)
- [x] 4 verify (G2 на моке — ci-fast зелёный 938 passed; live owner-gated ФАЗА 2)
- [x] 5 review (data-only каталог; handle-формат покрыт catalog-тестом, нет нового код-пути)
- [x] 5.5 security (n/a — статичные курируемые данные, валидируются паттерном)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
(initial — калька [TASK-089](./task-089-twitter-seed-pack.md): packs-фича переиспользуется
(`PackChannel.kind=REDDIT`), новой сущности нет. Зависит от TASK-092 (collector/reddit + регистрация +
`REDDIT_HANDLE_PATTERN`). live-`validate_ref` owner-gated на Reddit-ключ → до ключа моки, живой прогон ФАЗА 2.
Run в worktree `apps/trendPulse-reddit`.)

### Реализация 2026-06-14 (do→verify→ship)
`api/packs/data.py`: добавлен `_CRYPTO_REDDIT_CHANNELS` (~22 сабреддита, bare+lowercase, без `r/`, kind=REDDIT)
+ `PackDef(slug="crypto-reddit", title="Crypto Reddit (RU+EN)", topic="crypto")` в `PACK_CATALOG`; docstring
обновлён (пятый pack). Subreddit-имена: EN-крипто (cryptocurrency/bitcoin/ethereum/ethtrader/defi/solana/…)
+ 2 RU-кандидата (RU-крипто-сабов мало — RU-аудитория в основном в TG; мёртвые молча отсекаются).
Тесты: `test_packs_catalog.py` — добавлен `_REDDIT_HANDLE_RE` в `_HANDLE_RE_BY_KIND` (иначе KeyError на
reddit-каналах в `test_all_handles_match_format_for_kind`) + `test_crypto_reddit_pack_is_all_reddit_kind`
(kind=REDDIT, ≥15 субов, bare+lowercase, без `r/`). ci-fast зелёный (938 passed). Integration packs-API
(`>= 2` паков, subscribe) — backward-compat, не сломан. Diff строго в scope (data.py + его тест). AC1/2/3/5
выполнены; AC4 (live validate_ref→ингест→viral_score) owner-gated ФАЗА 2. Ядро/pipeline/collector не тронуты
(collector/reddit готов в TASK-092).)
