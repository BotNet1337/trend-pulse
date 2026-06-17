---
id: TASK-126
title: Источник-независимость — eff-independent-sources фича + бейдж (S5)
status: planned        # planned → in-progress → review → done
owner: backend         # backend + frontend (cross-cutting; backend-led)
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 87fefce49f552c8c0a137549f8655ab9ed329ecd
branch: ""
tags: [scoring-evolution, S5, moat, independence, watchlists, openapi]
---

# TASK-126 — Источник-независимость: eff-independent-sources фича + видимый бейдж

> Считать `effective_independent_sources = exp(entropy of post distribution across channels)` для
> кластера (РЕЮЗ `eval/science_features`), персистить на `Score`, отдать как поле `WatchlistSignal` и
> отрисовать как маленький independence-бейдж в `/watchlists`. Честно: это сигнал НЕЗАВИСИМОСТИ
> (органик vs концентрация), НЕ детектор координации.

## Context

S5 из плана эволюции скоринга ([`03-scoring-evolution-plan.md` §S5](../architecture/states/03-scoring-evolution-plan.md),
рек. D4.1 в [`02-state-target.md` §D4](../architecture/states/02-state-target.md)). `effective_independent_sources`
уже реализован и unit-покрыт в `eval/science_features.py` (TASK-113); standalone PR-AUC 0.831 на Higgs, но
**marginal lift над base-GBDT ≈0** — фича ждёт ре-замера на TG B1, где ожидаемо важнее (coordinated
single-source amplification = именно тот шум, что фильтрует продукт).

Research-честность (RQ3, [`scoring-target-research.md`](../research/scoring-target-research.md)): независимость
**доказана как предиктор ОРГАНИКИ** (Ugander 2012, Weng 2013), CIB-фреймворк (Pacheco 2021) использует её как
НУЛЕВУЮ гипотезу — но end-to-end детектор координации как single-metric **НЕ валидирован** ([INFERENCE]).
Известный false-positive: настоящая вирусность выглядит как координация. → НЕ ship-ить independence-only;
парить (концептуально, в этой задаче — документально) с synchrony/similarity-нулём как будущий шаг.

Прецеденты пути данных, которые эта задача расширяет (НЕ супершедит):
- **TASK-096** — `WatchlistSignal` + `signal_repo.aggregate_for_user` (per-channel агрегат `Score`/`Alert`).
- **TASK-121** — frontend-бейдж `viral_score` на той же строке (CSS `.vel-badge`, чистые хелперы в `signal-desk.ts`).
- **TASK-124/125** — паттерн «РЕЮЗ pure-fn из `eval.science_features`, НЕ реимплем» + «shadow-сигнал сначала,
  вес в score позже / owner-gated».

## Goal

`effective_independent_sources` кластера:
1. **(a) Сигнал для скорера** — посчитан на тике из per-channel событий (`events` уже в `_build_score_inputs`),
   персистится на `Score` (новая nullable колонка `effective_sources`) как наблюдаемый/логируемый сигнал;
2. **(b) Видимый бейдж** — отдан как nullable поле `WatchlistSignal.effective_sources`, отрисован маленьким
   trust-чипом «N independent sources» в `watchlist-row.tsx`.

**DoD:** independence виден в UI (Playwright: чип рендерится с реальным N) И входит в скоринг-наблюдаемость
(персистится на `Score`, лог `model_choice`-стиля не требуется — значение на строке). Парный baseline
синхронности задокументирован как следующий шаг (НЕ реализуется здесь). Score-веса НЕ меняются (badge +
shadow signal сейчас; взвешивание — отдельная owner-gated задача). Leak-free, no Any, no magic literals,
bounded. openapi/gen.types регенерированы (новое API-поле) → нет дрейфа в CI.

## Discussion
<!-- durable record of clarifications; autonomous PLAN — decisions resolved from code/docs -->

- Q: Откуда брать per-channel распределение для `exp(entropy)`? → A: Из `events: tuple[ScoreEvent,...]`,
  которые `_build_score_inputs` УЖЕ строит из загруженных in-window постов (`epoch`+`channel_id`, TASK-124) —
  никакого нового запроса/миграции для входных данных. → **Decision:** маппить каждый `ScoreEvent`→`TimedEvent
  (epoch, source_id=channel_id, weight=1)` и вызвать `effective_independent_sources(events)` из
  `eval.science_features` (РЕЮЗ, НЕ реимплем — как `_temporal` в `score.py`). (rationale: смежно с уже
  посчитанным temporal-термом; per-cluster post-counts уже в руках.)

- Q: Где считать — read-path (`signal_repo`) или scoring-time (`scorer/tasks.py`) + персист на `Score`? →
  A: **Scoring-time + персист на `Score`** (Option B). → **Decision:** добавить nullable колонку
  `scores.effective_sources` (Float, nullable — graceful для до-миграционных строк), считать в `_persist_score`
  из `inputs.events`, читать в `signal_repo` ровно как читается `velocity`. (rationale: это scoring-time фича
  (как `velocity`/`channels_count`), а не презентационный дериватив; матчит TO-BE-таблицу `scores: p_grow,
  independence, components`; даёт стабильное значение строке без расходящегося пересчёта в read-path; signal_repo
  уже селектит конкретные колонки `Score` — добавить одну тривиально. Read-path-only (Option A) потребовал бы
  НОВЫЙ grouped-count запрос постов в `signal_repo` и считал бы значение, расходящееся с тем, что видит scorer.)

- Q: Сразу включать в `viral_score` веса (множитель/4-й член)? → A: **НЕТ.** → **Decision:** только бейдж +
  персистированный сигнал. Взвешивание в score — **DEFERRED / owner-gated** (требует ре-валидации через
  S0 eval-gate, риск того же over-claim «Higgs≠TG»; D4: «не ship-ить independence-only»; marginal lift на Higgs
  ≈0). (rationale: меняя веса, мы трогаем алерты — owner-gate из плана §Owner-gates S4/S5; консервативно сначала
  делаем видимым/наблюдаемым, измеряем на TG B1, взвешиваем потом.)

- Q: Как назвать API-поле — `independence` или `effective_sources`? → A: **`effective_sources`** (Float|null). →
  **Decision:** имя матчит фичу `effective_independent_sources` и колонку `scores.effective_sources`; короче для
  badge-лейбла. (rationale: одно имя сквозь слои — модель→schema→openapi→gen.types→UI; меньше когнитивной
  нагрузки чем синоним `independence`.)

- Q: Что показывать в бейдже и как трактовать число? → A: «N independent sources», где N = `Math.round(effective_sources)`
  (effective number ≈ N независимых каналов; коллапсирует к 1 при single-source amplification). → **Decision:**
  чип рендерится ТОЛЬКО когда `effective_sources != null && >= MIN_INDEPENDENCE_DISPLAY` (порог-константа,
  напр. 2.0 — single-source ≈1 не показываем как «trust»); иначе ничего/нейтрально. Tooltip честный:
  «N effective independent sources (organic spread signal, not a coordination verdict)». (rationale: честная
  рамка RQ3 прямо в UI; не плодим «1 independent source» шум на 77% single-channel кластеров.)

- Q: openapi-drift CI? → A: Новое поле в `WatchlistSignal` → `make gen-openapi gen-types` ОБЯЗАТЕЛЕН, иначе
  `openapi-drift-check` (pr-checks.yml) красный. → **Decision:** в ship-шаге выполнить `make gen-openapi gen-types`
  и закоммитить `frontend/src/shared/api/openapi.json` + `gen.types.ts` ВМЕСТЕ с кодом (single-PR-контракт). FE
  `model.ts` тип `WatchlistSignal` дериватив от gen.types → автоматически получит поле.

- Q: Парный baseline синхронности — в этой задаче? → A: **НЕТ**, документируется как следующий шаг (D4.2–D4.4:
  co-forwarding граф / temporal-synchrony z-score / content-similarity null итеративно). → **Decision:** в DoD и
  в комментарии у фичи зафиксировать «independence ≠ coordination detector; pair with synchrony/similarity-null
  next» — durable, кандидат в ADR на learnings-шаге если решим.

## Scope

- **Touch ONLY:**
  - `backend/src/storage/models/scores.py` — `effective_sources: Mapped[float | None]` (Float, nullable).
  - `backend/migrations/...` — новая Alembic-миграция (следующий номер, ← последняя head): add nullable column
    `scores.effective_sources`.
  - `backend/src/scorer/tasks.py` — в `_persist_score`: посчитать `effective_independent_sources` из
    `inputs.events` (РЕЮЗ `eval.science_features`), записать в insert + on_conflict set_.
  - `backend/src/api/watchlist/schemas.py` — `WatchlistSignal.effective_sources: float | None = None`.
  - `backend/src/storage/repositories/signal_repo.py` — `WatchlistSignalData.effective_sources` + select колонки
    `Score.effective_sources` + протащить в `_build_signal` (берётся с того же latest-score-point).
  - `backend/src/api/watchlist/service.py` — `_to_signal`: смаппить новое поле.
  - `frontend/src/shared/api/openapi.json` + `frontend/src/shared/api/gen.types.ts` — РЕГЕН (`make gen-openapi gen-types`).
  - `frontend/src/features/watchlists/signal-desk.ts` — чистые хелперы `formatIndependenceBadge` +
    `MIN_INDEPENDENCE_DISPLAY` + tooltip; `rowSignal` fallback расширить полем.
  - `frontend/src/features/watchlists/watchlist-row.tsx` — отрисовать independence-чип.
- **Do NOT touch:**
  - `eval/science_features.py` — фича готова, РЕЮЗ as-is (НЕ реимплем, НЕ менять сигнатуру).
  - `scorer/score.py` `compute_components` / веса `0.55/0.30/0.15` — score-веса НЕ меняются (D4 deferred).
  - Кластеризация, alert-логика, `viral_model.py`, B1-снапшоты, любые другие S-задачи.
  - Synchrony/co-forwarding/similarity-null — следующий шаг, НЕ здесь.
- **Blast radius:**
  - **Schema/migration:** одна nullable колонка `scores.effective_sources` (graceful NULL для старых строк;
    server_default НЕ нужен — nullable). Миграция round-trip на pgvector:pg16.
  - **Public API:** `WatchlistSignal` += nullable поле → openapi-drift → `make gen-openapi gen-types` (MANDATORY).
  - **Consumers:** `signal_repo.aggregate_for_user` (+1 selected column, тот же grouped-query — без N+1);
    `service._to_signal` (+1 маппинг). Никаких Celery-контрактов / event-схем не трогаем.
  - Scorer-тик: +1 pure-вызов на кластер из уже-загруженных `events` (без нового запроса).

## Acceptance Criteria

- [ ] **AC1 — компьют (РЕЮЗ).** Given кластер с in-window постами на ≥2 каналах, When `_persist_score` бежит,
  Then `scores.effective_sources` = `effective_independent_sources(events)` из `eval.science_features` (РЕЮЗ,
  не реимплем), bounded ≥ 0, и `exp(entropy)` ≈ распределению постов по каналам (single-source → ≈1.0).
- [ ] **AC2 — графейс/leak-free.** Given кластер без `events` (пустой stream, fallback-консьюмеры) или
  single-channel, When скоринг, Then `effective_sources` = `0.0`/`1.0` корректно (НЕ NULL из-за ошибки, НЕ
  падение); до-миграционные строки `Score` читаются как `None` без регресса.
- [ ] **AC3 — API-поле.** Given юзер с watchlist, чьи кластеры скорены, When `GET /watchlists`, Then каждый
  `signal` несёт `effective_sources: float | null` (null когда нет in-window score), значение = latest-in-window
  `Score.effective_sources`; openapi.json/gen.types содержат поле (CI `openapi-drift-check` зелёный).
- [ ] **AC4 — бейдж.** Given строка с `effective_sources >= MIN_INDEPENDENCE_DISPLAY`, When `/watchlists`
  рендерится (Playwright), Then виден чип «N independent sources» (N = round) с честным tooltip; Given
  `effective_sources` null или `< MIN_INDEPENDENCE_DISPLAY`, Then чип НЕ показывается (нейтрально, не «1 source»).
- [ ] **AC5 — score целостность.** Given любой вход, When скоринг, Then `viral_score` БАЙТ-в-байт как до задачи
  (independence НЕ входит в веса) — `compute_components` не тронут; алерт-порог/логика неизменны.
- [ ] **AC6 — честность.** Given код/доки, Then у фичи и в DoD зафиксировано «independence ≠ coordination
  detector; organic-spread signal; pair with synchrony next» (RQ3); UI-tooltip не обещает «детектор накрутки».

## Plan

1. `backend/src/storage/models/scores.py` — добавить `effective_sources: Mapped[float | None] = mapped_column(Float, nullable=True)`
   (комментарий: exp(source-entropy), independence signal, не входит в viral_score — D4 deferred).
2. `backend/migrations/<next>_add_scores_effective_sources.py` — Alembic add nullable column (down = drop);
   `down_revision` = текущая head.
3. `backend/src/scorer/tasks.py` `_persist_score` — посчитать `eff = effective_independent_sources([TimedEvent(...)
   for e in inputs.events])` (импорт из `eval.science_features`, маппинг как в `score._temporal`), записать в
   `pg_insert(...).values(...)` И в `on_conflict_do_update(set_=...)`. (pure, без нового запроса.)
4. `backend/src/api/watchlist/schemas.py` — `WatchlistSignal.effective_sources: float | None = None` + docstring-строка.
5. `backend/src/storage/repositories/signal_repo.py` — `WatchlistSignalData.effective_sources: float | None = None`;
   `_scores_by_cluster` select += `Score.effective_sources` (расширить tuple); `_build_signal` берёт его с latest
   score-point (как `live_velocity`); пробросить в DTO.
6. `backend/src/api/watchlist/service.py` `_to_signal` — `effective_sources=data.effective_sources`.
7. `make gen-openapi gen-types` — регенерировать `openapi.json` + `gen.types.ts`; закоммитить.
8. `frontend/src/features/watchlists/signal-desk.ts` — `MIN_INDEPENDENCE_DISPLAY = 2.0`;
   `formatIndependenceBadge(eff): string | null` (round, gate на порог); `formatIndependenceTooltip`; расширить
   `rowSignal` fallback-объект полем `effective_sources: null`.
8. `frontend/src/features/watchlists/watchlist-row.tsx` — прочитать `signal.effective_sources`, отрисовать чип
   (переиспользуя существующий бейдж-CSS-язык; trust-вариант) когда label !== null.

## Invariants

- `viral_score` и его компоненты НЕ меняются (AC5) — independence вне формулы.
- `effective_sources` ≥ 0, finite; single-source → ≈1.0; никогда не падает скоринг из-за этой фичи
  (как B1-снапшоты — данные best-effort, но здесь это часть `_persist_score`, поэтому компьют — pure и
  total на любых `events`, включая пустые).
- Read-path без N+1 — то же число grouped-queries в `aggregate_for_user` (только +1 selected column).
- Leak-free: `events` — те же in-window посты, из которых уже считаются агрегаты (нет post-T_obs).
- No Any, no magic literals (порог дисплея — именованная константа), immutable DTO, ошибки не глотать.

## Edge cases

- Пустой `events` (offline/fallback-консьюмер вызвал бы `_persist_score`? — нет, только scorer-тик строит
  `events`; но total-guard) → `effective_independent_sources([]) == 0.0`. → персистим `0.0`.
- Single-channel кластер (все посты 1 канал) → entropy=0 → `exp(0)=1.0`. → персистим `1.0`; бейдж НЕ показывается
  (`< MIN_INDEPENDENCE_DISPLAY`).
- До-миграционные `Score`-строки → колонка NULL → `WatchlistSignalData.effective_sources=None` → API `null` →
  бейдж нейтрально скрыт. Без регресса.
- Out-of-range/нечисловое из БД (не должно случиться) → frontend `formatIndependenceBadge` гардит
  `Number.isFinite` → null (как `formatScoreBadge`).
- Несколько score-points у канала → берём latest (тот же `max(points, key=computed_at)`, что для `live_score`).

## Test plan

- **unit (backend):**
  - scorer: `_persist_score` пишет `effective_sources` = ожидаемое `exp(entropy)` для multi-channel events;
    single-channel → 1.0; пустые events → 0.0 (если конструируемо). Reuse-проверка: значение == прямой вызов
    `effective_independent_sources` (не дрейфует).
  - signal_repo: `aggregate_for_user` отдаёт `effective_sources` с latest score; None когда нет score; без N+1
    (фикс число запросов).
  - schema: `WatchlistSignal` сериализует `effective_sources` null и число; `extra="forbid"` цел.
- **unit (frontend):** `signal-desk.ts` — `formatIndependenceBadge`: null при null/нефинит/`<MIN`; «N» при `>=MIN`;
  `rowSignal` fallback несёт `effective_sources: null`.
- **integration (backend):** миграция round-trip (pgvector:pg16) up/down; `GET /watchlists` E2E-вью отдаёт поле.
- **e2e (Playwright):** `/watchlists` под суперюзером — independence-чип рендерится для multi-channel строки с
  реальным N (AC4); honest tooltip присутствует.
- **regression-gate:** `viral_score` тесты зелёные без изменений (AC5); `make openapi-drift-check` зелёный (AC3).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: 87fefce49f552c8c0a137549f8655ab9ed329ecd
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + lint + typecheck + runtime + real behavior: Playwright чип + psql `scores.effective_sources`)
- [ ] 5 review (auto, adversarial — другой моделью)
- [ ] 5.5 security (N/A — no auth/input/secrets; skip unless review flags)
- [ ] 6 ship (confirm plan done → PR; ОБЯЗАТЕЛЬНО `make gen-openapi gen-types` закоммичен)
- [ ] 7 learnings (auto; кандидат ADR: independence-pair-with-synchrony durable decision)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial)
</content>
