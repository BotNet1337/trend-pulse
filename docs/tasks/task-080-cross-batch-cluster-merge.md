---
id: TASK-080
title: Cross-batch cluster merge — перестать плодить дубликаты кластеров одной темы
status: review         # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-13
baseline_commit: "fb4d497"
branch: "task/080-cross-batch-cluster-merge"
tags: [pipeline, clustering, pgvector, cross-batch, merge, dedup]
---

# TASK-080 — Cross-batch cluster merge

> Прод 2026-06-13: 9 404 кластера, но только 7 147 различных тем — **753 темы
> размазаны по 3 010 кластерам (32% всех кластеров)**. Пример: «Гэри Генслер…»
> существует как 3 отдельных кластера по 1 139 постов. Причина — кластеризация
> делается per-batch БЕЗ кросс-батч-непрерывности: одна и та же тема, повторяясь
> от тика к тику, каждый раз порождает новый `Cluster`.

## Context

`pipeline/steps/cluster.py::run` делает жадную single-link cosine-кластеризацию
(порог `cluster_cosine_threshold`, дефолт 0.75) ТОЛЬКО по постам текущего батча.
`pipeline/batch_processor.py::process_user_batch` сохраняет каждый
`ClusterCandidate` батча как НОВУЮ строку `Cluster` каждый раз.

**Что код делал ДО изменения** (`process_user_batch`, persist-путь,
`backend/src/pipeline/batch_processor.py`):

```python
with get_session() as session:
    handle_to_channel_id = _build_handle_to_channel_id(session, all_normalized)
    for candidate in candidates:
        cluster_row = _candidate_to_cluster(candidate, user_id)  # ВСЕГДА новый Cluster
        session.add(cluster_row)
        session.flush()  # obtain cluster_row.id before persisting posts
        for np_post in candidate.posts:
            ...
            session.add(Post(... cluster_id=cluster_row.id ...))
```

То есть для каждого кандидата — `session.add(Cluster(...))` безусловно. Никакого
поиска уже существующего кластера той же темы у этого пользователя нет → дубли.

Таблица `clusters`: `embedding Vector(384)` (центроид), tenant-scoped по `user_id`,
индекс `ix_clusters_user_updated (user_id, updated_at)`. pgvector доступен (cosine
через оператор `<=>`).

## Goal

Минимальный дифф: кандидат батча **СЛИВАЕТСЯ** в уже существующий недавний кластер
того же пользователя, если их центроиды похожи (cosine ≥ `cluster_cosine_threshold`)
и кластер свежий (в окне `cluster_merge_window_seconds`), вместо безусловного
создания новой строки. Иначе — создаётся новый кластер (поведение сегодня).

## Discussion
<!-- durable record -->
- Q: Какое окно свежести? Переиспользовать или новая настройка? → A: новая
  выделенная настройка **`cluster_merge_window_seconds`** (дефолт **86400s = 24h**).
  Rationale: семантика отлична от соседних окон — `scorer_recent_window_seconds`
  (свежесть кластера для скоринга, 1h — слишком узко, сливали бы редко),
  `score_window_seconds`/`trending_window_seconds` (окна скоринга/витрины). Окно
  слияния должно ловить тему, повторяющуюся в течение суток; 24h — sensible default,
  меняется одним env `CLUSTER_MERGE_WINDOW_SECONDS`.
- Q: distance↔similarity у pgvector? → A: оператор `<=>` возвращает cosine
  **DISTANCE** = `1 - cosine_similarity`. Значит «similarity ≥ threshold» ⇔
  «distance ≤ 1 - threshold». NN-запрос: `ORDER BY embedding <=> :centroid LIMIT 1`,
  ограничен `user_id` + `updated_at >= window_start`, затем кандидат проверяется
  фильтром `distance <= 1 - threshold` в самом SQL (`WHERE`), чтобы не сливать в
  непохожий ближайший.
- Q: обновление центроида? → A: бегущее среднее по числу членов. У строки `Cluster`
  нет счётчика членов, поэтому фактический вес берём из `COUNT(Post)` уже
  привязанных к кластеру постов (надёжно, идемпотентно): новый центроид =
  `(old·n_existing + cand_centroid·n_candidate) / (n_existing + n_candidate)`.
- Q: гонки/идемпотентность? → A: слияния идут под существующим per-user batch-локом
  (`max_instances=1`), два батча одного юзера не гоняются. Повторный батч не
  двоит посты: дедуп по `external_id` уже выше по потоку (collector/dedup), а посты
  несут `cluster_id`.
- Q: scope? → A: только cross-batch merge (убивает 3 010 дублей). Mega-bucket taming
  и рекалибровка порога — отдельная будущая задача, НЕ трогаем здесь.

## Acceptance Criteria

- AC1: при persist каждый `ClusterCandidate` ищет ближайший СУЩЕСТВУЮЩИЙ кластер
  того же `user_id`, свежий (`updated_at >= now - cluster_merge_window_seconds`),
  с cosine-similarity центроидов ≥ `cluster_cosine_threshold` (pgvector
  `<=>` ≤ `1 - threshold`). Найден → посты привязываются к нему, центроид
  пересчитывается бегущим средним, `updated_at` обновляется. Нет → новый кластер.
- AC2: два батча с кандидатом одной темы дают ОДИН кластер (merge), а не два
  (тест `test_second_batch_same_topic_merges_into_existing`).
- AC3: непохожий кандидат всё равно создаёт новый кластер
  (тест `test_dissimilar_candidate_creates_new_cluster`).
- AC4: древний (вне окна свежести) кластер НЕ сливается — создаётся новый
  (тест `test_ancient_cluster_not_merged`).
- AC5: `cluster_merge_window_seconds` — pydantic-settings tunable с именованным
  дефолтом (`_DEFAULT_CLUSTER_MERGE_WINDOW_SECONDS = 86_400`), override через
  `CLUSTER_MERGE_WINDOW_SECONDS`.
- AC6: чистая кластеризация (`cluster.py::run`) и per-batch поведение не сломаны;
  `make test` и `make ci-fast` зелёные.

## Files touched

- `backend/src/config.py` — настройка `cluster_merge_window_seconds` + дефолт.
- `backend/src/pipeline/batch_processor.py` — `_find_mergeable_cluster` (pgvector NN
  под user+freshness+distance), `_merged_centroid` (бегущее среднее), persist-цикл
  сливает в найденный кластер или создаёт новый.
- `backend/tests/unit/test_batch_processor.py` — unit-тесты merge/no-merge на mock.
- `backend/tests/integration/test_run_batch.py` — integration merge/freshness на
  реальном pgvector.
- `docs/tasks/task-080-cross-batch-cluster-merge.md`, `docs/tasks/tasks-index.md`.

## merge_query

```sql
SELECT id, embedding <=> :centroid AS distance
FROM clusters
WHERE user_id = :user_id
  AND updated_at >= :window_start
  AND embedding <=> :centroid <= :max_distance   -- max_distance = 1 - threshold
ORDER BY embedding <=> :centroid
LIMIT 1
```

pgvector `<=>` = cosine DISTANCE = `1 - cosine_similarity`. «similarity ≥ threshold»
⇔ «distance ≤ 1 - threshold». Реализовано через SQLAlchemy `Cluster.embedding.cosine_distance(centroid)`.

## Checkpoints

- [x] locate
- [x] plan (G1)
- [x] do (TDD)
- [x] verify (G2)
- [ ] review
- [ ] ship
- current_step: do→verify
- lock: agent-a5f3f69034249e8ea

## Tests (RED → GREEN)

См. финальный отчёт исполнителя — RED доказан на коде без merge, GREEN после правки.
</content>
</invoke>
