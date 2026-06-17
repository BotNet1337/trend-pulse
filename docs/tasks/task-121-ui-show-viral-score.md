---
id: TASK-121
title: "UI: показать реальный сигнал (viral_score) на Signal Desk"
status: planned        # planned → in-progress → review → done
owner: frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: af734e86fbfcc60cfd23da4b579fc394e560aa14
branch: ""
tags: [S1, scoring-evolution, frontend, quick-win, presentational]
---

# TASK-121 — UI: показать реальный сигнал (viral_score quick win)

> S1 плана эволюции скоринга: в `/watchlists` «Live signal» показывать `viral_score` (0–100) как ОСНОВНУЮ метрику + тренд по `sparkline_24h`; velocity демотировать во вторичное (tooltip), НЕ удалять.

## Context

- Источник: [`docs/architecture/states/03-scoring-evolution-plan.md`](../architecture/states/03-scoring-evolution-plan.md) §S1 + [`01-state-current.md`](../architecture/states/01-state-current.md) §6.
- AS-IS дефицит №3 (state-01 §8): UI акцентирует velocity (`×baseline ≈0.0` на одноканальных кластерах), а `viral_score` avg≈21 / max≈47 уже посчитан и есть в API — пользователь видит «мёртвый» сигнал, хотя сигнал есть.
- Данные УЖЕ считаются: `signal_repo.aggregate_for_user` (TASK-096) уже отдаёт `live_score` (viral_score 0–100), `sparkline_24h` (почасовой max viral_score), `live_velocity`, `last_alert_at`. API-схема `WatchlistSignal` уже несёт все 4 поля. То есть это чисто presentational + выбор поля — backend/API НЕ трогаем.
- Ключевой факт (проверено grep): `live_score` присутствует в `gen.types.ts` / `openapi.json` / схеме, но **нигде не рендерится** во фронте. Бейдж в строке = только velocity (`formatVelocityBadge` → `×{n.n} baseline`). Спарклайн уже по viral_score (правильный), его не трогаем.

## Goal

На каждой строке Signal Desk (`/watchlists`) основной живой бейдж показывает `viral_score` 0–100 (а не `×0.0 baseline`). Спарклайн (уже по viral_score) остаётся. Velocity не исчезает из контракта — переезжает во вторичную подачу (tooltip бейджа score). DoD: UI НЕ показывает «×0.0», когда `viral_score>0`; нет регрессии API-контракта (`WatchlistSignal` неизменна, openapi не дрейфует).

## Discussion

Owner спит, предодобрено. Решения приняты из кода/плана (рекомендованные варианты), записаны ниже.

- Q: viral_score как ОСНОВНАЯ метрика — а velocity убрать или оставить?
  → A: оставить вторичной.
  → Decision: velocity демотируется во вторичную подачу (tooltip на score-бейдже), НЕ удаляется. (rationale: задание прямо требует «velocity demoted to secondary/tooltip (not removed) to preserve API contract». Удаление `live_velocity` сломало бы `WatchlistSignal`/openapi и потребовало бы backend-дифф — это уже не surgical и не presentational.)

- Q: где живёт изменение — backend или frontend?
  → A: только frontend.
  → Decision: backend (`signal_repo.py`, `service.py`, `schemas.py`) НЕ трогаем — поля уже есть в API. (rationale: подтверждено чтением `signal_repo.aggregate_for_user` (отдаёт `live_score`/`sparkline_24h`) и `schemas.WatchlistSignal` (поля `live_score`/`live_velocity`/`sparkline_24h`/`last_alert_at` уже объявлены). openapi.json регенерации не нужно — контракт не меняется.)

- Q: как форматировать score-бейдж и его «горячесть» (tier)?
  → A: целое 0–100; tier по порогам score.
  → Decision: новый чистый хелпер `formatScoreBadge(score)` → строка вида `{Math.round(score)}` (целое, tabular-nums; напр. `47`), `null` когда `live_score == null`. Новый `scoreTier(score)` переиспользует CSS-классы `.vel-badge.{hot,warm,calm}` (тот же визуальный язык, без нового CSS): hot ≥ alert-зона, warm — средняя, calm — низкая. Пороги — именованные константы. (rationale: viral_score 0–100, alert-порог по умолчанию из watchlist ~ score_threshold; чтобы не тащить per-row threshold в tier-логику и держать diff минимальным, берём фиксированные именованные пороги SCORE_HOT/SCORE_WARM. Числовая правда — само значение в бейдже; tier — только цвет.)

- Q: что показывать, когда `live_score == null` (нет in-window данных)?
  → A: тот же graceful-плейсхолдер, что и сейчас.
  → Decision: бейдж `vel-badge--empty` с текстом `no signal` (вместо текущего `no data`); сохраняем «никаких фейк-значений» (INV2). (rationale: повторяем уже существующий empty-паттерн строки — без нового CSS.)

- Q: куда девать velocity в строке?
  → A: в `title` (tooltip) основного score-бейджа.
  → Decision: tooltip score-бейджа = `Live signal {score}/100 · velocity ×{v.v} baseline` (velocity-часть опускается, когда `live_velocity == null`). Отдельный velocity-бейдж в ячейке убирается. (rationale: «secondary/tooltip» из задания; одна ячейка «Live signal (24h)» = спарклайн + один основной бейдж, чище и честнее.)

- Q: метка колонки в шапке таблицы?
  → A: оставить «Live signal (24h)».
  → Decision: заголовок колонки не меняем; легенда внизу страницы (`Threshold = score a topic must hit to alert`) уже корректна. (rationale: минимальный diff; «Live signal (24h)» уже описывает viral_score за 24ч.)

- Q: сортировка по score?
  → A: вне scope.
  → Decision: НЕ добавляем сорт-колонку по live_score (сейчас сортируются только `name`/`threshold`). (rationale: scope creep; quick-win = только подача. Можно отдельной задачей.)

## Scope

- Touch ONLY:
  - `frontend/src/features/watchlists/signal-desk.ts` — добавить `formatScoreBadge`, `scoreTier`, именованные пороги `SCORE_HOT_THRESHOLD`/`SCORE_WARM_THRESHOLD` (+ опц. хелпер tooltip-строки). Существующие velocity-хелперы НЕ удалять (контракт + tooltip).
  - `frontend/src/features/watchlists/watchlist-row.tsx` — рендерить score-бейдж как основной (на месте текущего velocity-бейджа), velocity → в `title`. Спарклайн без изменений.
  - `frontend/src/features/watchlists/index.ts` — экспорт новых хелперов (если они импортируются строкой/тестами; по аналогии с `formatVelocityBadge`).
  - `frontend/tests/unit/watchlists/signal-desk.spec.ts` — unit-тесты на `formatScoreBadge`/`scoreTier` + правка ожиданий по бейджу (TDD: сначала падающие).
- Do NOT touch:
  - backend: `signal_repo.py`, `api/watchlist/{service,schemas,router}.py`, любые `storage/`/`scorer/` — поля уже есть.
  - `frontend/src/shared/api/gen.types.ts` / `openapi.json` — контракт не меняется (никакой regen).
  - `frontend/src/app/app.css` — переиспользуем существующие `.vel-badge.{hot,warm,calm,--empty}` и `.spark*` (новый CSS не добавляем).
  - data fetching / queries / mutations / routes / query-keys / plan-gating — без изменений.
  - velocity-хелперы (`velocityTier`, `formatVelocityBadge`) — оставить (tooltip + API-контракт).
- Blast radius:
  - service interfaces: НЕТ (backend не тронут).
  - Celery tasks/queues: НЕТ.
  - DB schema / pgvector: НЕТ.
  - public API request/response (`WatchlistSignal`/`WatchlistRead`): НЕТ — поля уже в контракте, openapi стабилен (openapi-drift CI чек зелёный по построению).
  - Потребители фронта: только `WatchlistRow` (один компонент) + его unit-тесты.

## Acceptance Criteria

- [ ] Given watchlist с `signal.live_score = 47.4`, When строка рендерится, Then основной бейдж показывает `47` (целое 0–100), а НЕ `×0.0 baseline`.
- [ ] Given watchlist с `live_score` в hot-зоне (≥ `SCORE_HOT_THRESHOLD`), When рендерится, Then бейдж имеет класс `.vel-badge.hot`; warm-зона → `.warm`; ниже → `.calm`.
- [ ] Given watchlist с `live_velocity = 0.3` и `live_score = 47.4`, When наводят на score-бейдж, Then `title` содержит и score, и `velocity ×0.3 baseline` (velocity сохранена как вторичная, контракт цел).
- [ ] Given watchlist без in-window данных (`live_score = null`), When рендерится, Then показывается graceful-плейсхолдер (`no signal`, класс `vel-badge--empty`), без фейк-значения (INV2).
- [ ] Given любой watchlist, When рендерится, Then спарклайн (по `sparkline_24h`) рендерится как прежде (без регрессии).
- [ ] Given сборка фронта, When `tsc` + lint + vitest, Then зелёные; `gen.types.ts`/`openapi.json` НЕ изменены (контракт стабилен).
- [ ] Given прод (Playwright под суперюзером на `/watchlists`), When открыт Signal Desk, Then видны числовые score-бейджи >0 + спарклайны; `scores` в БД подтверждает значения (`viral_score>0`).

## Plan

1. `frontend/src/features/watchlists/signal-desk.ts` — добавить именованные пороги `SCORE_HOT_THRESHOLD` / `SCORE_WARM_THRESHOLD`, чистые `scoreTier(score)` (→ `VelocityTier`-совместимый union hot|warm|calm, переиспользуя CSS) и `formatScoreBadge(score)` (целое 0–100 строкой, `null` когда нет). Опц. `formatSignalTooltip(score, velocity)`. Velocity-хелперы оставить нетронутыми.
2. `frontend/tests/unit/watchlists/signal-desk.spec.ts` — (TDD, RED первым) тесты: `formatScoreBadge` (47.4→`47`, 0→`0`, null→null, NaN→null), `scoreTier` (пороги hot/warm/calm + null→calm), tooltip-строка с/без velocity.
3. `frontend/src/features/watchlists/watchlist-row.tsx` — заменить рендер velocity-бейджа на score-бейдж как основной: `const score = signal.live_score; const tier = scoreTier(score); const scoreLabel = formatScoreBadge(score);`; `title` = signal-tooltip (score + velocity). Empty-ветка → `no signal`. Спарклайн-блок без изменений. Импорты velocity-хелперов, если больше не нужны напрямую, заменить на score-хелперы (velocity всё ещё нужна для tooltip → берём `signal.live_velocity`).
4. `frontend/src/features/watchlists/index.ts` — добавить экспорт `formatScoreBadge`/`scoreTier`/пороги (по аналогии с velocity-хелперами), если они реэкспортятся барелем.
5. Verify (G2): `make` фронт-таргет (tsc+lint+vitest); подтвердить `git diff --stat` НЕ содержит `gen.types.ts`/`openapi.json`/backend; Playwright-смок на `/watchlists` + `psql` `SELECT max(viral_score) FROM scores`.

## Invariants

- API-контракт неизменен: `WatchlistSignal` несёт те же 4 поля; `gen.types.ts`/`openapi.json` без дрейфа (openapi-drift CI зелёный).
- INV2 — нет фейк-данных: `live_score == null` → плейсхолдер, не `0`/не выдуманное.
- Immutability: хелперы чистые, входные данные не мутируются.
- velocity сохранена в DTO и видна вторично (tooltip) — никакой потери информации.
- Спарклайн уже по viral_score — его смысл не меняется.
- No magic literals: пороги tier — именованные константы.

## Edge cases

- `live_score == null` (нет in-window scores) → `no signal` плейсхолдер (как текущий `no data`).
- `live_score == 0` (валидный ноль, не null) → бейдж `0` calm-tier (это РЕАЛЬНЫЙ ноль, показываем; INV2 различает null vs 0).
- `live_score` нецелое (47.4) → `Math.round` → `47`.
- `live_score` NaN/Infinity (не должно прийти из API, но guard) → трактуем как нет данных → плейсхолдер.
- `live_velocity == null`, `live_score` есть → score-бейдж рендерится, tooltip без velocity-части.
- compact-density (`.is-compact`) → бейдж/спарклайн уже стилизованы; класс-классы не меняем → деградирует как сейчас.

## Test plan

- unit (vitest, `signal-desk.spec.ts`): `formatScoreBadge`, `scoreTier`, `formatSignalTooltip` — таблицей значений (включая null/0/NaN/пороги). Правка существующих ожиданий, если бейдж-текст ассертится в row-тестах.
- component (если есть row-render тест): score-бейдж показывает число, не `×baseline`; empty → `no signal`; title содержит velocity.
- integration: НЕ требуется (backend не тронут; `signal_repo` интеграционный тест TASK-096 остаётся зелёным as-is).
- e2e/прод-факт: Playwright `/watchlists` под суперюзером — числовые бейджи >0 + спарклайны; `psql` подтверждает `viral_score>0`.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: af734e86fbfcc60cfd23da4b579fc394e560aa14
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)  — N/A (presentational, no input/auth/secrets)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial)

Key located facts (read at plan time, baseline af734e8):
- `signal_repo.aggregate_for_user` (`backend/src/storage/repositories/signal_repo.py:187`) already returns `live_score`/`sparkline_24h`/`live_velocity`/`last_alert_at` — NO backend change.
- `WatchlistSignal` (`backend/src/api/watchlist/schemas.py:127`) already declares all 4 fields — NO schema change.
- `live_score` exists in `gen.types.ts:1618` but is rendered NOWHERE in the SPA — the row badge is velocity-only (`watchlist-row.tsx:74-76,130-138`).
- Velocity helpers `velocityTier`/`formatVelocityBadge` live in `signal-desk.ts:116,128`; CSS `.vel-badge.{hot,warm,calm,--empty}` in `app.css:1912-1933` — reused, no new CSS.
- Table header column "Live signal (24h)" at `list.tsx:194` — unchanged.
</content>
</invoke>
