---
id: TASK-122
title: "S0 eval-gate — онлайн-измерение качества скоринга на TG B1 (leak-free)"
status: planned
owner: backend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 25ab33b6625a64c43ad5ef6264931faa01a570f3
branch: ""
tags: [scoring-evolution, S0, eval, quality-gate, leak-free, measurement]
---

# TASK-122 — S0 eval-gate: онлайн-измерение качества скоринга на TG B1 (leak-free)

> Воспроизводимый офлайн-джоб: join B1 `cluster_feature_snapshots` (ранние окна 15m/30m/1h) → eventual cluster outcome, leak-free doubling-лейбл (reuse `forward_split`), репорт **PR-AUC / ROC-AUC / Brier** для ТЕКУЩЕЙ v2-формулы на реальном TG + **alert precision** по 👍/👎 — это baseline-измерение, против которого судятся S3/S4. Модель НЕ меняем.

## Context

S0 из [`03-scoring-evolution-plan.md`](../architecture/states/03-scoring-evolution-plan.md) (рек. вариант 1: offline-джоб по B1+исходам). Цель target-state §4 KPI: **Online PR-AUC `p(grow)` ≥0.80@1ч**, **Brier ≤0.12**, **Alert precision ≥0.6** ([`02-state-target.md`](../architecture/states/02-state-target.md) §4, D5). Принцип плана: *«никаких слепых изменений модели»* — сначала ставим честную цифру на TG, потом S3/S4 мерятся против неё.

Наработки уже есть (reuse, не rebuild):
- `eval/metrics.py` — `average_precision` (PR-AUC), `roc_auc`, `precision_at_k`, `confusion_at_threshold`, `separation`. **НЕТ Brier** → добавляем pure `brier_score` сюда же.
- `eval/forward_split.py` — `ClusterOutcome`, `split_by_time`, `LabelKind.DOUBLING`, `CohortPolicy`, `label_partition(s)` (leak-free chrono split + cohort-median-per-partition doubling-лейбл).
- `eval/scoring_replay.py` — паттерн «replay v2-формулы через `compute_components`/`ScoreInputs`, НЕ реимплементируя формулу».
- `storage/models/cluster_feature_snapshots.py` (B1, копятся в проде) — ранние METRICS-only снимки `(user_id, cluster_id, window_label∈{15m,30m,1h})`: `age_seconds, post_count, views, forwards, reactions, distinct_channels, breadth_velocity, captured_at`.
- `scorer/score.py` — v2-формула; `scorer/viral_model.py` — GBDT (dormant, не трогаем в S0).
- `storage/models/alert_feedback.py` — `AlertFeedback(alert_id FK, verdict∈{0=down,1=up})`; цепочка precision: `AlertFeedback → Alert(cluster_id, score) → Cluster`.

## Goal

Один воспроизводимый backend-скрипт `backend/scripts/eval_gate.py` (`uv run`), который читает прод-БД read-only, и через новый pure-модуль `backend/src/eval/online_gate.py`:
1. собирает per-cluster ранний feature-снапшот (B1) на каждом окне 15m/30m/1h;
2. вычисляет eventual outcome кластера (cumulative weighted engagement из `posts`) — leak-free: фичи только из раннего окна, outcome измеряется ПОЗЖЕ;
3. строит `ClusterOutcome`, гоняет `split_by_time` + `label_partition` (`LabelKind.DOUBLING`, cohort-per-partition) → balanced doubling-лейбл на test-партиции;
4. реплеит v2-score КАК ранний скор (через `compute_components`, из снапшота → `ScoreInputs`);
5. репортит **PR-AUC, ROC-AUC, Brier** (score-as-pseudo-prob) per окно на test + **alert precision** = доля 👍 среди оценённых алертов (если фидбек есть);
6. пишет маленький JSON-отчёт (+ stdout-сводку) с `n`, `n_pos`, метриками per окно и честными caveat'ами (N-limited / single-class → skip).

DoD: воспроизводимая цифра качества v2-формулы на TG B1 ДО любых изменений модели; leak-free (forward-split + outcome строго позже окна); 0 изменений live-скорера/API/схемы; покрыто unit-тестами; ruff+mypy strict, без `Any`/magic-literals.

## Discussion
<!-- автономный режим: решения приняты из кода/доков, owner спит; рекомендованный вариант зафиксирован -->

- Q: Delivery surface — CLI-скрипт, admin-эндпоинт или оба? → A: `backend/scripts/eval_gate.py` через `uv run --directory backend python scripts/eval_gate.py`, пишет JSON + stdout. → Decision: **CLI-first** (рек. вариант плана S0). Rationale: наименьший дифект; нет нового API-surface → не нужен security/auth-ревью; зеркалит существующие `scripts/quality_report.py` / `backtest_harness.py`. Read-only admin-метрика — отдельная задача S0-follow-up (`02-state-target.md` упоминает дашборд-эндпоинт), НЕ в этом surgical-дифекте.

- Q: Outcome definition исхода кластера? → A: cumulative weighted engagement `Σ(views + forwards·F + reactions·R)` по ВСЕМ постам кластера (`engagement_numerator` из `scorer/score.py`, тот же вес F=3/R=2), измеренный на момент джоба. → Decision: **cumulative engagement growth → doubling vs cohort-mean через `LabelKind.DOUBLING`**. Rationale: `forward_split` уже даёт balanced doubling-лейбл (outcome > cohort-median); engagement — единственный сигнал, выживший в B0/B2 (eval показал AUC 0.91 у engagement, velocity дегенеративен). `final_outcome` неотрицателен → проходит `ClusterOutcome.__post_init__`.

- Q: Leak-free как гарантируется? → A: фичи берём ТОЛЬКО из B1-снапшота окна (cumulative-до-capture, по построению ранние); outcome считаем по `posts` кластера в целом (заведомо ПОЗЖЕ окна, т.к. снапшот — ранний, а кластер живёт дальше); split chronological по `first_seen`; doubling-порог cohort-median считается ВНУТРИ test-партиции. → Decision: **outcome-window отделён от feature-window**; `t0_epoch = cluster.first_seen`, `age_at_outcome_seconds = (now − first_seen)`. Rationale: повторяет два leak-hazard'а, которые `forward_split` уже закрывает (boundary-gap + cohort-per-partition); B1 by-design leak-free (хранит только ранние метрики, не лейбл).

- Q: B1-снапшот → `ScoreInputs` маппинг (watched_channels у снапшота нет)? → A: `views/forwards/reactions/distinct_channels/age_seconds` из снапшота; `delta_channel_count = distinct_channels`, `delta_hours = age_seconds/3600`, `unique_channels_count = distinct_channels`; `watched_channels_count` — именованная CLI-assumption (default 1, как в `FormulaFallbackModel`), `channel_avg` — fallback-proxy `views/post_count` (тот же документированный proxy, что `scoring_replay`). → Decision: **снапшот-проекция в `ScoreInputs`, формула не реимплементируется** (зовём `compute_components`). Rationale: единственный источник формулы — `scorer/score.py`; cross_channel под явной assumption репортится (как `scoring_replay`).

- Q: Score 0–100 → pseudo-probability для Brier? → A: `viral_score / SCORE_SCALE` (÷100, clamp [0,1]) — ровно как `FormulaFallbackModel.predict_proba`. → Decision: **формула = ranking-сигнал, нормализуем в [0,1] для Brier** с честной пометкой «не калибровано». Rationale: Brier на сырой формуле — это baseline калибровки, против которого S4 (калиброванный GBDT) покажет улучшение; это явная цель D5/§4.

- Q: Brier-метрика — добавить новый модуль или расширить `metrics.py`? → A: добавить pure `brier_score(probs, labels)` в `eval/metrics.py` рядом с `average_precision`. → Decision: **extend `metrics.py`** (не новый файл). Rationale: метрики качества лейбл-vs-скор живут именно там; модуль <800 строк; reuse `_check_pairs`/`_check_binary_labels`.

- Q: Alert precision когда фидбек пустой (0 алертов/0 голосов сейчас)? → A: join `AlertFeedback→Alert`, precision = `Σverdict==1 / n_feedback`; при `n_feedback==0` → честный placeholder `null` + `n=0` в отчёте (как `confusion_at_threshold` отдаёт 0.0 при пустом знаменателе). → Decision: **precision опционально, не валит джоб** при пустом фидбеке. Rationale: прод сейчас 0 алертов (state-доки) — джоб должен работать и расти по мере накопления.

- Q: Single-class партиция (sparse TG → cohort-median=0 → all-negative)? → A: детектим `n_pos==0` / `n_neg==0` ДО вызова AUC (который raise'ит), репортим `n`/`n_pos` и SKIP окно. → Decision: **honest-skip single-class окна** (как документировано в `forward_split`/`metrics`). Rationale: thin TG-субсет (B0: 315–964 истории) → ожидаемая дегенерация; репорт честно показывает причину, не падает.

- Q: Read-only гарантия? → A: только SELECT'ы; `with get_session() as session` коммитит на выходе, но без write-операций коммит no-op. → Decision: **NO writes**; джоб не создаёт/не меняет строк. Rationale: измерение не должно трогать прод-данные.

## Scope

- **Touch ONLY:**
  - `backend/src/eval/online_gate.py` — **NEW** pure-модуль: типы (`OnlineEvalConfig`, `SnapshotRow`, `ClusterEngagementOutcome`, `WindowReport`, `GateReport`) + чистые функции (`snapshot_to_score_inputs`, `compute_window_report`, `build_cluster_outcomes`, `alert_precision`). НИКАКОГО I/O / DB здесь.
  - `backend/src/eval/metrics.py` — добавить pure `brier_score(probs, labels)` (+ reuse `_check_pairs`).
  - `backend/scripts/eval_gate.py` — **NEW** тонкий runner: открывает `get_session()`, делает read-only SELECT'ы (snapshots + per-cluster posts + alert-feedback), зовёт `online_gate`, пишет JSON + stdout. Argparse: `--out`, `--watched-channels`, `--split-gap-seconds`, `--cohort-bucket-seconds`.
  - `backend/tests/unit/eval/test_online_gate.py` — **NEW** unit-тесты pure-логики.
  - `backend/tests/unit/eval/test_metrics.py` — добавить тесты `brier_score`.
  - `docs/tasks/tasks-index.md` — строка (этот PR).
- **Do NOT touch:** `scorer/score.py`, `scorer/tasks.py`, `scorer/viral_model.py`, `scorer/feature_snapshots.py` (live-скорер); любой `api/*` (нет нового эндпоинта); `storage/models/*` (нет схемы/миграции); `eval/forward_split.py` (reuse as-is); `eval/scoring_replay.py`; фронт/инфра.
- **Blast radius:** нулевой для рантайма — новый модуль + скрипт + одна pure-функция в `metrics.py` (аддитивно, существующие импорты целы). Нет Celery-тасков, нет схемы, нет API-контракта, нет pgvector-измерений. Единственный consumer `metrics.brier_score` — новый скрипт. Read-only по БД.

## Acceptance Criteria

- [ ] **AC1 (PR-AUC/ROC-AUC на TG B1):** Given B1-снапшоты и посты кластеров в проде, When запускаю `uv run --directory backend python scripts/eval_gate.py --out report.json`, Then JSON содержит per окну {15m,30m,1h} `pr_auc` и `roc_auc` для v2-формулы на test-партиции, с `n`/`n_pos` рядом.
- [ ] **AC2 (Brier/calibration):** Given те же данные, When джоб посчитал, Then репорт содержит `brier` per окно (score÷100 как pseudo-prob) с пометкой «uncalibrated baseline».
- [ ] **AC3 (leak-free):** Given кластер с ранним снапшотом, When строится `ClusterOutcome`, Then фичи берутся ТОЛЬКО из снапшота окна, а `final_outcome` — из полного набора постов кластера (заведомо позже окна); doubling-порог считается внутри test-партиции (`label_partition` per-partition). Unit-тест доказывает, что ни одно поле снапшота не зависит от будущего outcome.
- [ ] **AC4 (alert precision из 👍/👎):** Given строки `alert_feedback`, When джоб считает precision, Then `precision = #(verdict==1)/n_feedback` в отчёте; Given пустой фидбек, Then `precision=null, n=0` без падения.
- [ ] **AC5 (single-class honest-skip):** Given окно с `n_pos==0` или `n_neg==0`, When считаются метрики, Then окно помечается `skipped: "single_class"` с `n`/`n_pos`, а AUC НЕ вызывается (не raise).
- [ ] **AC6 (формула не реимплементирована):** Given маппинг снапшот→score, When считается ранний скор, Then используется `scorer.score.compute_components` (а не локальная копия формулы). Unit-тест на идентичность с прямым вызовом формулы.
- [ ] **AC7 (read-only, без побочек):** Given прод-БД, When джоб отработал, Then ни одна строка не создана/изменена (только SELECT).
- [ ] **AC8 (качество кода):** Given изменения, When `make ci` (ruff+mypy strict+pytest), Then зелёно; нет `Any`/`# type: ignore`/magic-literals; новые pure-функции покрыты unit-тестами; файлы <800 строк.

## Plan

1. `backend/src/eval/metrics.py` — добавить `brier_score(probs: Sequence[float], labels: Sequence[int]) -> float` = `mean((p − y)²)`; reuse `_check_pairs` + `_check_binary_labels`; docstring «calibration: 0 идеально, 0.25 = coin-flip».
2. `backend/src/eval/online_gate.py` (NEW) — frozen-типы: `OnlineEvalConfig(watched_channels_count, split_gap_seconds, cohort_bucket_seconds, windows)`; `SnapshotRow` (зеркало колонок B1); `ClusterEngagementOutcome(cluster_id, first_seen_epoch, final_engagement, age_at_outcome_seconds)`; `WindowReport(window, n, n_pos, pr_auc|None, roc_auc|None, brier|None, skipped|None)`; `GateReport(windows, alert_precision|None, alert_feedback_n)`.
3. `online_gate.snapshot_to_score_inputs(snapshot, *, watched_channels_count) -> ScoreInputs` — проекция B1→`ScoreInputs` (документированные assumptions; reuse `_build_inputs`-стиль `scoring_replay`).
4. `online_gate.build_cluster_outcomes(outcomes_raw) -> tuple[ClusterOutcome, ...]` — маппинг engagement-исходов в `forward_split.ClusterOutcome` (`t0_epoch=first_seen`, `final_outcome=final_engagement`, `age_at_outcome_seconds`).
5. `online_gate.compute_window_report(window, paired_scores_and_outcomes, *, config) -> WindowReport` — `split_by_time` → `label_partition(test, DOUBLING, cohort)` → если single-class → skip; иначе `average_precision`/`roc_auc`/`brier_score` на (score÷100, label) test-партиции.
6. `online_gate.alert_precision(feedback_verdicts) -> tuple[float|None, int]` — `Σ==1/n` или `(None,0)`.
7. `backend/scripts/eval_gate.py` (NEW) — argparse; `with get_session()`: SELECT B1-снапшоты (`ClusterFeatureSnapshot`), per-cluster cumulative engagement из `Post` (group by `cluster_id`, sum weighted), `Cluster.first_seen`, `AlertFeedback.verdict` (join `Alert`); собрать в `online_gate`-входы; вызвать pure-функции per окно; `json.dump` в `--out` + stdout-сводка (стиль `quality_report.py`).
8. `backend/tests/unit/eval/test_online_gate.py` (NEW) + дополнить `test_metrics.py` — brier, snapshot→inputs идентичность формуле, leak-free, single-class-skip, пустой фидбек.
9. `docs/tasks/tasks-index.md` — строка TASK-122 (в этом же PR).

## Invariants

- Live-скорер/алерты НЕ затронуты (0 изменений в `scorer/*`, `api/*`, `storage/models/*`); прод-поведение бит-в-бит.
- Формула — единственный источник `scorer/score.py`; `online_gate` НЕ реимплементирует её (зовёт `compute_components`).
- Leak-free: feature-окно (B1-снапшот) строго отделено от outcome-окна (полный кластер позже); cohort-порог считается per-partition (`label_partition`).
- Read-only: джоб не делает INSERT/UPDATE/DELETE.
- CONVENTIONS: no `Any`, no `# type: ignore`, no magic-literals (пороги/окна/факторы — именованные константы или CLI/config), immutability (frozen dataclasses), ошибки не глотать (валидация на границе — посчитанные `n`/`n_pos` рядом с каждой метрикой), файлы <800 строк.
- Brier-pseudo-prob честно помечен «uncalibrated» — не выдаём ranking-формулу за калиброванную вероятность.

## Edge cases

- Окно без снапшотов / без постов кластера → `WindowReport(n=0, skipped="empty")`, не падать.
- Single-class партиция (cohort-median=0 на sparse TG) → детект `n_pos==0`/`n_neg==0` ДО AUC → `skipped="single_class"` + `n`/`n_pos`.
- Пустой `alert_feedback` (0 алертов сейчас) → `alert_precision=(None, 0)`.
- Кластер с `distinct_channels=0`/`age_seconds=0` → guard'ы формулы (`_velocity` floor 1h, `_cross_channel` watched≤0→0) уже держат; `final_outcome>=0` инвариант `ClusterOutcome` соблюдён (engagement неотрицателен).
- Снапшот с `window_label` вне {15m,30m,1h} → фильтруется по `config.windows` (валидный набор).
- Кластеры разных `user_id` (multi-tenant) → группируем/лейблим в рамках одного джоба корректно (cohort по age, split по времени; per-user изоляция данных в SELECT не ломается — outcome считается по постам того же кластера).

## Test plan

- **unit (`test_online_gate.py`):** `snapshot_to_score_inputs` == прямой `compute_components` (AC6); `build_cluster_outcomes` валидирует/маппит; `compute_window_report` на синтетике — корректные PR-AUC/ROC-AUC/Brier (hand-computed) + single-class skip (AC5); leak-free свойство (outcome не влияет на feature-вектор) (AC3); `alert_precision` (заполненный/пустой) (AC4).
- **unit (`test_metrics.py` +):** `brier_score` на известных кейсах (идеал=0, coin-flip=0.25, length-mismatch raise) (AC2).
- **integration:** не требуется — БД-слой тонкий read-only SELECT в скрипте; покрытие даёт pure-модуль. (Опционально: smoke-прогон скрипта на проде owner'ом по факту — psql подтверждает n снапшотов; не в CI.)
- **ci:** `make ci` (ruff + mypy strict + pytest) зелёный; full backend suite не регрессирует (AC8).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: 25ab33b6625a64c43ad5ef6264931faa01a570f3
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth) — N/A (read-only, no auth/input/secrets)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
- Reuse-граф: `forward_split` (split+doubling-лейбл), `metrics` (PR-AUC/ROC-AUC + новый Brier), `scorer.score.compute_components` (формула), `scoring_replay`-паттерн (снапшот→ScoreInputs proxy), B1 `cluster_feature_snapshots` (ранние фичи), `AlertFeedback→Alert` (precision), `storage.database.get_session` (sync read-only сессия).
- Запуск: `uv run --directory backend python scripts/eval_gate.py --out report.json` (паттерн `quality_report.py`/`backtest_harness.py`).
- Outcome = cumulative weighted engagement (`engagement_numerator` веса F=3/R=2) по всем постам кластера; doubling vs cohort-median per test-partition.
