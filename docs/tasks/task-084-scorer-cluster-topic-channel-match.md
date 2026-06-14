---
id: TASK-084
title: Scorer cluster→topic matching по channel-overlap, а не по равенству topic-строк
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "56f0213"
branch: "task/084-scorer-cluster-topic-channel-match"
tags: [scorer, topic-match, channel-overlap, prod-bug, scores-zero]
---

# TASK-084 — Cluster→topic matching по channel-overlap

> **Прод-подтверждённая первопричина (2026-06-13), почему scores ВСЕГДА = 0.**
> В `scorer/tasks.py::_score_user` кластер матчился к watched-топику по равенству
> строк: `config = topic_configs.get(cluster.topic)`. Но `topic_configs` ключуется
> по `Watchlist.topic` — это КАТЕГОРИЯ (в проде ровно `"crypto"` и `"tech"`), а
> `Cluster.topic` — это `text[:255]` первого поста (напр. «Паоло Ардоино: …»). Они
> НИКОГДА не равны → `.get()` всегда `None` → `continue` → скорер пишет НОЛЬ строк
> Score, всегда. Поэтому в проде 9 400+ кластеров, но 0 scores / 0 alerts / 0 витрины
> — независимо от уже выкаченных фиксов OOM/backfill/окна (079/080/082/083).

## Context

- `_topic_configs(user_id)` → `dict[str(=watchlist.topic), _TopicConfig]`, где
  `_TopicConfig(threshold, channel_ids)`: `threshold` = MIN порог по watchlists
  топика, `channel_ids` = ОБЪЕДИНЕНИЕ каналов, которые юзер смотрит под этим топиком
  (это и есть знаменатель `cross_channel` = `watched_channels_count`).
- `Cluster.topic: String(255)` — свободный текст (первый пост). `Watchlist.topic:
  String(255)` — ярлык категории; `Watchlist.channel_id` — FK на канал.
- `Post` несёт И `cluster_id` (FK, проставляется в `pipeline.batch_processor`), И
  `channel_id` (FK). Т.е. пост связывает кластер с каналом — это и есть мост для
  матчинга по пересечению каналов.

**Что код делал ДО** (`_score_user`):
```python
config = topic_configs.get(cluster.topic)   # cluster.topic = free text → всегда None
if config is None:
    continue                                  # → ни score, ни alert. ВСЕГДА.
```

## Goal

Минимальный корректный дифф: свежий кластер, чьи посты лежат на каналах, которые
юзер смотрит, получает строку Score под подходящим топиком, и alert срабатывает по
порогу как раньше. Меняется ТОЛЬКО шаг матчинга — `score_window` skip (TASK-079),
`_persist_score`, порог, anti-fatigue guards (TASK-043), идемпотентность алертов и
Free-задержка сохранены.

## Discussion
<!-- durable record -->
- **Правило матчинга:** кластер матчится к watched-топику по **CHANNEL OVERLAP** —
  пересечению множества каналов кластера (distinct `channel_id` его постов В ОКНЕ
  скоринга `score_window_seconds`) с `_TopicConfig.channel_ids` каждого топика.
- **Multi-match policy (product decision):** кластер может пересекать несколько
  watched-топиков (один канал → несколько топиков, или посты на каналах разных
  топиков). Выбран **best-overlap**: кластер скорится РОВНО ОДИН раз под топиком с
  НАИБОЛЬШИМ пересечением каналов; тай-брейк детерминированный — по имени топика
  (по возрастанию), чтобы один и тот же кластер всегда отображался в один и тот же
  топик от тика к тику. Rationale: сохраняет инвариант «один кластер → один Score /
  один Alert», который docstring модуля явно ввёл (TASK-022 убрал per-topic
  дублирование алертов). Альтернатива «score per-topic» вернула бы дубль-алерты на
  один и тот же кластер для каждого пересечённого топика — отвергнута.
  *Флаг для владельца:* если продукт хочет уведомлять под КАЖДЫМ пересечённым
  топиком (другой UX), это меняется здесь же — но дефолт best-overlap.
- **Окно для channel-set:** множество каналов кластера берётся по постам В ТОМ ЖЕ
  окне `score_window_seconds`, что и `_build_score_inputs` — чтобы матчинг и скоринг
  видели один и тот же набор постов (старый пост на разлюбленном канале не должен
  менять матч). Кластер без постов в окне → пустое множество → матча нет → skip
  (ни score, ни alert), что согласуется с TASK-079.
- **`watched_channels_count`:** сохраняется семантика `len(config.channel_ids)` для
  ВЫБРАННОГО (best-overlap) топика — знаменатель `cross_channel` не меняется.
- **Follow-up debt (review MEDIUM-2):** `check_group_guard` дедуплицирует алерты по
  `Cluster.topic == cluster.topic` (свободный текст). Это уже было фактическим no-op
  при старом сломанном матчинге, но теперь, когда алерты реально пойдут, два кластера
  про одно событие с разным free-text topic не будут схлопываться group-guard'ом →
  возможны близкие дубль-алерты. Вне scope TASK-084 (трогаем только шаг матчинга);
  предлагается отдельный TASK на дедуп group-guard по watched-топику / overlap.

## Acceptance Criteria

- AC1: матчинг кластер→топик идёт по пересечению каналов, НЕ по `cluster.topic ==
  watchlist.topic`. Старый `topic_configs.get(cluster.topic)` удалён.
- AC2: кластер со свободным `topic` (не категорией), чьи посты на watched-канале,
  получает строку Score (`viral_score > 0`) — прод-регрессия закрыта (доказано
  `test_freetext_topic_on_watched_channel_now_scores`, был RED: 0 scores).
- AC3: кластер, чьи посты на каналах ВНЕ watchlist, не получает ни score, ни alert
  (`test_cluster_on_unwatched_channel_creates_no_alert`).
- AC4: кластер, пересекающий ДВА топика, скорится один раз под топиком с большим
  overlap; ровно одна строка Score / один alert (`...scores_once_under_best_overlap`,
  был RED: 0 scores).
- AC5: регрессия TASK-079 — кластер без постов в окне скоринга не получает Score,
  даже если каналы пересекают watched-топик (`test_no_posts_in_score_window_still_no_score`).
- AC6: `score_window` skip, `_persist_score` upsert, порог, rate/group guards,
  идемпотентные алерты и Free-задержка не тронуты; `make ci-fast` зелёный.

## Files touched

- `backend/src/scorer/tasks.py` — добавлены `_cluster_channel_ids()` (distinct
  `channel_id` постов кластера в окне) и `_match_topic_by_channels()` (best-overlap
  + детерминированный тай-брейк); `_score_user` заменяет lookup по строке на
  channel-overlap матчинг; обновлён docstring модуля.
- `backend/tests/integration/test_scorer_alerts.py` — старый
  `test_topic_mismatch_creates_no_alert` (кодировал баг — матч по строке) заменён на
  `test_cluster_on_unwatched_channel_creates_no_alert`; добавлены три теста:
  free-text-topic на watched-канале теперь скорится, two-topic best-overlap,
  no-posts-in-window регрессия.
- `docs/tasks/task-084-scorer-cluster-topic-channel-match.md`, `docs/tasks/tasks-index.md`.

## Tests (RED → GREEN)

RED (на коде с матчингом по строке, против живого pgvector):
- `test_freetext_topic_on_watched_channel_now_scores` — FAILED: Score=None
  (`cluster.topic` ≠ `"crypto"` → ноль строк) — **это и есть прод-баг**.
- `test_cluster_overlapping_two_topics_scores_once_under_best_overlap` — FAILED:
  `0 == 1`, ноль строк Score.
- `test_cluster_on_unwatched_channel_creates_no_alert` и
  `test_no_posts_in_score_window_still_no_score` — PASSED (корректно без алерта).

GREEN (после channel-overlap матчинга): весь `test_scorer_alerts.py` зелёный;
`make ci-fast` зелёный.

## Deploy

Прод-эффект (scores>0 → alerts/showcase) требует редеплоя бэкенда владельцем —
PR НЕ мержится и НЕ деплоится этим тиком (оркестратор валидирует + мержит + редеплоит).
