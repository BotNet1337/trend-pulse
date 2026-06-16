---
id: TASK-124
title: S3 — velocity/acceleration: заменить дегенеративный velocity на EWMA (temporal-терм)
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 75bd7ed
branch: ""
tags: [scorer, velocity, ewma, acceleration, breadth-velocity, signal-quality, scoring-evolution, S3]
---

# TASK-124 — S3 velocity/acceleration: дегенеративный velocity → EWMA temporal-терм

> Заменить дегенеративный `velocity`-член скорера на **bounded temporal-терм** из
> EWMA-acceleration (положительная часть) + breadth-velocity (реюз чистых функций
> `eval/science_features.py`), сохранив 3-членную форму и веса 0.55/0.30/0.15;
> score остаётся bounded [0, 100]. Re-валидация через S0 eval-gate ПЕРЕД деплоем.

## Context

- План эволюции скоринга: [`states/03-scoring-evolution-plan.md` §S3](../architecture/states/03-scoring-evolution-plan.md)
  + рекомендация **D3 вариант 6** (две фичи: EWMA-accel + breadth-velocity) в
  [`states/02-state-target.md` §D3](../architecture/states/02-state-target.md).
- AS-IS дефект (state-01 §3/§8 + [TASK-086](./task-086-fix-velocity-degeneration.md)):
  текущий `velocity = log1p(max(Δch−1,0))/max(Δhours,1h)/BURST_SCALE` на **сыром**
  корпусе даёт AUC≈0.07 (degenerate); single-channel zero-window раньше → ≈max
  (TASK-086 уже частично смягчил: 1 канал → 0, clamp 1h, BURST_SCALE-бounded → real
  AUC 0.564→0.859). Но член ОСТАЁТСЯ ≈0 на реальных кросс-канальных историях (34/35
  judged-кластеров одноканальны) и не несёт темпорального сигнала: Cheng 2014 —
  темпоральные фичи доминируют, а у нас temporal-член — мёртвый.
- **TASK-086 НЕ супершедится, а РАСШИРЯЕТСЯ:** 086 убрал ложную velocity у одиночных
  постов; 124 заменяет сам член на осмысленный temporal-сигнал (EWMA-accel +
  breadth-velocity). После 124 `_velocity` (старый burst) удаляется как формульный
  член, но breadth-семантика «расхождение по каналам» сохраняется внутри нового терма.
- Готовые pure-функции уже есть и юнит-тестированы (offline, TASK-113):
  `eval/science_features.py` — `ewma_acceleration` (строки 87–106), `breadth_velocity`
  (109–120), `TimedEvent` (46–63). **НЕ реимплементировать — импортировать.**
- S0 eval-gate (TASK-122, `scripts/eval_gate.py` + `eval/online_gate.py`) — инструмент
  re-валидации: текущая baseline-цифра качества v2 на TG B1 (judged ROC-AUC 0.859;
  PR-AUC per окно). S3 не должна её регрессировать.

## Goal

Temporal-член скорера перестаёт быть дегенеративным/мёртвым: он = **bounded [0,1]
комбинация EWMA-acceleration (положительная часть) + breadth-velocity**, вычисленная из
per-post события (timestamp + channel_id) кластера. 3-членная форма и веса
(engagement 0.55 / cross_channel 0.30 / temporal 0.15) НЕ меняются — наименьший радиус,
веса остаются валидированными (state-02 §4). Score bounded [0, 100], leak-free, без Any
и magic-literals. **DoD-гейт: S0 eval-gate на B1 НЕ регрессирует** PR-AUC/ROC-AUC vs
текущей формулы (target: ROC-AUC не ниже текущих 0.859 на judged; PR-AUC per окно
stable/лучше на B1).

## Discussion
<!-- durable record; recommended option выбран автономно из кода/доков -->

- Q: Сохранить 3-членную форму (заменить velocity на temporal) ИЛИ разбить на 2 члена
  с ре-нормализацией весов? → A: **СОХРАНИТЬ 3-членную форму** — заменить под-член
  `velocity` на `temporal`, вес 0.15 не меняется. → Decision: smallest blast radius;
  веса 0.55/0.30/0.15 эмпирически валидированы (ROC-AUC 0.91–0.93 на eval, state-02 §4),
  разбивка на 2 члена потребовала бы ре-нормировки и новой валидации всех весов.
  Rationale: D3-рек-6 говорит «две фичи» в контексте **GBDT-вектора** (S4), а НЕ
  формулы; в bounded-формуле обе фичи объединяются в один bounded temporal-член.

- Q: Точная формула temporal-члена? → A:
  `temporal = clamp( ACCEL_WEIGHT · norm_accel + BREADTH_WEIGHT · norm_breadth , 0, 1 )`,
  где (внутренние веса суммируются в 1.0, именованные константы):
  - `norm_accel = min( max(ewma_acceleration(events), 0) / ACCEL_SCALE , 1 )` —
    положительная часть ускорения (decay → 0, не штрафуем отрицательным вкладом, член
    остаётся ≥0); `ACCEL_SCALE` — named scale (события/час), бьёт верхнюю границу.
  - `norm_breadth = min( breadth_velocity(events) / BREADTH_SCALE , 1 )` —
    distinct-каналов/час; `BREADTH_SCALE` — named scale (каналов/час).
  → Decision: каждая под-фича нормирована в [0,1] делением на именованный scale и
  clamp; их выпуклая комбинация → bounded [0,1]; член ведёт себя монотонно по обеим.
  Rationale: bounded гарантирует `temporal·0.15` не доминирует (инвариант v2); accel
  положительной частью отражает «разгоняется» (Cheng), breadth — «расходится по
  каналам» (моат, сохраняет семантику старого velocity).

- Q: Откуда брать per-post события для EWMA? `ScoreInputs` сейчас несёт только
  агрегаты (`delta_hours`, `delta_channel_count`), НЕ event-stream. → A:
  Добавить на `ScoreInputs` **опциональное** поле `events: tuple[ScoreEvent, ...] = ()`
  (frozen dataclass `ScoreEvent(epoch: float, channel_id: int)`), которое
  `_build_score_inputs` заполняет из уже-загруженных постов (`p.posted_at.timestamp()`,
  `p.channel_id`). → Decision: поле ОПЦИОНАЛЬНОЕ с дефолтом `()` — все офлайн-консьюмеры
  `ScoreInputs` (`scoring_replay`, `online_gate.snapshot_to_score_inputs`,
  `viral_model.FormulaFallbackModel`, `scenarios`, `eval_gate`) НЕ ломаются: при пустом
  event-stream temporal-член считается из агрегатов-fallback (см. ниже), как сегодня.
  Rationale: per-post timestamps уже есть в `_build_score_inputs` (`earliest`/`latest`
  считаются из `posted_at`) — НЕ нужен новый запрос/миграция/индекс. Не делаем поле
  обязательным → нулевой blast radius на офлайн-консьюмеров.

- Q: B1-снапшоты (`cluster_feature_snapshots`) НЕ хранят per-post event-stream (только
  агрегаты: `distinct_channels`, `age_seconds`, готовый `breadth_velocity`). Значит
  eval-gate НЕ может вычислить EWMA-acceleration из B1. Как re-валидировать? → A:
  **Graceful-degradation fallback в temporal-терме**: когда `events` пуст, temporal
  считается ТОЛЬКО из breadth-части по агрегатам — `breadth = delta_channel_count /
  max(delta_hours, BURST_FLOOR_HOURS)`, нормировка та же (`/BREADTH_SCALE`, clamp);
  accel-часть = 0 (нет event-stream → ускорение не определено). → Decision: eval-gate
  через `snapshot_to_score_inputs` (events=()) измеряет breadth-половину temporal-члена
  — это и есть честная re-валидация под-сигнала, доступного из B1; accel-половина
  замеряется только live на проде (psql по `scores`) + остаётся под покрытием
  unit-тестов с явным event-stream. Rationale: единый источник формулы остаётся
  `scorer/score.py` (online_gate реюзит `compute_components`, ничего не реимплементирует);
  честный caveat в репорте: «eval-gate exercises breadth-half; accel-half — live-only».

- Q: `Score.velocity` колонка + `ScoreComponents.velocity` поле — переименовывать? → A:
  **НЕТ.** Поле `ScoreComponents.velocity` и колонка `scores.velocity` остаются по
  имени (теперь несут значение temporal-члена); докстринги обновляются. → Decision:
  переименование тронуло бы `signal_repo.live_velocity`, `alerts/notifier.py`,
  `alerts/formatting.py`, `api/watchlist/schemas.py` (`live_velocity` в ПУБЛИЧНОМ API →
  openapi-drift) + миграцию колонки — вне scope, ломает контракт. Rationale: меняем
  СМЫСЛ члена (degenerate burst → temporal), НЕ имя; нулевой blast на schema/API/UI.
  (UI-демотация velocity → S1/TASK-121, отдельно.)

- Q: Какие named-константы и где? → A: в `scorer/score.py` как module-level NAMED
  constants (НЕ env — формульные коэффициенты, как `BURST_SCALE`/`LOG_ENGAGEMENT_SCALE`):
  `EWMA_HALF_LIFE_SECONDS` (период полураспада EWMA — accel принимает его для симметрии
  сигнатуры), `ACCEL_SCALE`, `BREADTH_SCALE`, `ACCEL_WEIGHT`, `BREADTH_WEIGHT`
  (внутренние веса temporal, сумма 1.0), `BURST_FLOOR_HOURS` (реюз, fallback-знаменатель).
  → Decision: формульные scale/веса — именованные module-константы рядом с весами v2,
  с обоснованием в докстринге. Rationale: CONVENTIONS «no magic literals», паттерн уже
  принят в score.py.

- Q: Старый `_velocity`/`BURST_SCALE`/`BURST_FLOOR_HOURS` — удалять? → A: `_velocity`
  (формульный член) удаляется; `BURST_FLOOR_HOURS` РЕЮЗИТСЯ как floor знаменателя
  breadth-fallback; `BURST_SCALE` удаляется если больше не используется (проверить
  ссылки: `test_score.py` импортирует его — обновить тест). → Decision: убрать мёртвый
  код после замены, не оставлять unused. Rationale: refactor-clean инвариант.

## Scope
- **Touch ONLY:**
  - `backend/src/scorer/score.py` — заменить `_velocity` на `_temporal`; добавить
    `ScoreEvent` (frozen) + опциональное `ScoreInputs.events`; named-константы;
    обновить `compute_components` (temporal вместо velocity); docstrings.
  - `backend/src/scorer/tasks.py` — `_build_score_inputs`: собрать
    `events=tuple(ScoreEvent(p.posted_at.timestamp(), p.channel_id) for p in posts)`
    и передать в `ScoreInputs`. (никаких новых запросов/миграций.)
  - `backend/tests/unit/test_score.py` — обновить `_expected`/импорты под новый
    temporal-член; новые unit для `_temporal` (TDD).
  - `backend/tests/unit/` (новый/в существующем scorer-каталоге) — unit для
    `_build_score_inputs.events` сборки, если нужно.
  - `docs/tasks/task-124-ewma-velocity.md`, `docs/tasks/tasks-index.md`.
- **Reuse (import, do NOT reimplement):** `eval/science_features.py`
  `ewma_acceleration`, `breadth_velocity`, `TimedEvent`.
- **Do NOT touch:** `eval/science_features.py` (чистые фичи — только импорт),
  `eval/online_gate.py` / `scripts/eval_gate.py` (реюзят `compute_components`, формула
  меняется под ними прозрачно — НЕ править), `storage/models/scores.py` (колонка
  `velocity` остаётся), `api/watchlist/*` (публичный `live_velocity` цел),
  `alerts/*`, `signal_repo.py`, frontend, миграции, config env.
- **Blast radius:**
  - `ScoreInputs` consumers: `scoring_replay`, `online_gate.snapshot_to_score_inputs`,
    `viral_model.FormulaFallbackModel`, `eval/scenarios`, `eval_gate` — все строят
    `ScoreInputs` БЕЗ `events` → опциональный дефолт `()` → не ломаются (компилируются и
    работают, temporal через breadth-fallback). **Проверить: ни один не передаёт
    `events` позиционно** (frozen dataclass — новое поле в конце, kw-safe).
  - `ScoreComponents.velocity` / `scores.velocity` — имя цело → consumers целы.
  - НЕТ: schema/migration, public API/openapi, Celery-контракты, события.

## Acceptance Criteria
- [ ] **AC1 (temporal не дегенеративен):** Given реальный кросс-канальный кластер с
  per-post events расходящийся по ≥2 каналам с ускорением, When `compute_components`,
  Then `temporal > 0` и растёт монотонно по (a) положительному EWMA-accel и (b)
  breadth; для single-channel zero-spread кластера `temporal` НЕ ≈max (не дегенерирует).
- [ ] **AC2 (bounded):** Given любые входы (включая Δhours→0, пустой events, отрицат.
  accel, мега-breadth), When `compute_components`, Then `temporal ∈ [0,1]`,
  `viral_score ∈ [0,100]`, функция не бросает.
- [ ] **AC3 (graceful fallback):** Given `ScoreInputs` без `events` (events=()),
  When `compute_components`, Then temporal считается из breadth-агрегатов
  (`delta_channel_count`/`delta_hours`), accel-часть=0; все офлайн-консьюмеры
  (`scoring_replay`/`online_gate`/`viral_model`/`scenarios`/`eval_gate`) компилируются
  и проходят свои тесты без изменений.
- [ ] **AC4 (reuse):** Given реализация, When grep, Then EWMA-accel/breadth берутся
  импортом из `eval/science_features.py` (НЕ реимплементированы в `score.py`).
- [ ] **AC5 (имя/контракт цел):** Given изменения, When openapi-dump + schema-diff,
  Then `scores.velocity` колонка и `live_velocity` API-поле НЕ меняются (no drift).
- [ ] **AC6 (no magic / no Any):** Given diff, When ruff+mypy strict, Then зелёные,
  все scale/веса/half-life — именованные константы, без Any/`type: ignore`.
- [ ] **AC7 (RE-VALIDATION GATE — blocks deploy):** Given S0 eval-gate
  (`scripts/eval_gate.py` на проде/B1-снапшотах) ДО и ПОСЛЕ изменения, When сравнение,
  Then новый temporal-терм **НЕ регрессирует** ROC-AUC (не ниже текущих **0.859** на
  judged) и PR-AUC per окно (15m/30m/1h) stable/лучше vs текущей формулы; результат
  (before/after числа) приложен к PR. Деплой ЗАПРЕЩЁН без этого доказательства.
- [ ] **AC8 (leak-free):** Given temporal вычисляется только из событий внутри
  score-окна (как и сейчас `_build_score_inputs`), When ревью, Then никакого
  post-T_obs/будущего сигнала; eval-gate использует leak-free forward-split (reuse).

## Plan
1. `scorer/score.py` — добавить named-константы (`EWMA_HALF_LIFE_SECONDS`,
   `ACCEL_SCALE`, `BREADTH_SCALE`, `ACCEL_WEIGHT`, `BREADTH_WEIGHT`; реюз
   `BURST_FLOOR_HOURS`) с обоснованием в докстринге.
2. `scorer/score.py` — `ScoreEvent(frozen: epoch, channel_id)` + опциональное
   `ScoreInputs.events: tuple[ScoreEvent, ...] = ()` (дефолт в конце dataclass).
3. `scorer/score.py` — `_temporal(*, events, delta_channel_count, delta_hours) -> float`:
   - если `events`: построить `TimedEvent(epoch, source_id=channel_id, weight=1.0)`,
     `norm_accel = min(max(ewma_acceleration(.., half_life=EWMA_HALF_LIFE_SECONDS),0)/ACCEL_SCALE,1)`,
     `norm_breadth = min(breadth_velocity(..)/BREADTH_SCALE,1)`.
   - иначе (fallback): `norm_accel=0`,
     `norm_breadth = min((delta_channel_count/max(delta_hours,BURST_FLOOR_HOURS))/BREADTH_SCALE,1)`.
   - `return min(max(ACCEL_WEIGHT·norm_accel + BREADTH_WEIGHT·norm_breadth,0),1)`.
4. `scorer/score.py` — `compute_components`: заменить вызов `_velocity` на `_temporal`;
   `ScoreComponents.velocity = temporal` (имя поля цело); удалить `_velocity`,
   неиспользуемые `BURST_SCALE` если больше не нужен; обновить module-докстринг
   (формула: temporal·0.15 + engagement·0.55 + cross_channel·0.30).
5. `scorer/tasks.py` — `_build_score_inputs`: собрать
   `events=tuple(ScoreEvent(epoch=p.posted_at.timestamp(), channel_id=p.channel_id) for p in posts)`
   и передать в `ScoreInputs(... events=events)`.
6. `tests/unit/test_score.py` — RED: обновить импорты (`BURST_SCALE`→убрать если ушёл),
   `_expected` под temporal; добавить unit для `_temporal` (single=low/0, multi-accel>0,
   monotonic по accel и breadth, bounded, fallback-без-events).
7. Re-валидация (AC7): `make`-обёртка eval-gate на B1 ДО и ПОСЛЕ; before/after в PR.
8. `docs/tasks/tasks-index.md` — строка TASK-124.

## Invariants
- `temporal ∈ [0,1]`, `engagement ∈ [0,1]`, `cross_channel ∈ [0,1]`,
  `viral_score ∈ [0,100]` при любых входах (включая degenerate).
- Веса 0.55/0.30/0.15 НЕ меняются; внутренние temporal-веса суммируются в 1.0.
- `ScoreComponents.velocity` поле + `scores.velocity` колонка по имени НЕ меняются.
- `compute_components` не бросает на degenerate входах (guards, как сейчас).
- Формула — единственный источник в `scorer/score.py`; eval/online_gate реюзят её.
- Leak-free: temporal только из событий внутри score-окна; eval — forward-split.
- Файлы < 800 строк; ошибки не глотать; immutability (frozen dataclasses).

## Edge cases
- `events=()` (офлайн/eval/viral_model) → breadth-fallback из агрегатов, accel=0.
- 1 событие / 1 канал → `ewma_acceleration`=0 (нужны ≥2), breadth малый → temporal мал.
- `delta_hours→0` → floor `BURST_FLOOR_HOURS` (реюз), не делит на 0.
- Все события в один момент (`epochs[-1]==epochs[0]`) → accel=0 (наука-fn guard),
  breadth через 1-мин floor внутри `science_features` → bounded.
- Отрицательный EWMA-accel (decay) → `max(.,0)`=0 (член ≥0, не штрафует).
- Мега-breadth / мега-accel → clamp к 1.0.
- `posted_at` с clock-skew (будущее) → события всё равно внутри score-окна-выборки
  (`_build_score_inputs` уже фильтрует `posted_at >= score_window_start`); epoch finite.

## Test plan
- **unit (`test_score.py`):** `_temporal` — single/zero (низкий, не max), multi-channel
  accel>0, монотонность по accel и по breadth, bounded на degenerate, fallback без
  events == breadth-only; обновлённый `_expected` hand-computed под новый член;
  `compute_viral_score` bounded [0,100].
- **unit (scorer tasks/inputs):** `_build_score_inputs` кладёт корректные
  `events` (epoch=posted_at.timestamp(), channel_id) из постов.
- **regression:** существующие `test_science_features.py`, `test_scoring_replay.py`,
  `test_online_gate.py`, `test_monotonicity.py`, `test_scorer_alerts.py`,
  `test_watchlist_signal.py` — зелёные без правок (опциональный `events` дефолт).
- **re-validation (AC7, ПЕРЕД деплоем):** `scripts/eval_gate.py` на B1 — before/after
  ROC-AUC≥0.859 judged, PR-AUC per окно stable/лучше; числа в PR.
- `make test` + `make ci-fast` (ruff format/check + mypy ×2 + unit) зелёные.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: 75bd7ed
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + lint + typecheck + runtime + RE-VALIDATION eval-gate)
- [ ] 5 review (auto, adversarial — желательно другой моделью)
- [ ] 5.5 security (N/A — не трогает auth/input/secrets/OAuth; skip if confirmed)
- [ ] 6 ship (confirm plan done + AC7 re-validation proof → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial)
</content>
</invoke>
