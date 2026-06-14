---
id: TASK-079
title: Scorer velocity/engagement по СКОЛЬЗЯЩЕМУ окну, а не за всю жизнь кластера
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "85618ed"
branch: "task/079-scorer-rolling-window"
tags: [scorer, velocity, engagement, config, rolling-window]
---

# TASK-079 — Scorer velocity/engagement по скользящему окну

> viral_score должен мерить НЕДАВНИЙ всплеск (burst), а не всю историю кластера.
> Долгоживущий кластер копит посты сутками: `delta_hours` растёт → velocity
> схлопывается, а старые посты разбавляют engagement. На корпусе исторического
> бэкфилла из-за этого все кластеры выглядели «плоскими» (вклад в scores=0).
> T3 остановил новый бэкфилл, но кластер всё равно живёт и набирает посты от тика
> к тику — безлимитная агрегация за всю жизнь по-прежнему неверна.

## Context

Скорер считает viral_score per (user, cluster):
- `scorer/score.py`: `viral_score = velocity·0.4 + engagement·0.35 + cross_channel·0.25`,
  `velocity = log1p(Δchannel_count)/Δhours`, `engagement = (views + 3·forwards +
  2·reactions)/channel_avg`. Формула чистая, без I/O.
- `scorer/tasks.py::_build_score_inputs` агрегирует метрики + `posted_at`-span по
  постам кластера; `_recent_clusters` отбирает кластеры по `Cluster.updated_at >=
  window_start` (`scorer_recent_window_seconds`).

**Что код делал ДО изменения** (`_build_score_inputs`, `backend/src/scorer/tasks.py`):

```python
stmt = select(Post).where(Post.user_id == user_id).where(Post.cluster_id == cluster_id)
posts = list(session.scalars(stmt).all())
if not posts:
    return ScoreInputs(views=0, forwards=0, reactions=0, channel_avg=0.0,
                       delta_channel_count=0, delta_hours=0.0,
                       unique_channels_count=0, watched_channels_count=...)
...
earliest = min(p.posted_at for p in posts)
latest = max(p.posted_at for p in posts)
delta_hours = (latest - earliest).total_seconds() / _SECONDS_PER_HOUR
```

То есть выборка постов кластера **БЕЗ фильтра по `posted_at`** — агрегация
views/forwards/reactions, `delta_hours` и счётчиков каналов шла по ВСЕМ постам
кластера за всю его жизнь. Старый docstring модуля даже утверждал, что
«Cluster freshness bounds recency, so the per-cluster post query needs no separate
`posted_at` window» — это и есть неверное допущение: свежесть по `updated_at` НЕ
ограничивает разброс `posted_at` внутри кластера.

`channel_avg` (TASK-041) — отдельный исторический знаменатель по 7-дневному
окну канала (`engagement_baseline_window_seconds`), это НЕ окно скоринга и не
трогается.

## Goal

Минимальный дифф: входы скоринга кластера считаются ТОЛЬКО по постам в недавнем
окне (`score_window_seconds`, дефолт 24h), а не за всё время. Формулы
velocity/engagement/cross_channel не меняются. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Длина окна и переиспользовать ли существующую настройку? → A: новая выделенная
  настройка **`score_window_seconds`** (дефолт **24h = 86400s**). Rationale: семантика
  отличается от соседних окон — `scorer_recent_window_seconds` (свежесть кластера по
  `updated_at`, 1h), `trending_window_seconds` (отбор витрины), `engagement_baseline_
  window_seconds` (7d-база channel_avg). Смешивать интенты нельзя; задача прямо просит
  предпочесть отдельную настройку. 24h — sensible default для «burst»; на 48h меняется
  одним env `SCORE_WINDOW_SECONDS=172800`.
- Q: Кластер без постов в окне? → A: `_build_score_inputs` возвращает `None`, вызывающий
  `_score_user` делает `continue` — ни строки Score, ни алерта, без деления на ноль и без
  полезной нагрузки 0-score. Раньше возвращались занулённые входы и строка Score всё
  равно писалась (загрязнение).
- Q: Один пост в окне? → A: velocity использует уже существующий клэмп
  `MIN_WINDOW_HOURS` (Δhours→1 минута), поведение не меняется.

## Acceptance Criteria

- AC1: `_build_score_inputs` агрегирует views/forwards/reactions, `delta_hours` и
  счётчики каналов ТОЛЬКО по постам с `posted_at >= now - score_window_seconds`.
- AC2: посты вне окна не влияют ни на один компонент score (доказано тестом:
  два идентичных кластера с одинаковым свежим burst, у одного — гигантский пост
  3 дня назад → равные viral_score).
- AC3: кластер, у которого все посты старше окна, пропускается чисто — нет строки
  Score, нет Alert (доказано тестом `test_score_window_empty_skips_cleanly`).
- AC4: `score_window_seconds` — pydantic-settings tunable с именованным дефолтом
  (`_DEFAULT_SCORE_WINDOW_SECONDS = 86_400`), override через `SCORE_WINDOW_SECONDS`.
- AC5: поведение `channel_avg` (7d база, TASK-041) сохранено — окно скоринга и
  историческая база не смешаны (доказано прохождением `test_engagement_baseline.py`).
- AC6: формулы velocity/engagement/cross_channel не изменены; `make test` и
  `make ci-fast` зелёные.

## Files touched

- `backend/src/config.py` — новая настройка `score_window_seconds` + именованный
  дефолт `_DEFAULT_SCORE_WINDOW_SECONDS` (24h) с разъяснением отличия от соседних окон.
- `backend/src/scorer/tasks.py` — `_build_score_inputs` фильтрует посты по
  `posted_at >= now - score_window_seconds`, возвращает `ScoreInputs | None`;
  `_score_user` пропускает кластер при `None`; обновлён docstring модуля.
- `backend/tests/integration/test_scorer_alerts.py` — два теста: out-of-window posts
  не влияют на score; пустое окно пропускается чисто.
- `docs/tasks/task-079-scorer-rolling-window.md`, `docs/tasks/tasks-index.md`.

## Tests (RED → GREEN)

RED (на безлимитном коде): `test_score_window_excludes_old_posts` падал
(score кластера B ≠ A — старый пост протёк), `test_score_window_empty_skips_cleanly`
падал (кластер со старым постом всё равно эмитил Score + Alert). GREEN после правки:
весь `test_scorer_alerts.py` 8 passed, `test_engagement_baseline.py` 4 passed,
полный integration-набор 257 passed / 7 skipped, `make ci-fast` 710 unit passed.
