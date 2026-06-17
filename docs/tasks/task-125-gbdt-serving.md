---
id: TASK-125
title: "S4 — ML serving: подключить GBDT p(grow) + formula-fallback (calibrated), за флагом, zero-risk OFF"
status: planned
owner: backend
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 87fefce49f552c8c0a137549f8655ab9ed329ecd
branch: ""
tags: [scoring-evolution, S4, ml-serving, gbdt, viral-model, feature-flag, calibration, observability]
---

# TASK-125 — S4 ML serving: GBDT `p(grow)` + formula-fallback (calibrated), за флагом

> Подключить serving-ПЛАМБИНГ так, чтобы live-скорер МОГ звать `viral_model.select_prediction` (GBDT когда модель загружена И кластер ≥2 поста/≥2 канала, иначе formula-fallback) и логировать `model_choice` для наблюдаемости — БЕЗ риска для прод-скоров (единственный артефакт обучен на Higgs ≠ TG). Флаг по умолчанию OFF → поведение байт-в-байт как сегодня (формула).

## Context

S4 из [`03-scoring-evolution-plan.md`](../architecture/states/03-scoring-evolution-plan.md) (D1 рек.1: «калиброванный GBDT `p(grow)` + formula-fallback на cold-start», D5 рек.1: «bootstrap на Higgs-артефакте сейчас → дообучение на B1»). Цель target-state §4 KPI: Online PR-AUC `p(grow)` ≥0.80@1ч, Brier ≤0.12 ([`02-state-target.md`](../architecture/states/02-state-target.md) §0/D1/D5).

Интерфейс уже написан и dormant (TASK-112, `backend/src/scorer/viral_model.py`, mypy-strict, без `Any`):
- `EarlyFeatures(e_ch, e_posts, e_eng_log, e_burst)` — frozen, валидируется при создании; `FEATURE_ORDER` — single source of truth.
- `FormulaFallbackModel` — оборачивает v2-формулу (`scorer.score.compute_viral_score`) в [0,1] псевдо-вероятность; всегда доступный cold-start baseline.
- `GbdtViralModel.load(Path, feature_order=...)` — грузит LightGBM из нативного text-дампа (без pickle), валидирует имена фич артефакта против `FEATURE_ORDER`; lightgbm импортируется ЛЕНИВО внутри `load`.
- `select_prediction(features, *, gbdt, fallback) -> Prediction(probability, chosen: ModelChoice)` — политика: GBDT когда загружен И `has_minimum_signal()` (≥2 поста И ≥2 канала), иначе fallback; возвращает `ModelChoice.{GBDT,FALLBACK}`.

Live-путь скорера (`backend/src/scorer/tasks.py`): `_build_score_inputs` уже агрегирует из in-window постов кластера `views/forwards/reactions`, `unique_channels`, `delta_hours` → `ScoreInputs`; `_persist_score` пишет `compute_components(inputs)` в `Score` через ON CONFLICT.

Артефакт: `eval_offline/models/viral_gbdt_higgs_1h.txt` (LightGBM text, 350KB) — **обучен на Higgs (36k публичных каскадов), НЕ на TG**. Лежит в `eval_offline/` (вне backend-образа; `lightgbm` — opt-in `ml` extra, не в lean-образе).

## Goal

Live-скорер УМЕЕТ звать `select_prediction` за конфиг-флагом и логирует `model_choice` (наблюдаемость GBDT-vs-fallback ratio), при этом:
- **Флаг OFF (default)** → `scorer_model_enabled=False` / `scorer_model_path` пуст → GBDT НЕ грузится → всегда formula-fallback → скоры байт-в-байт идентичны до-изменения. **Zero-risk, zero score-change.**
- **Флаг ON + Higgs-модель + synthetic ≥2post/≥2channel кластер** → `select_prediction` возвращает GBDT-вероятность и пишет `ModelChoice.GBDT` в лог.
- Re-validation gate (offline GBDT-vs-formula на TG B1) задокументирован как условие, оправдывающее когда-либо включение флага.

`p(grow)` НЕ пишется в live `viral_score`/алерты по умолчанию: serving подключён, но решение «GBDT-вероятность ведёт алерты» — отдельный owner-gated шаг ПОСЛЕ TG-валидации (см. Discussion safety-gate). В этой задаче `viral_score` остаётся формульным; `p(grow)` логируется как shadow-сигнал.

## Discussion
<!-- durable record of decisions; AUTONOMOUS — resolved from code/docs -->

- Q: Шить ли Higgs-предсказания в live `viral_score`/алерты? → A: **НЕТ.** → Decision (CRITICAL safety-gate): единственный артефакт обучен на Higgs (D5/§7 RQ2,RQ6: «PR-AUC 0.92 — на Higgs, НЕ на TG»), B1 тонкий (~315–964 истории). Higgs-вероятность НЕ ведёт алерты по умолчанию. Подключаем ПЛАМБИНГ + флаг `scorer_model_enabled` (default **False**) и путь `scorer_model_path` (default **пусто** → GBDT не грузится). При OFF — поведение тождественно сегодняшнему (формула). Rationale: «никаких слепых изменений модели» (план S0/S4); включение требует TG-валидации (Brier≤0.12 на shadow), что owner-gated (план §Owner-gates: «S4/S5 — согласие на изменение скоринг-логики в проде»).

- Q: Как `p(grow)` влияет на `viral_score`/алерты в этой задаче? → A: **Никак (shadow-only).** → Decision: `viral_score` остаётся `compute_components(...).viral_score` (формула). `select_prediction` вызывается ДОПОЛНИТЕЛЬНО (когда флаг ON) и его `chosen`/`probability` ЛОГИРУЮТСЯ через `log_event` — это observability split, не управление алертами. Так «подключение serving» доказуемо без касания revenue-critical пути. Перевод алертов на `p(grow)` — следующая owner-gated задача с TG-моделью.

- Q: Schema-change (`scores.p_grow`/`model_choice` колонка) или log-only? → A: **Log-only сначала** (рекомендация плана: «log-only first to stay surgical»). → Decision: НЕ добавляем миграцию/колонку в этой задаче. `model_choice` (+ shadow `p_grow`) эмитятся через `observability.logging.log_event("model_choice", ...)`. Rationale: (1) минимальный диффект — ноль schema/migration/API blast-radius; (2) при OFF (default) `select_prediction` даже не зовётся, колонка была бы вечно `FALLBACK`/NULL → шум в схеме; (3) ratio GBDT-vs-fallback — операционная метрика, лог достаточен для S4 DoD («ratio в логах»). Колонка `scores.p_grow`/`model_choice` отложена до момента, когда `p(grow)` РЕАЛЬНО ведёт алерты (отдельная задача с миграцией `0025`, когда TG-модель валидирована). Зафиксировано как явный debt в этом доке (§Edge cases / known-debt).

- Q: Откуда брать `EarlyFeatures` в live-пути? → A: Из тех же агрегатов, что уже строит `_build_score_inputs` — БЕЗ нового запроса/миграции. → Decision (mapping, зеркало `eval_offline/public_datasets.CascadeFeatures`):
  - `e_ch`  = `unique_channels_count` (distinct каналы кластера = breadth)
  - `e_posts` = `len(posts)` (число постов в окне = early interaction count)
  - `e_eng_log` = `math.log1p(engagement_numerator(views, forwards, reactions))` — РЕЮЗ `scorer.score.engagement_numerator` (те же веса F=3/R=2), затем `log1p`
  - `e_burst` = `e_ch / max(delta_hours, BURST_FLOOR_HOURS)` (distinct каналов в час = скорость spread; пол часа уже есть как `score.BURST_FLOOR_HOURS=1.0`)
  Все четыре выводимы из уже-загруженных in-window постов / готового `ScoreInputs`. Чистая pure-функция `_early_features_from_inputs(inputs) -> EarlyFeatures` в `scorer/tasks.py` (или рядом), валидируется конструктором `EarlyFeatures` (non-negative, finite).

- Q: Где грузить модель (раз на тик, не на кластер)? → A: Лениво, один раз за `score_recent_clusters()` тик, кэшируется в скоупе тика. → Decision: helper `_load_viral_model(settings) -> ViralModel | None` зовётся ОДИН раз в начале тика; при `scorer_model_enabled and scorer_model_path` → `GbdtViralModel.load(Path(scorer_model_path), feature_order=FEATURE_ORDER)`, иначе `None`. `GbdtViralModel` frozen/immutable, переиспользуется для всех кластеров тика. Ошибка загрузки (`ViralModelError`: нет файла / lightgbm не стоит / mismatch) → лог + `None` (graceful → formula-fallback; модель-сбой НЕ валит revenue-critical scoring, как B1-snapshot SAVEPOINT-паттерн). Lazy-load избегает импорта lightgbm в api/worker boot когда флаг OFF.

- Q: Offline re-validation — где и как? → A: Расширить ОФЛАЙН GBDT-vs-formula compare (уже есть в `eval_offline/`), не плодить API. → Decision: re-validation gate, оправдывающий включение флага, — офлайн прогон `eval_offline/train_gbdt_c1.py` / `harness_c2_lift.py` (уже считают GBDT PR-AUC/ROC-AUC/Brier vs v2-formula baseline на том же split) НА TG B1-снапшотах (через `eval/online_gate` проекцию), когда N достаточно. Тонкий скрипт-сравнение GBDT-vs-formula на B1 — расширение `scripts/eval_gate.py` (опционально, отдельный shadow-режим) ИЛИ офлайн-харнесс; в этой задаче фиксируем КОНТРАКТ gate (Brier≤0.12 + PR-AUC ≥ formula на TG test), а живой прогон — owner-gated по мере накопления B1. Минимально: тест, доказывающий что `_early_features_from_inputs` даёт ту же фича-схему, что offline-тренер (`FEATURE_ORDER`-параллель).

- Q: Riск изменения скоров при OFF? → A: Ноль, доказуемо. → Decision: при `scorer_model_enabled=False` ветка `select_prediction`/логирования НЕ исполняется (early-return на флаге ДО любого вызова); `_persist_score` пишет ровно `compute_components(inputs)` как сейчас. Acceptance AC1 — golden-тест байт-в-байт идентичности скоров с флагом OFF.

> ADR-кандидат (durable): «Higgs≠TG safety-gate для ML-serving — flag-gated dormant serving, `p(grow)` shadow-only до TG-валидации». Зафиксировать в learnings → `docs/architecture/adr-NNN-*.md` при ship.

## Scope
- **Touch ONLY:**
  - `backend/src/config.py` — +2 поля `Settings`: `scorer_model_enabled: bool = False`, `scorer_model_path: str = ""` (+ named-constant defaults в стиле модуля; env `SCORER_MODEL_ENABLED`/`SCORER_MODEL_PATH`).
  - `backend/src/scorer/tasks.py` — +pure `_early_features_from_inputs(inputs) -> EarlyFeatures`; +`_load_viral_model(settings) -> ViralModel | None` (lazy, раз/тик, graceful на ошибке); прокинуть `gbdt: ViralModel | None` через `score_recent_clusters → _score_user → _persist_score`; в `_persist_score` (флаг ON) звать `select_prediction(...)` и `log_event("model_choice", ...)` (shadow `p_grow` + choice); `viral_score` НЕ меняется.
  - `backend/tests/unit/scorer/` — новые юнит-тесты (AC1 golden OFF-identity; AC2 ON+fake-booster GBDT-choice; feature-mapping; graceful load-fail).
  - `docs/tasks/task-125-gbdt-serving.md` (этот док) + `docs/tasks/tasks-index.md` (строка).
- **Do NOT touch:**
  - `backend/src/scorer/viral_model.py` (готов, dormant — не трогаем).
  - `backend/src/scorer/score.py` / `compute_components` / формула / веса (`viral_score` остаётся формульным).
  - `backend/src/storage/models/scores.py` + миграции (log-only — НЕТ schema-change, НЕТ миграции 0025).
  - `eval/online_gate.py` / `scripts/eval_gate.py` (re-validation gate переиспользует существующее; правки опц./вне surgical-ядра).
  - API-схемы / openapi / `WatchlistSignal` / `live_velocity` (0 API-drift); alert-trigger / threshold / guards.
  - `eval_offline/*` артефакт/тренер (не пересобираем модель).
- **Blast radius:** один модуль (`scorer/tasks.py`) + 2 конфиг-поля. НЕТ schema/migration/pgvector/Celery-contract/public-API изменений. При OFF (default) — поведение тождественно. Lazy lightgbm import → boot api/worker не тянет lightgbm пока флаг OFF. Cross-module: `select_prediction`/`EarlyFeatures` — публичная поверхность `scorer.viral_model` (CONVENTIONS-чисто).

## Acceptance Criteria
- [ ] **AC1 (OFF identity, MUST):** Given `scorer_model_enabled=False` (default), When `score_recent_clusters`/`_persist_score` исполняется на кластере, Then `compute_components` зовётся как раньше, `select_prediction`/lightgbm НЕ зовутся, и persisted `viral_score`/components байт-в-байт идентичны до-изменения (golden-тест на фиксированных `ScoreInputs`).
- [ ] **AC2 (ON → GBDT choice):** Given `scorer_model_enabled=True` + загруженный (fake/Higgs) booster + synthetic `EarlyFeatures` с ≥2 поста И ≥2 канала, When `select_prediction` зовётся в `_persist_score`-пути, Then возвращается GBDT-вероятность ∈ [0,1] и `ModelChoice.GBDT` логируется (`log_event("model_choice", choice="gbdt", ...)`).
- [ ] **AC3 (ON cold-start → fallback):** Given флаг ON + booster + кластер <2 поста ИЛИ <2 канала, When `select_prediction` зовётся, Then `ModelChoice.FALLBACK` (formula псевдо-вероятность), `viral_score` всё ещё формульный.
- [ ] **AC4 (feature mapping):** Given готовый `ScoreInputs`, When `_early_features_from_inputs(inputs)`, Then `e_ch=unique_channels_count`, `e_posts=len(posts)`, `e_eng_log=log1p(engagement_numerator(...))`, `e_burst=e_ch/max(delta_hours,1h)`; конструктор `EarlyFeatures` не падает на валидных входах (non-negative/finite).
- [ ] **AC5 (graceful load-fail):** Given флаг ON но `scorer_model_path` указывает на отсутствующий файл / lightgbm не установлен / feature-mismatch, When `_load_viral_model`, Then возвращается `None` + лог-warning, тик продолжается на formula-fallback (scoring НЕ падает).
- [ ] **AC6 (lazy import / boot):** Given флаг OFF, When импортируется/бутится `scorer.tasks` (api/worker), Then lightgbm НЕ импортируется (импорт только внутри `GbdtViralModel.load`).
- [ ] **AC7 (no schema/API drift):** Given изменение, Then нет новой миграции, нет правок `scores`-схемы/openapi/`WatchlistSignal`; ruff + mypy strict зелёные, без `Any`/`# type: ignore`/magic-literals.

## Plan
1. `backend/src/config.py` — добавить named-constant defaults (`_DEFAULT_SCORER_MODEL_ENABLED=False`, `_DEFAULT_SCORER_MODEL_PATH=""`) + поля `Settings.scorer_model_enabled`/`scorer_model_path` рядом со Scorer-блоком (комментарий: Higgs≠TG, default OFF = тождественно формуле, путь к артефакту в `eval_offline/models/`).
2. `backend/src/scorer/tasks.py` — pure `_early_features_from_inputs(inputs: ScoreInputs) -> EarlyFeatures` (mapping из Discussion; РЕЮЗ `engagement_numerator`, `BURST_FLOOR_HOURS`; import из `scorer.score`/`scorer.viral_model`).
3. `backend/src/scorer/tasks.py` — `_load_viral_model(settings) -> ViralModel | None`: при `enabled and path` → `GbdtViralModel.load(Path(path), feature_order=FEATURE_ORDER)`; `except ViralModelError` → `log_event`/`logger.warning` + `None`; иначе `None`.
4. `backend/src/scorer/tasks.py` — прокинуть `gbdt: ViralModel | None` параметром: `score_recent_clusters` грузит раз/тик → `_score_user(..., gbdt=gbdt)` → `_persist_score(..., gbdt=gbdt)`.
5. `backend/src/scorer/tasks.py` — в `_persist_score`: `viral_score = compute_components(inputs).viral_score` (как сейчас). ЕСЛИ `gbdt is not None` (т.е. флаг ON и модель загрузилась): построить `EarlyFeatures`, `pred = select_prediction(feats, gbdt=gbdt, fallback=FormulaFallbackModel(watched_channels_count=inputs.watched_channels_count))`, `log_event("model_choice", user_id=..., cluster_id=..., choice=pred.chosen.value, p_grow=pred.probability)`. `viral_score` (что пишется в `Score`) НЕ меняется (shadow-only). Early-return на `gbdt is None` гарантирует AC1.
6. `backend/tests/unit/scorer/test_*.py` — AC1 golden OFF-identity (фикс `ScoreInputs` → те же components до/после); AC2/AC3 select-choice c fake-booster (паттерн из `test_viral_model.py`); AC4 mapping; AC5 graceful load-fail (несуществующий путь → `None`); AC6 (опц.) — assert lightgbm не в `sys.modules` после import при OFF.
7. `docs/tasks/tasks-index.md` — строка TASK-125.

## Invariants
- `viral_score`, записываемый в `scores`, ВСЕГДА = `compute_components(inputs).viral_score` (формула) в этой задаче — `p(grow)` НИКОГДА не перезаписывает его (shadow-only). [revenue-critical]
- При `scorer_model_enabled=False` ветка GBDT/логирования полностью пропускается (early-return на `gbdt is None`) → скоры тождественны pre-change. [zero-risk OFF]
- Сбой модели (load или predict) НИКОГДА не валит scoring/alert-путь (graceful → fallback/formula; модель — best-effort shadow, как B1-snapshot). [reliability]
- lightgbm импортируется ТОЛЬКО внутри `GbdtViralModel.load`; boot/import `scorer.tasks` при OFF его не тянет. [lean-image]
- Args Celery-тасков JSON-serializable — модель грузится ВНУТРИ тик-функции из конфиг-пути, НЕ передаётся как arg. [CONVENTIONS]
- Нет `Any`/`# type: ignore`/magic-literals; пороги (`MIN_*`, `BURST_FLOOR_HOURS`) — named-constants из `viral_model`/`score`. [CONVENTIONS]
- Фича-схема live-пути == offline-тренера (`FEATURE_ORDER`) — иначе модель mis-fed (артефакт-валидация в `load` ловит, но mapping должен совпадать по смыслу). [correctness]

## Edge cases
- Кластер с 1 постом / 1 каналом (77% live single-post) → `has_minimum_signal()=False` → `select_prediction` отдаёт FALLBACK даже при ON. → формульная псевдо-вероятность (лог FALLBACK); `viral_score` формульный. OK.
- `delta_hours == 0` (все посты в одну секунду) → `e_burst = e_ch / max(0, 1h) = e_ch` (пол `BURST_FLOOR_HOURS`). Не делим на ноль. OK.
- `scorer_model_path` указывает в `eval_offline/` (вне backend-образа) → в проде файла нет → `load` → `ViralModelError` → `None` → fallback (AC5). Это ОЖИДАЕМО: артефакт деплоится отдельно когда owner включает флаг. OK.
- lightgbm не в образе (lean) + флаг ON → `load` → `ImportError`→`ViralModelError` → `None` → fallback + warning. OK.
- **Known-debt (зафиксировано):** `model_choice`/`p_grow` — log-only. Когда `p(grow)` начнёт ВЕСТИ алерты (отдельная owner-gated задача с TG-моделью) — добавить миграцию `0025` (`scores.p_grow FLOAT NULL`, `scores.model_choice VARCHAR NULL`) и писать в `_persist_score`. Сейчас — НЕ нужно (колонка была бы вечно NULL/FALLBACK при default-OFF).

## Test plan
- **unit:** `_early_features_from_inputs` mapping (AC4); OFF-identity golden на `compute_components` (AC1); `select_prediction` choice GBDT/FALLBACK c fake-booster (AC2/AC3, паттерн `_FakeBooster` из `test_viral_model.py`); `_load_viral_model` graceful на bad path / disabled (AC5); lazy-import (AC6).
- **integration:** `score_recent_clusters` тик с `scorer_model_enabled=False` → `scores` идентичны baseline (расширить существующий scorer integration-тест, если есть, фикстурой OFF); с флагом ON + fake-модель (monkeypatch `_load_viral_model`) → `log_event("model_choice")` вызван, `scores.viral_score` всё ещё формульный.
- **e2e/offline re-validation:** контракт gate (Brier≤0.12 + PR-AUC≥formula на TG B1) — документирован; живой прогон `eval_offline` harness owner-gated по N (не в CI). Минимум — тест эквивалентности фича-схемы live↔offline.
- **G2 runtime:** при OFF — `make ci` зелёный, lightgbm не в `sys.modules`; поведенческая проверка — тик пишет скоры идентично (psql diff на staging при наличии).

## Checkpoints
current_step: 3
baseline_commit: 87fefce49f552c8c0a137549f8655ab9ed329ecd
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
