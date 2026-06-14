---
id: TASK-082
title: Persist per-post embeddings — пайплайн пишет в posts.embedding уже вычисленный вектор
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "e82d1fd"
branch: "task/082-persist-post-embeddings"
tags: [pipeline, embedding, pgvector, clustering, backtest, vector-ml, compliance]
---

# TASK-082 — Persist per-post embeddings

> Включить go-forward бэктесты кластеризации/эмбеддингов и vector-ML: пайплайн УЖЕ
> считает 384-d вектор на пост (для кластеризации), но выбрасывает его на персисте —
> в проде `posts.embedding` = NULL у ВСЕХ 57 940 строк, а `posts.text` чистится через
> 48ч. Персистим уже посчитанный вектор → векторы переживают TTL текста → будущие
> корпуса становятся бэктестабельны без хранения сырого текста (compliance-friendly).

## Context

Пайплайн `dedup → normalize → embed → cluster` считает вектор на каждый пост:
- `embed.run(posts) -> list[list[float]]` — один 384-d вектор на пост, в порядке
  входа, с проверкой размерности (`_validate_dim`, EMBEDDING_DIM)
  (`backend/src/pipeline/steps/embed.py:82-93`).
- `cluster.run(posts, vectors)` группирует по косинусной близости; внутренний
  `_Group` хранит `self.vectors` (per-post), но `to_candidate()` эмитил только
  ЦЕНТРОИД (`embedding=tuple(... centroid ...)`) и `posts` — per-post векторы
  терялись (`backend/src/pipeline/steps/cluster.py:54-83`).

На персисте `process_user_batch` создаёт `Post(...)` БЕЗ `embedding=` →
дефолт NULL (current behavior, **где вектор выбрасывается**):

```python
# backend/src/pipeline/batch_processor.py (до фикса, :391-402)
session.add(
    Post(
        user_id=user_id,
        channel_id=channel_id,
        cluster_id=cluster_row.id,
        external_id=np_post.external_id,
        views=np_post.metrics.views,
        forwards=np_post.metrics.forwards,
        reactions=np_post.metrics.reactions,
        posted_at=np_post.posted_at,
    )   # ← embedding не передан → NULL
)
```

Колонка УЖЕ существует и nullable — **миграция НЕ нужна**:

```python
# backend/src/storage/models/posts.py:36
embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
```

`EMBEDDING_DIM = 384` — единый источник правды
(`backend/src/storage/models/clusters.py:16`).

## Goal

Минимальный диф: каждая персистируемая строка `Post` несёт тот же 384-d вектор,
который пайплайн уже посчитал для её кластеризации. Без повторного эмбеддинга, без
изменения формул/кластеризации, без миграции. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Как протянуть per-post вектор от embed/cluster до персиста, сохранив чистоту
  шагов? → A: добавить поле в `ClusterCandidate` → Decision: **`ClusterCandidate.
  post_embeddings: tuple[tuple[float, ...], ...]`**, параллельное `posts`. `_Group`
  УЖЕ держит `self.vectors`; `to_candidate()` просто эмитит их. Это тот же вектор,
  что использован для группировки (не центроид, не повторный эмбеддинг). Шаги
  остаются pure/immutable (CONVENTIONS) — только расширен выход.
- Q: Не сломает ли новое поле прямую конструкцию `ClusterCandidate(...)` в тестах? →
  A: нет → Decision: поле с **default `()`** (пустой tuple) — backward-совместимо;
  `run` всегда заполняет его параллельно `posts`.
- Q: Где писать `embedding=` на Post? → A: в цикле персиста, зипуя `candidate.posts`
  с `candidate.post_embeddings` → Decision: `zip(..., strict=False)`; при отсутствии
  per-post векторов (defensive: directly-built candidate) — паддинг `None` →
  embedding=NULL.
- Q: Что если вектор отсутствует/неверной размерности? → A: персистить NULL, не
  падать → Decision: хелпер `_embedding_for_post(vector) -> list[float] | None` —
  возвращает `list(vector)` только при `len == EMBEDDING_DIM`, иначе `None`
  (embedding nullable; инвариант 384-d сохранён, pgvector не корраптится).
- Q: Стоимость хранения? → A: ~1.5KB/пост (384 float4) — скромно при bounded
  collection; вектор переживает 48ч TTL текста, сырой текст не хранится → compliance.
- Q: Миграция? → A: **НЕ нужна** — колонка `posts.embedding Vector(384)` nullable уже
  есть (`posts.py:36`). Если бы требовалась схема — HALT (по контракту задачи).

## Scope

- **Touch ONLY:**
  - `backend/src/pipeline/steps/cluster.py` — поле `ClusterCandidate.post_embeddings`
    (default `()`); `to_candidate()` эмитит per-post векторы из `_Group.vectors`.
  - `backend/src/pipeline/batch_processor.py` — хелпер `_embedding_for_post`; в цикле
    персиста `embedding=_embedding_for_post(post_vector)` через
    `zip(candidate.posts, candidate.post_embeddings)`.
  - Тесты: `backend/tests/unit/test_cluster.py` (per-post векторы в candidate),
    `backend/tests/unit/test_batch_processor.py` (Post несёт non-null 384-d вектор,
    равный тому, что у его кластера), `backend/tests/integration/test_run_batch.py`
    (реальная модель → posts.embedding non-null 384-d).
  - Этот док + `docs/tasks/tasks-index.md`.
- **Do NOT touch:** `frontend/`, `templates/`, scorer, collector, миграции, схему БД.

## Acceptance Criteria

- AC1: `cluster.run` возвращает кандидатов, у которых `post_embeddings` параллелен
  `posts` и равен входным per-post векторам (тот же порядок, те же значения).
- AC2: после `process_user_batch` каждая персистируемая `Post` несёт `embedding`
  non-null, длины EMBEDDING_DIM, равный вектору, использованному для её кластера.
- AC3: вектор отсутствует/неверной размерности → `embedding=NULL`, без краша.
- AC4: миграция не добавлена; `make ci-fast` зелёный (ruff/mypy/unit).

## Verification (G2)

- RED→GREEN unit: `test_cluster_candidate_carries_per_post_embeddings`,
  `test_persists_posts_with_their_embedding` (см. ниже Evidence).
- Integration (CI main-integration, реальная sentence-transformers модель,
  importorskip локально): `test_run_batch_persists_clusters_scoped_by_user` теперь
  также проверяет `posts.embedding` non-null 384-d.
- `make ci-fast`: 725 passed, 266 deselected — зелёный.

## Notes

- Применяется в проде только после деплоя владельцем (новые посты получат вектор;
  ретроспективно NULL-строки не пересчитываются — текст уже почищен через 48ч).
- Стоимость хранения ~1.5KB/пост (384 float4) — скромно при bounded collection.

## Checkpoints
<!-- resume state -->
- [x] Locate: вектор есть в `_Group.vectors`/`embed.run`; Post создаётся без
      `embedding=` (`batch_processor.py`). Колонка nullable Vector(384) — миграция не нужна.
- [x] RED: оба unit-теста падают (нет `post_embeddings`; `Post.embedding is None`).
- [x] GREEN: поле + персист; 30 связанных тестов + полный `make ci-fast` зелёные.
- [x] Doc + index.
- [x] PR #125 https://github.com/BotNet1337/trend-pulse/pull/125 (MERGED).
</content>
</invoke>
