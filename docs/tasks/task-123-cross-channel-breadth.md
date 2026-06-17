---
id: TASK-123
title: "S2 clustering — кросс-канальная связка темы (широта = основа моата)"
status: planned
owner: backend
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 7e8a5fc
branch: ""
tags: [scoring-evolution, S2, clustering, cross-channel, breadth, over-merge-guard, merge-precision]
---

# TASK-123 — S2 clustering: кросс-канальная связка темы (широта = основа моата)

> Одна история across каналов = ОДИН кластер с `channels_count>1`. Ввести ВТОРОЙ, более низкий cosine-порог `cluster_merge_cosine_threshold` (рек. **0.65**), используемый ТОЛЬКО в cross-batch merge-пути (`_find_mergeable_cluster`), оставив tight intra-batch `cluster_cosine_threshold` (0.75) нетронутым для группировки/дедупа. Target: ≥35% multi-channel кластеров БЕЗ роста ложных склеек — обязательный замер **merge-precision** через `clustering_audit` ПЕРЕД деплоем.

## Context

S2 из [`03-scoring-evolution-plan.md`](../architecture/states/03-scoring-evolution-plan.md) (рек. вариант D2.1: тюнинг cross-batch merge + понизить cosine-порог окна → D2.2 two-tier поэтапно). Цель target-state §4 KPI: **`channels_count>1` доля ~12% → ≥35%** ([`02-state-target.md`](../architecture/states/02-state-target.md) §4, D2). Риск-инвариант §5: **over-merge** — склейка разного при низком cosine → ОБЯЗАТЕЛЬНЫЙ precision-замер ПЕРЕД деплоем.

Диагноз AS-IS ([`01-state-current.md`](../architecture/states/01-state-current.md) §4/§7): кластеризация — greedy single-link cosine ≥0.75 per-batch, scope per-user; cross-batch merge (TASK-080) переиспользует **тот же** `cluster_cosine_threshold` (0.75) и в intra-batch группировке (`pipeline/steps/cluster.py`), и в cross-batch склейке (`pipeline/batch_processor.py:_find_mergeable_cluster`). Прод (user_id=2, 2ч): `channels_count` 1→121, 2→10, 3→5 → **~88% одноканальные** → `velocity≈0`, `cross_channel≈0`, `viral_score` avg≈21 < alert-порога → 0 алертов. Дефицит №1 §8: «кросс-канальной широты — velocity/cross_channel структурно =0 пока тема в 1 канале → моат не считается».

Почему 0.75 слишком жёсткий для cross-channel: разные каналы пишут об одном событии РАЗНЫМИ формулировками (перефраз, свой angle, эмодзи/хедер канала) → центроиды семантически близкой, но НЕ идентичной истории расходятся ниже 0.75. Tight-порог нужен для дедупа (почти-дубль одного текста), но душит «одна история, разные слова». Отсюда two-tier: tight 0.75 для группировки/дедупа, loose ~0.65 для «это та же история across каналов».

Наработки уже есть (reuse, не rebuild):
- `pipeline/batch_processor.py:_find_mergeable_cluster` — единственный cross-batch merge-сайт (pgvector `cosine_distance`, NN LIMIT 1, bounded user+freshness+span). СЕЙЧАС: `max_distance = 1.0 - settings.cluster_cosine_threshold`.
- `pipeline/steps/cluster.py:run` — intra-batch greedy grouping по `cluster_cosine_threshold`. **НЕ трогаем** (tight tier).
- `config.py` — `cluster_cosine_threshold=0.75`, `cluster_merge_window_seconds`, `cluster_max_span_seconds`; паттерн именованных `_DEFAULT_*` + env-override.
- `eval/clustering_audit.py:count_duplicate_centroid_pairs(centroids, cosine_threshold)` — blocked upper-triangle cosine-pass; уже считает near-duplicate пары центроидов. Reuse как over-merge proxy.
- `scripts/backtest_harness.py` — CLI-репорт: scoring replay + clustering audit (size histogram, singleton%, duplicate topics, duplicate centroids). Reuse как gate-харнесс.
- `eval/quality.py` — `max_cross_cluster_cosine` quality-feature, `assess_cluster` near_duplicate-флаг (cosine ≥0.9). Reuse контекст.

## Goal

Хирургический config-дифект: добавить ВТОРОЙ именованный порог `cluster_merge_cosine_threshold` (рек. default **0.65**) и применить его ТОЛЬКО в `_find_mergeable_cluster` (`max_distance = 1.0 - cluster_merge_cosine_threshold`), оставив intra-batch `cluster.py` и tight `cluster_cosine_threshold=0.75` нетронутыми. Плюс расширить offline-харнесс метрикой **merge-precision** (over-merge guard), чтобы доказать: понижение порога поднимает multi-channel долю, НЕ склеивая несвязанные истории.

DoD:
1. Multi-channel доля (`channels_count>1`) на проде сдвигается вверх к ≥35% (прод-факт по psql после деплоя).
2. **Merge-precision gate (ОБЯЗАТЕЛЕН ПЕРЕД деплоем):** offline-замер over-merge на локальном/прод-корпусе показывает, что доля near-duplicate/over-merged пар при `0.65`-пороге остаётся в границах (не растёт качественно vs baseline `0.75`); см. Acceptance.
3. 0 изменений intra-batch clustering-алгоритма, live-скорера, схемы, public API.
4. ruff+mypy strict, без `Any`/magic-literals; blast radius ≤2 модуля (`config.py` + `batch_processor.py`, +харнесс/тесты в `eval`/`scripts`).

## Discussion
<!-- автономный режим: решения приняты из кода/доков, owner спит; рекомендованный вариант зафиксирован -->

- Q: Подход — переиспользовать `cluster_cosine_threshold` (просто понизить 0.75→0.65 глобально) или ввести ОТДЕЛЬНЫЙ merge-порог? → A: ввести отдельный `cluster_merge_cosine_threshold`, применить ТОЛЬКО в `_find_mergeable_cluster`. → Decision: **two-tier: tight `cluster_cosine_threshold`=0.75 (intra-batch grouping/dedup, не трогаем) + loose `cluster_merge_cosine_threshold`=0.65 (cross-batch cross-channel merge)**. Rationale: глобальное понижение 0.75→0.65 в `cluster.py` сломало бы дедуп (почти-дубли одного текста начнут разъезжаться/слипаться неверно) и intra-batch группировку; D2 рек. вариант явно two-tier (tight→loose). Surgical: один новый setting + одна строка в merge-сайте. Соответствует D2.1→D2.2.

- Q: Точный default loose-порога? Диапазон D2: 0.62–0.70. → A: **0.65**. → Decision: default `_DEFAULT_CLUSTER_MERGE_COSINE_THRESHOLD = 0.65`, env-override `CLUSTER_MERGE_COSINE_THRESHOLD`. Rationale: середина D2-диапазона 0.62–0.70 — балансирует широту vs over-merge; all-MiniLM-L6-v2 на коротких новостных постах об одном событии даёт cosine ~0.6–0.75 для «та же история, разные слова», ~0.45–0.6 для разных историй той же темы → 0.65 захватывает первое, отсекает второе. Настраиваемо: gate-харнесс позволяет owner'у подвинуть в [0.62,0.70] по precision-кривой ПЕРЕД деплоем без кода. ИНВАРИАНТ: `cluster_merge_cosine_threshold <= cluster_cosine_threshold` (loose не строже tight) — провалидировать в config (model_validator), иначе two-tier бессмыслен.

- Q: Как измеряется merge-precision (over-merge guard) офлайн без source-текста (48h purge)? → A: сохранены 384-d центроиды кластеров → cosine-структура восстановима. Reuse `count_duplicate_centroid_pairs` + симуляция merge-решений при двух порогах. → Decision: расширить `backtest_harness.py` (clustering-audit ветку) **merge-precision секцией**: над корпусом центроидов посчитать, сколько cross-channel merge-РЕШЕНИЙ добавил бы порог 0.65 vs 0.75 (NN-пары в окне [0.65,0.75)), и какая доля этих НОВЫХ пар попадает в «over-merge» зону (либо принадлежат разным topic-стрингам/каналам-без-overlap как proxy несвязанности, либо ниже «safe»-полосы). Acceptance-gate: multi-channel-пары растут И over-merge доля новых склеек ≤ заданного бюджета (см. Acceptance). Rationale: единственная offline-сигнатура — центроиды; `count_duplicate_centroid_pairs` уже даёт blocked cosine-pass; добавляем «merge-pair» инспекцию в той же ветке харнесса, не новый рантайм-код. Это проверка ПЛАНА (D2 §5 over-merge), не live-фича.

- Q: Judged-пары для precision (D2 говорит «на judged-парах»)? Их нет под рукой? → A: judged-набор отсутствует (0 алертов, фидбек пуст). → Decision: **proxy-precision сейчас** (topic-string-collision + channel-overlap как proxy «связанности» в харнессе) + **manual spot-check sample** новых [0.65,0.75)-пар (вывести N=20 топ-пар центроидов с topic-стрингами в отчёт для глаз) как human-gate ПЕРЕД деплоем. Когда S0 eval-gate (TASK-122) накопит judged-исходы → перемерить на них (follow-up). Rationale: честно — proxy не = judged precision; но D2 §5 требует именно «не задеплоить вслепую». Spot-check sample + бюджет over-merge — минимальный честный gate. Записать ограничение в отчёт (как `scoring_replay` помечает proxy).

- Q: Setting-новый модуль или extend `config.py`? → A: extend `config.py` рядом с `cluster_cosine_threshold`. → Decision: **extend `config.py`** (`_DEFAULT_*` константа + поле Settings + env-override + model_validator на `loose <= tight`). Rationale: все pipeline-пороги живут там; модуль уже структурирован; reuse валидатор-паттерн (как `collect <= batch` инвариант в config).

- Q: Тронуть ли `_match_topic_by_channels` / scorer (cross_channel-терм)? → A: НЕТ. → Decision: **scorer/matcher не трогаем**. Rationale: scorer уже честно считает `channels_count` как distinct-каналы кластера в 24ч-окне (state-01 §4). Как только merge склеит больше каналов в один кластер, `channels_count`/`cross_channel`/`velocity` поднимутся АВТОМАТИЧЕСКИ — это downstream-эффект, не требует изменений скоринга. Держит дифект surgical.

- Q: Гистерезис между tight grouping и loose merge — не создаст ли это «оба сразу» аномалий? → A: пути ортогональны. → Decision: **intra-batch (`cluster.run`, 0.75) формирует candidate'ы ВНУТРИ батча; cross-batch (`_find_mergeable_cluster`, 0.65) решает, прилепить ли candidate к УЖЕ существующему кластеру другого батча**. Rationale: два разных решения на двух разных стадиях (см. batch_processor docstring) — loose влияет только на «continuity across ticks/channels», tight — на «один ли это пост-кластер сейчас». Нет двойного применения к одному решению.

## Scope

- **Touch ONLY:**
  - `backend/src/config.py` — `_DEFAULT_CLUSTER_MERGE_COSINE_THRESHOLD = 0.65`; поле `cluster_merge_cosine_threshold: float`; env-override doc; model_validator `cluster_merge_cosine_threshold <= cluster_cosine_threshold`.
  - `backend/src/pipeline/batch_processor.py` — в `_find_mergeable_cluster`: `max_distance = 1.0 - settings.cluster_merge_cosine_threshold` (одна строка + обновить docstring: distinct merge-порог).
  - `backend/scripts/backtest_harness.py` + `backend/src/eval/clustering_audit.py` — merge-precision/over-merge секция (новая pure-функция в `clustering_audit` считающая NN-пары в окне [merge,tight) + over-merge proxy-долю + sample; харнесс печатает её).
  - tests: `backend/tests/...` — unit на новый порог в `_find_mergeable_cluster` (распознаёт merge при sim∈[0.65,0.75)), config-валидатор, новая clustering_audit-функция.
- **Do NOT touch:** `pipeline/steps/cluster.py` (intra-batch grouping — tight tier остаётся 0.75), `scorer/*` (cross_channel/velocity поднимутся downstream автоматически), `_match_topic_by_channels`, storage-схема / миграции, public API / openapi, frontend.
- **Blast radius:** один новый settings-поле (env-override, дефолт сохраняет старое поведение при `=0.75`); одна строка merge-сайта; offline-харнесс/тесты. БЕЗ schema/Celery-контракт/API-изменений. 2 рантайм-модуля (`config`, `batch_processor`) + eval-харнесс. Risk: over-merge — закрыт обязательным gate ниже.

## Acceptance Criteria

- [ ] **AC1 (loose merge wires):** Given существующий кластер юзера с центроидом C (свежий, в span) и новый batch-candidate с центроидом C' где cosine(C,C')=0.68 (∈[0.65,0.75)), When `process_user_batch` персистит candidate, Then candidate МЁРЖИТСЯ в существующий кластер (`_find_mergeable_cluster` вернёт его), а НЕ создаёт новый — потому что `cluster_merge_cosine_threshold=0.65`.
- [ ] **AC2 (tight intra-batch unchanged):** Given два поста в ОДНОМ батче с cosine 0.68 между ними, When `cluster.run` группирует, Then они остаются в РАЗНЫХ candidate-группах (intra-batch порог 0.75 не тронут) — two-tier разделение доказано.
- [ ] **AC3 (config invariant):** Given env `CLUSTER_MERGE_COSINE_THRESHOLD=0.80` (> tight 0.75), When Settings грузится, Then ValidationError (loose не может быть строже tight) — инвариант защищён.
- [ ] **AC4 (default preserves old behavior path):** Given `cluster_merge_cosine_threshold` НЕ задан в env, When merge выполняется, Then используется default 0.65 (не 0.75) — и unit фиксирует, что распределение склеек шире, чем при 0.75.
- [ ] **AC5 (MERGE-PRECISION GATE — over-merge guard, BLOCKS DEPLOY):** Given прод/локальный корпус центроидов, When `backtest_harness.py` (merge-precision секция) сравнивает порог 0.65 vs 0.75, Then отчёт выдаёт: (a) число НОВЫХ cross-channel merge-пар в окне [0.65,0.75); (b) over-merge proxy-долю этих пар (доля пар БЕЗ topic/channel-overlap-связности); (c) sample N=20 топ-новых-пар с topic-стрингами для human spot-check. **Gate: деплой ТОЛЬКО если** multi-channel доля растёт (новых merge-пар >0) **И** over-merge proxy-доля новых пар остаётся в бюджете (рек. ≤ near-duplicate baseline-доля при 0.9, т.е. понижение порога НЕ создаёт качественного скачка несвязанных склеек) **И** spot-check sample глазами ownerّа подтверждает «та же история». Без прохождения — НЕ деплоить, подвинуть порог в [0.62,0.70] по precision-кривой.
- [ ] **AC6 (prod-fact, POST-deploy):** Given деплой с gate-пройденным порогом, When psql считает распределение `channels_count` за 2ч-окно, Then доля `channels_count>1` сдвигается к ≥35% БЕЗ роста duplicate-centroid пар (cosine≥0.9) сверх baseline — re-валидация `clustering_audit` на свежем корпусе.

## Plan

1. `backend/src/config.py` — добавить `_DEFAULT_CLUSTER_MERGE_COSINE_THRESHOLD = 0.65` (named, с doc-комментом: distinct loose cross-channel merge tier, env `CLUSTER_MERGE_COSINE_THRESHOLD`); поле `cluster_merge_cosine_threshold: float = _DEFAULT_CLUSTER_MERGE_COSINE_THRESHOLD`; `@model_validator(mode="after")` гарантирующий `cluster_merge_cosine_threshold <= cluster_cosine_threshold` (raise ValueError иначе — паттерн collect<=batch инварианта).
2. `backend/src/pipeline/batch_processor.py:_find_mergeable_cluster` — заменить `max_distance = 1.0 - settings.cluster_cosine_threshold` → `... - settings.cluster_merge_cosine_threshold`; обновить docstring (loose merge-tier distinct от tight intra-batch grouping; почему: cross-channel перефраз).
3. `backend/src/eval/clustering_audit.py` — новая pure-функция `count_merge_window_pairs(centroids, *, merge_threshold, tight_threshold)` → возвращает (a) число NN-пар в [merge,tight), (b) over-merge proxy-долю (нужны topic/handle-метаданные → принять параллельный список меток), (c) sample топ-пар. Reuse blocked cosine-pass паттерн `count_duplicate_centroid_pairs`.
4. `backend/scripts/backtest_harness.py` — в clustering-audit ветке вызвать (3), напечатать merge-precision секцию (новые пары / over-merge proxy% / sample-20) с честной пометкой «proxy, не judged; spot-check глазами».
5. tests — unit: `_find_mergeable_cluster` мёржит при sim∈[0.65,0.75) (AC1), `cluster.run` НЕ группирует при 0.68 (AC2 — вероятно уже покрыт, дополнить), config-валидатор raise при loose>tight (AC3), default=0.65 (AC4), `count_merge_window_pairs` корректность (AC5).

## Invariants

- `cluster_merge_cosine_threshold <= cluster_cosine_threshold` (loose ≤ tight) — иначе two-tier бессмыслен; защищено config-валидатором.
- Intra-batch grouping (`cluster.run`) НЕ меняет поведение — `cluster_cosine_threshold=0.75` нетронут (no dedup regression).
- Immutability/purity pipeline-степов сохранена (`_find_mergeable_cluster` — read-side NN, не мутирует входы).
- Per-user изоляция склейки сохранена (merge-query bounded `Cluster.user_id == user_id`).
- pgvector 384-d инвариант не затронут (только distance-порог меняется, не размерность).
- No magic literals: новый порог — named `_DEFAULT_*` + Settings-поле + env-override.
- **Over-merge gate проходится ПЕРЕД деплоем** (AC5) — глобальный инвариант плана S2 (target §5).

## Edge cases

- **Loose==tight (порог 0.75):** дефолт сохраняет старое поведение → безопасный fallback / A/B-точка; валидатор разрешает равенство.
- **Loose > tight (мисконфиг):** config-валидатор raise при старте — fail-fast, не тихий two-tier-инверт.
- **Over-merge мега-кластер:** span-cap (`cluster_max_span_seconds`) и freshness-window НЕ ослаблены — boilerplate-chain защита от scoring-v2 остаётся; loose-порог влияет только на семантическую близость, не на временные границы.
- **Корпус без topic/handle-меток для proxy:** `count_merge_window_pairs` деградирует к «только число пар» (over-merge% = None в отчёте, помечается «meta missing»).
- **Degenerate/zero центроид:** reuse guard из `count_duplicate_centroid_pairs` (norm==0 → 1.0, не хитит порог).
- **Пустой корпус / <2 кластера:** функция возвращает 0 пар (как `count_duplicate_centroid_pairs`).

## Test plan

- **unit:** new-threshold merge (AC1); intra-batch unchanged (AC2); config invariant raise (AC3); default 0.65 (AC4); `count_merge_window_pairs` (счёт пар в окне + over-merge proxy + sample) (AC5). Reuse фикстуры `_find_mergeable_cluster`-тестов TASK-080.
- **integration:** `process_user_batch` end-to-end — два «канала, одна история» (центроиды cosine 0.68) попадают в ОДИН кластер с `channels_count==2` (downstream широта).
- **offline gate (manual, pre-deploy, AC5):** `uv run python scripts/backtest_harness.py --posts ... --clusters ...` → merge-precision секция; owner смотрит over-merge% + sample-20 ПЕРЕД деплоем.
- **prod-fact (post-deploy, AC6):** psql distribution `channels_count` + `clustering_audit` duplicate-centroid на свежем корпусе.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 4
baseline_commit: 7e8a5fc
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior + MERGE-PRECISION gate AC5)
- [ ] 5 review (auto, adversarial — другой моделью)
- [ ] 5.5 security (N/A — no auth/input/secrets; skip unless harness reads untrusted paths)
- [ ] 6 ship (confirm plan done + gate AC5 passed → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial)
</content>
</invoke>
