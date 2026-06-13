---
id: TASK-081
title: Offline accuracy harness на прод-корпусе (METRICS-ONLY) — измерительный инструмент + baseline-отчёт
status: review         # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-13
baseline_commit: "fb4d497"
branch: "task/081-offline-backtest-harness"
tags: [eval, backtest, scorer, clustering, metrics, signal-quality, T9]
---

# TASK-081 — Offline accuracy harness (T9)

> Владелец хочет доверенное, воспроизводимое измерение качества сигнала ДО
> инвестиций в более тяжёлый ML. Живых юзеров нет (0 алертов / 0 фидбэка), поэтому
> точность измеряется ОФФЛАЙН на существующем корпусе.

## Context — жёсткая реальность данных (read-only прод, 2026-06-13)

Корпус: **57 940 постов + 9 404 кластера**, НО:
- `posts.text IS NULL` для ВСЕХ строк (retention выпилил текст — ADR-002 §4);
- `posts.embedding IS NULL` для ВСЕХ строк (повекторные эмбеддинги постов никогда
  не персистились);
- `clusters.embedding IS NOT NULL` для всех 9 404 (центроиды 384-d доступны);
- 2 user_id; 0 постов-сирот (`cluster_id` всегда резолвится).

⇒ Нельзя переиграть кластеризацию/эмбеддинги оффлайн (нет текста/векторов). Можно
(a) переиграть логику СКОРИНГА и (b) аудитить СТРУКТУРУ кластеров. Построено ровно это.

## Goal

Воспроизводимый harness (новый модуль `backend/src/eval/` + CLI
`backend/scripts/backtest_harness.py` + экспортёр `scripts/export_corpus.sh`),
который выдаёт baseline-отчёт качества/точности в
`cache/trendpulse-signal-quality-report.md`. БЕЗ изменения прод-логики
scorer/clustering/collector — только импорт и переиспользование.

## Discussion
<!-- durable record -->
- Q: Как переиграть скоринг без БД? → A: переиспользуем РЕАЛЬНУЮ формулу
  `scorer.score.compute_components`/`ScoreInputs` (импорт, не реимплементация), а
  агрегацию входов повторяем по правилам `scorer.tasks._build_score_inputs`, но на
  записях снапшота: окно `posted_at >= updated_at − score_window_seconds` (TASK-079,
  24h), якорь = `Cluster.updated_at` («как если бы во времени»), кластер без постов в
  окне пропускается (зеркалит прод `return None → continue`).
- Q: `channel_avg`? → A: живое значение — историческое 7-дневное AVG по каналу,
  завязано на часы и cold-channel fallback; оффлайн не восстановимо точно. Берём
  документированный fallback (`sum(views)/len(posts)`) и помечаем engagement как
  PROXY.
- Q: `cross_channel`? → A: живых watchlists в корпусе нет → `watched_channels_count`
  — допущение (дефолт 10), помечено в отчёте.
- Q: numpy как зависимость? → A: numpy уже транзитивно тянут `datasketch`/`imagehash`/
  `pgvector` (core deps) → уже на образе воркера; объявлен прямой пин `numpy>=2,<3`,
  чтобы импорт `eval.clustering_audit` (косинус центроидов) был честным.
- Q: данные в git? → A: полные CSV (clusters.csv ≈ 47 MB) gitignored
  (`backend/data/eval/.gitignore`); коммитим маленький sample + документированную
  команду экспорта (`scripts/export_corpus.sh`). Текст НЕ экспортируется (он NULL) →
  нет PII/compliance.

## Acceptance Criteria

- AC1: read-only снапшот метрик из прода (posts: posted_at/channel_id/user_id/
  cluster_id/views/forwards/reactions; clusters: id/user_id/first_seen/updated_at/
  topic/centroid) экспортируется `scripts/export_corpus.sh` (`\copy SELECT`, без
  мутаций). ✅ — 57 940 + 9 404 строк.
- AC2: scoring-replay переигрывает РЕАЛЬНУЮ формулу (`compute_components`) по корпусу,
  степпинг по `posted_at`/окну; отчёт содержит распределение score (гистограмма/
  перцентили), сколько кластеров перешли бы 85/90, разбивку по топикам, lead-time
  PROXY. ✅
- AC3: clustering-audit считает гистограмму размеров, % синглтонов, мега-бакеты,
  дубль-ТОПИКИ и дубль-ЦЕНТРОИДЫ (cosine ≥ 0.9, numpy). ✅ — воспроизведён известный
  baseline точь-в-точь.
- AC4: отчёт `cache/trendpulse-signal-quality-report.md` с конкретными числами,
  способом вычисления каждого и кавеатами (особенно: точность кластеризации/
  эмбеддингов НЕ измерима на этом корпусе → нужен forward text-capture, T11). ✅
- AC5: измерительный harness — настоящий runnable с тестами для чистых хелперов
  (метрики), не one-off. ✅ — `backend/tests/unit/eval/` (28 unit-тестов).
- AC6: прод-логика scorer/clustering/collector НЕ изменена (только импорт);
  `frontend/`/`templates/` не тронуты; `make test` и `make ci-fast` зелёные.

## Baseline numbers (фактически измерено, 2026-06-13)

### Scoring replay (`score_window_seconds=86400`, `watched=10` допущение)
- Кластеров со score: **30 из 9 404**; пропущено (нет постов в окне): 9 374.
- `viral_score`: min 0.762 / p50 17.026 / p90 17.037 / p95 17.039 / p99 17.056 /
  max 17.063 / mean 14.94. Гистограмма (рёбра 0,1,10,50,85,90,100): `[1,3,26,0,0,0,0]`.
- **Кластеров ≥85: 0; ≥90: 0.** velocity доминирует (mean 36.06), engagement PROXY
  mean 1.39, cross_channel mean 0.103.
- median lead-time PROXY: 6 257.6 h (≈ 261 дн) — отпечаток исторического backfill,
  НЕ продуктовый lead-time.

### Clustering-structure audit (воспроизводит известный baseline ✅)
- Синглтоны: **6 368 (67.7% от 9 404)** ≈ известные 68% ✅.
- Мега-бакеты: **4 102 / 1 713 / 1 210** (далее 1 179 / 1 139) ✅.
- Distinct topics: **7 147** ✅; дубль-топик-групп: **753**; кластеров в дублях:
  **3 010 (32%)** ✅.
- Гистограмма размеров (рёбра 1,2,3,6,11,51,501): `[6368,719,587,231,292,140,20]`.
- **Дубль-центроидов (cosine ≥ 0.9): 5 122 пары** (новое) — over-splitting smell.
- 1 047 кластеров без постов (пустые).

## Data caveats (что НЕ измеримо и почему)

1. Точность кластеризации/эмбеддингов — НЕ измерима: исходный текст и повекторные
   эмбеддинги постов отсутствуют. Только структура. → **T11** (forward text-capture).
2. engagement и cross_channel в скоринге — PROXY (cold-channel fallback + допущение
   о числе watched-каналов).
3. lead-time — внутрикорпусный PROXY (first→peak engagement), не реальный.
4. Числа привязаны к снапшоту 2026-06-13; корпус backfill-формы → оффлайн-скоринг
   почти пустой by construction.

## Files touched

- `backend/src/eval/__init__.py`, `corpus.py`, `distribution.py`, `scoring_replay.py`,
  `clustering_audit.py` — новый eval-модуль (чистые хелперы + replay/audit).
- `backend/scripts/export_corpus.sh` — read-only экспортёр снапшота.
- `backend/scripts/backtest_harness.py` — runnable CLI отчёта.
- `backend/tests/unit/eval/` — 28 unit-тестов чистых хелперов.
- `backend/pyproject.toml` — прямой пин `numpy>=2,<3` (уже транзитивно на образе).
- `backend/data/eval/.gitignore` + `*.sample.csv` — gitignore полных CSV + коммит-сэмпл.
- `cache/trendpulse-signal-quality-report.md` — baseline-отчёт (секция T9).
- `docs/tasks/task-081-offline-backtest-harness.md`, `docs/tasks/tasks-index.md`.

## Tests

`make test` (unit) + `make ci-fast` (ruff format/check + mypy) — зелёные.
`backend/tests/unit/eval/` — 28 unit-тестов (percentile/histogram/threshold;
CSV/centroid parse + NULL/orphan; replay reuses real `compute_components`, окно/skip;
audit sizes/dup-topics/dup-centroids incl. block-boundary). Harness реально запущен на
полном корпусе — числа выше из его вывода.

## Checkpoints

- [x] lock: agent-a7b8d775
- [x] locate
- [x] plan (G1)
- [x] do (TDD)
- [x] verify (G2) — make test + ci-fast
- [x] review
- [x] ship (PR, NO merge)
- current_step: ship
