---
id: TASK-089
title: Twitter seed-pack «Crypto (RU+EN)» через packs-фичу + per-source handle-валидация
status: planned         # planned → in-progress → review → done
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: ""
branch: "task/089-twitter-seed-pack"
tags: [collector, twitter, packs, watchlist, twitter-loop, phase-c, C5]
deps: [031]
---

# TASK-089 — Twitter seed-pack «Crypto (RU+EN)» (ФАЗА C / C5)

> Бриф: [../research/twitter-source-research-brief.md](../research/twitter-source-research-brief.md) §6.
> Зависит от TASK-031 (collector/twitter + регистрация + storage SourceKind.TWITTER).

## Goal
Собрать pack из Twitter-аккаунтов РОВНО как pack из TG-каналов, переиспользуя существующую
packs-фичу (`api/packs/*`), НЕ плодя новую сущность. Аккаунт = `PackChannel(handle, kind=TWITTER)`.
Перед добавлением — провалидировать каждый через `TwitterCollector.validate_ref()`; невалидные
отсечь с причиной (лог + отчёт). Цель ~20-30 живых.

## Discussion (дефолты)
- packs УЖЕ поддерживают `PackChannel.kind` (default TELEGRAM) → Twitter-pack = новый `PackDef` с
  `kind=TWITTER`. Подписка создаёт watchlist-строки тем же `service.subscribe`.
- Валидация handle: Twitter username 1-15 [A-Za-z0-9_] (per-source `TWITTER_HANDLE_PATTERN`,
  пререквизит из TASK-031 §4). В data.py хранить без '@'.
- live-`validate_ref` требует реального `TWITTER_BEARER_TOKEN` → **owner-gated**: до ключа фиксируем
  список-кандидатов + код/тесты на моках; живой прогон (валидация→pack→ингест→viral_score) —
  следующая итерация по появлению ключа (MANUAL-TODO).
- Кандидаты (валидировать, оставить живых, переименованных/мёртвых — в отчёт):
  - EN: @VitalikButerin @balajis @saylor @APompliano @CryptoHayes @cobie @Pentosh1 @woonomic
    @WClementeIII @100trillionUSD @rektcapital @CryptoKaleo @intocryptoverse @RyanSAdams
    @TrustlessState @cburniske @haydenzadams @StaniKulechov @ErikVoorhees @lopp @gavofyork
    @MessariCrypto @glassnode @santimentfeed @DefiLlama @lookonchain @WhaleAlert @WatcherGuru
    @Cointelegraph @CoinDesk @TheBlock__
  - RU: @forklog @rbc_crypto @incrypted @bitsmedia_ru @prostocoin @hashtelegraph @bccnews
    @Cryptorussia @profinvestment @coinpost_ru @ru_holderlab @cryptohacker_ru

## Acceptance Criteria
- AC1: новый `PackDef(slug="crypto-twitter", topic="crypto", channels=(PackChannel(.., kind=TWITTER)…))`
  в `api/packs/data.py`; финальный валидированный список зафиксирован в docs/ (RU/EN + почему).
- AC2: per-source handle-валидация (`TWITTER_HANDLE_PATTERN`) в watchlist-create — Twitter-handle
  принимается, телеграм-валидатор не ломается.
- AC3: подписка на pack создаёт watchlist-строки с `source_kind=twitter`; backward-compat TG packs.
- AC4 (owner-gated, live): прогон `validate_ref` по кандидатам, отсев мёртвых в отчёт; ингест по
  pack'у → посты с `viral_score`. До ключа — на моках; живой — следующей итерацией.
- AC5: тесты ≥80% нового кода; `make ci-fast` зелёный; ядро/pipeline не тронуты.

## Verify
- unit: pack-определение валидно, handle-валидатор per-source; subscribe создаёт twitter-watchlist
  (мок). live behavioral — owner-gated MANUAL-TODO (нужен `TWITTER_BEARER_TOKEN`).

## Checkpoints
current_step: plan
- [x] plan (this doc, из ФАЗЫ B)
- [ ] do (TDD)
- [ ] verify
- [ ] ship (PR)
