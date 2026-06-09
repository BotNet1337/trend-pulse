---
id: TASK-038
title: Curated channel packs — каталог наборов, GET /packs, подписка в 1 клик вне лимита CHANNELS
status: planned
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e1, backend, frontend, watchlist, billing]
---

# TASK-038 — Curated channel packs (Epic E1)

> Снять проблему «не знаю, какие каналы добавить» и холодный старт метрики across-каналов:
> готовые наборы («Crypto RU», «Tech», …) подключаются одним кликом. Основа для onboarding
> (TASK-039) и Free-воронки (E5).

## Context

`Watchlist` = (user_id, channel_id, topic, threshold, min_channels, lang), unique (user_id, channel_id, topic).
`Channel` глобален (source_kind, handle) — пак из 30 каналов читается коллектором **один раз на всех**
(cross-tenant dedup, ADR-002) → паки почти не добавляют нагрузку на пул. Лимиты:
`billing.assert_within_limit(.., Resource.CHANNELS)` — Free=5/Pro=100/Team=500; пак на Free не влез бы
в лимит, а E1 требует «Free = доступ к наборам». Миграции: последняя `0010_api_keys.py`.
Watchlist API: `api/watchlist/{router,schemas,service}.py` — эталон структуры фичи.

## Goal

`GET /packs` отдаёт каталог наборов (slug, название, тема, число каналов); `POST /packs/{slug}/subscribe`
одним вызовом создаёт watchlist-строки пака (помеченные `pack_slug`), которые **не считаются** в
`Resource.CHANNELS`; лимитируется число подключённых паков (Free=1, Pro/Team=5 — константы в plans.py);
`DELETE /packs/{slug}/subscribe` отключает пак целиком. Frontend: страница/блок «Наборы» + кнопка
подключения. DoD = AC.

## Discussion
- Q: Пак = отдельная сущность или bulk watchlist-строки? → Decision: **bulk watchlist-строки с маркером
  `watchlists.pack_slug: str | NULL`** (миграция NNNN). Pipeline/scorer/collector не трогаем вообще —
  они видят обычные watchlist'ы. Альтернатива (pack_subscriptions + виртуальные watchlist) отвергнута:
  больший blast radius на scorer.
- Q: Откуда каталог? → Decision: статическая curated-data в коде `api/packs/data.py` (tuple of frozen
  dataclass: slug, title, topic, channels[(handle, kind)], default AlertConfig) — паки меняются PR'ом,
  никакой админки сейчас. Первые паки: `crypto-ru` (~30 каналов), `tech-en` (~20) — состав подбирает owner,
  в коде — плейсхолдер-структура + 2 реальных пака минимум.
- Q: Лимиты? → Decision: pack-строки исключаются из `_channel_usage` (фильтр `pack_slug IS NULL`);
  новый `Resource.PACKS` в plans.py: Free=1, Pro=5, Team=5 (константы). Это сознательное продуктовое
  правило E1/E5: паки — ценность Free-воронки.
- Q: Дубли (юзер уже следит за каналом из пака руками)? → Decision: при subscribe строки с конфликтом
  unique (user_id, channel_id, topic) пропускаются (skip, не ошибка) — отчёт в ответе (created/skipped).
- Q: Update состава пака после подписки? → Decision: вне scope (нет синка); отписка+подписка обновляет.
  Зафиксировать как известное ограничение.

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/NNNN_watchlist_pack_slug.py` — **новая**: nullable `watchlists.pack_slug`
    (varchar 64) + index (user_id, pack_slug).
  - `backend/src/storage/models/watchlists.py` — поле `pack_slug`.
  - `backend/src/api/packs/` — **новый модуль**: `data.py` (каталог), `schemas.py`, `router.py`, `service.py`
    (subscribe = bulk-insert со skip-дублями, в одной транзакции; unsubscribe = delete by (user_id, pack_slug)).
  - `backend/src/billing/plans.py` — `Resource.PACKS` + лимиты; `billing/limits.py` — usage по distinct
    pack_slug; `_channel_usage` — фильтр `pack_slug IS NULL`.
  - `backend/src/api/main.py` — include router.
  - frontend: `frontend/src/features/packs/` + блок на странице watchlists (список паков, подключить/отключить);
    `gen.types.ts` регенерация (`make gen-openapi` + `npm run gen:api`).
  - tests: `backend/tests/integration/test_packs_api.py` (**новый**), unit на limits-фильтр;
    frontend unit на блок паков.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** collector/pipeline/scorer (паки для них — обычные watchlist+channel), alerts, auth.
- **Blast radius:** миграция watchlists (+nullable колонка — безопасно); изменение `_channel_usage`
  (поведение для всех существующих юзеров НЕ меняется — у них pack_slug NULL); новый публичный API;
  OpenAPI/gen.types drift. Каналы паков добавляются в глобальный сбор — нагрузка на пул +N каналов
  однократно (мониторится TASK-035).

## Acceptance Criteria
- [ ] **AC1 — каталог (failing-test anchor).** Given юзер (любой план), When `GET /packs`, Then список
  паков (slug/title/topic/channels_count) из data.py. RED первым.
- [ ] **AC2 — подписка в 1 клик.** Given Free-юзер без паков, When `POST /packs/crypto-ru/subscribe`,
  Then созданы watchlist-строки с `pack_slug='crypto-ru'` для всех каналов пака (channels создаются/
  дедуплицируются глобально), ответ {created, skipped}; повторный вызов идемпотентен (created=0).
- [ ] **AC3 — лимит паков, не каналов.** Given Free-юзер с 1 паком, When подписка на второй, Then 402
  PlanLimitExceeded (PACKS); при этом его ручной лимит CHANNELS=5 НЕ съеден паком (`_channel_usage`
  игнорирует pack-строки) — проверено созданием 5 ручных watchlist после подписки.
- [ ] **AC4 — отписка.** Given подписанный пак, When `DELETE /packs/{slug}/subscribe`, Then все строки
  пака удалены, ручные watchlist не тронуты; 404 на неизвестный slug.
- [ ] **AC5 — tenant-scope.** Given юзер A подписан, When юзер B смотрит свои watchlist/паки, Then
  данных A не видно (существующий get_tenant_user_id-паттерн).
- [ ] **AC6 — frontend + G2.** Given dev-стек, When юзер жмёт «Подключить» на паке, Then watchlist-список
  пополнился, лимит-UX корректен (402 → понятное сообщение); `make ci` зелёный, gen.types без drift.

## Plan
1. **RED:** `test_packs_api.py` — AC1–AC5 (integration, db_session).
2. Миграция NNNN + модель (`pack_slug`).
3. `api/packs/` (data 2 пака, schemas, service bulk-subscribe со skip, router) + include в main.
4. `plans.py` `Resource.PACKS` + `limits.py` (packs-usage, channels-фильтр).
5. GREEN; `make gen-openapi` → frontend packs-фича + gen.types.
6. G2 через `make up` (реальная подписка, канал пака собирается); tasks-index на ship.

## Invariants
- Pipeline/scorer/collector не знают про паки (видят обычные watchlist) — ядро не тронуто.
- `assert_within_limit` остаётся единственной точкой enforcement (ADR-003); PACKS идёт через неё.
- Существующие юзеры/лимиты не меняют поведение (pack_slug NULL).
- Subscribe — одна транзакция: либо пак подключён, либо нет (skip-дубли не ломают атомарность).
- Каталог — иммутабельные структуры, без magic literals (handles — данные, не литералы логики).

## Edge cases
- Канал пака с невалидным/умершим handle → validate при subscribe НЕ дёргаем Telegram на каждый канал
  (паки curated, проверены при добавлении в data.py PR-ревью); коллектор и так скипает мёртвые.
- Пак подключён, юзер удалил одну строку пака руками → допустимо; отписка удалит остальные.
- Тот же канал в двух паках → разные topic/pack_slug → unique не конфликтует; channels глобально дедуплицированы.
- Free-юзер с паком даунгрейдится/экспайрится → пак остаётся (Free=1 пак разрешён) — ничего не делаем.

## Test plan
- **integration:** `test_packs_api.py` — AC1–AC5 + идемпотентность + 402-коды.
- **unit:** limits — `_channel_usage` фильтр, packs-usage; data.py — валидность каталога (slug уникальны, handles валидного формата).
- **frontend unit:** блок паков (список, подключение, 402-обработка).
- **G2:** `make up` → подписка реальным юзером → канал пака появляется в сборе; OpenAPI drift-check.
- **security (5.5):** input — slug по белому списку каталога (404 иначе); rate-limit существующий; tenant-scope AC5.

## Checkpoints
current_step: 3
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (user input/limits — применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — locate: Channel глобален + cross-tenant dedup → паки дёшевы для пула; unique (user_id, channel_id, topic) определяет skip-семантику; `assert_within_limit` — единственная точка лимитов (ADR-003) — расширяем Resource, не обходим; миграционный паттерн NNNN_slug. Решение «bulk-строки с pack_slug» выбрано как минимальный blast radius (ядро не тронуто). Состав первых паков — за owner'ом до ship.)
