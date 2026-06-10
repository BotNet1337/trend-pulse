---
id: TASK-041
title: Historical engagement baseline — channel_avg по скользящему окну канала, не по батчу
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e2-historical-engagement-baseline"
tags: [epic-e2, backend, scorer]
---

# TASK-041 — Historical engagement baseline (Epic E2)

> Сейчас `engagement = (views + forwards·F + reactions·R) / channel_avg`, где `channel_avg`
> считается по постам **текущего кластера/батча** — «спайк» неотличим от обычного дня канала
> (learnings task-008). Заменить знаменатель историческим фоном канала: скользящее окно
> (константа, default 7 дней) по `posts` этого канала. Это прямой удар по «8 из 10 алертов —
> мусор» → удержание.

## Context

Точка расчёта: `backend/src/scorer/tasks.py::_build_score_inputs` (строки ~111–157) — посты
кластера берутся по `Post.cluster_id`, `channel_avg = views / len(posts)` по той же пачке.
Формула: `backend/src/scorer/score.py` (~75–84). Поля метрик на `posts`: `views`, `forwards`,
`reactions` (`storage/models/posts.py`). Ловушка: ретенция сырого контента 48h
(`raw_content_retention_seconds`) — но числовые метрики постов не подпадают под purge raw
content; проверить на locate, что `posts`-строки живут дольше 7 дней (если purge удаляет
строки целиком — окно фактически ограничено ретенцией, зафиксировать floor в Discussion).

## Goal

`channel_avg` = средний engagement-числитель поста канала за скользящее окно
`engagement_baseline_window_seconds` (default 604800 = 7d), с floor-защитой от деления на
малые значения (`engagement_baseline_min_posts`, default 10 — иначе fallback на текущее
поведение). Ровный канал перестаёт триггерить алерты; спайк относительно СВОЕГО фона —
триггерит. DoD = AC.

## Discussion
- Q: Где хранить baseline — agg-таблица или запрос на лету? → Decision: **запрос на лету**
  (AVG по `posts` канала за окно, индекс по `(channel_id, posted_at)` при необходимости —
  по explain). Agg-таблица — преждевременная оптимизация; объёмы E0-эпохи малы. Кэш — Redis
  с TTL (1h, константа), ключ per-channel — опционально, если explain покажет боль.
- Q: Числитель и знаменатель должны быть одной природы? → Decision: да — baseline считается
  по той же weighted-формуле (views + forwards·F + reactions·R), не по голым views.
  Иначе отношение несравнимо между каналами с разной структурой реакций.
- Q: Что при < min_posts историческом фоне (новый канал)? → Decision: fallback на текущий
  batch-avg (поведение как сейчас) + `log_event("baseline_fallback", channel_id=…)` —
  видимость доли холодных каналов.
- Q: Менять ли формулу velocity/cross_channel? → Decision: нет — touch только engagement.

## Scope
- **Touch ONLY:**
  - `backend/src/scorer/tasks.py` — `_build_score_inputs`: расчёт `channel_avg` через
    исторический запрос (+ fallback).
  - `backend/src/scorer/score.py` — только если потребуется вынести weighted-числитель в
    переиспользуемую функцию (engagement_numerator(post)).
  - `backend/src/config.py` — `engagement_baseline_window_seconds` (604800),
    `engagement_baseline_min_posts` (10).
  - `backend/migrations/versions/0013_posts_channel_posted_index.py` — **только если** explain
    покажет seq scan (индекс `(channel_id, posted_at)`).
  - tests: `backend/tests/unit/scorer/test_engagement_baseline.py` (**новый**), правка
    существующих scorer-тестов, где channel_avg замокан батчем.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** velocity/cross_channel-компоненты, alert-trigger-путь (TASK-040 guards),
  pipeline/embed, формат Score.
- **Blast radius:** значения viral_score сместятся для всех юзеров (порог 70 может стать
  строже/мягче) — задокументировать в learnings; скорость score-tick (доп. запрос на канал).

## Acceptance Criteria
- [x] **AC1 — ровный канал не триггерит (failing-test anchor).** Given канал с 7d-фоном
  ≈X и новый пост ≈X, Then engagement ≈ 1.0 (не спайк). RED первым.
- [x] **AC2 — спайк ловится.** Given фон ≈X и пост 10X, Then engagement ≈ 10 и при threshold
  ниже composite-score алерт создаётся.
- [x] **AC3 — холодный канал = fallback.** Given < min_posts постов за окно, Then
  channel_avg = batch-avg (как сейчас) + log_event("baseline_fallback").
- [x] **AC4 — окно скользит.** Посты старше окна не влияют на baseline.
- [x] **AC5 — G2.** Живой стек: два канала (ровный/спайковый) через реальный score-tick —
  алерт только по спайковому; `make ci-fast` зелёный; explain запроса baseline — index/ok.

## Plan
1. **RED:** `test_engagement_baseline.py` — AC1–AC4 (посев posts с posted_at внутри/вне окна).
2. Вынести weighted-числитель; исторический AVG-запрос + min_posts fallback.
3. config-константы; правка существующих scorer-тестов.
4. GREEN + explain + G2; tasks-index на ship.

## Invariants
- Формула композитного score (веса velocity/engagement/cross_channel) не меняется — меняется
  только знаменатель engagement.
- Идемпотентность `_create_alert_idempotent` не затронута.
- No magic literals — окно/min_posts из Settings.
- Числитель и знаменатель — одна weighted-формула.

## Edge cases
- Канал без постов за окно вообще (заглох) → fallback (AC3).
- Посты с NULL-метриками (views=None?) → COALESCE 0 — проверить модель на nullable.
- Purge/retention удаляет старые posts-строки → окно фактически ≤ ретенции; зафиксировать
  floor: если retention < окна, использовать retention (warning в log на старте — опционально).
- Деление на 0 при нулевом фоне → guard: avg <= 0 → fallback.

## Test plan
- **unit:** test_engagement_baseline.py — AC1–AC4; freeze-time/посев posted_at.
- **integration:** score-tick на db_session с посевом 7d-истории (ровный vs спайк).
- **G2:** живой стек AC5 + explain.
- **security:** n/a (внутренняя математика, нет input).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "0600f58062fa0078825f3acb10ae19f923000a42"
branch: "gsd/phase-e2-historical-engagement-baseline"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (n/a — подтверждено review: внутренняя математика, ORM bind params, без нового input)
- [x] 6 ship (PR #52, squash-merged 2026-06-10, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-10 TASK-041)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E2, первая из цепочки 041→042→043. Главный риск — ретенция
posts-строк короче окна baseline: проверить на locate ПЕРВЫМ. Сдвиг распределения score
после смены знаменателя — ожидаем; учесть при пороге 70 в G2.)

### locate (2026-06-10, loop run)
- **Риск ретенции СНЯТ:** `compliance/retention.py:27-39` только NULL-ит `posts.text` (raw
  content) старше 48h, строки НЕ удаляются — метрики живут дольше окна 7d. Floor не нужен.
- channel_avg сегодня: `scorer/tasks.py:146` — `views / len(posts)` по батчу кластера.
- Веса/факторы: `scorer/score.py:27-34` (FORWARD_FACTOR=3, REACTION_FACTOR=2).
- Метрики posts non-nullable (default=0); `posted_at` есть; индекс
  `ix_posts_user_channel_posted (user_id, channel_id, posted_at)` УЖЕ существует →
  миграция 0013 скорее всего не нужна (решение по explain). Последняя миграция: 0012.
- Сессии в scorer — sync `get_session()` context-manager; `log_event(event, **fields)`.
- Тесты к правке: `tests/integration/test_scorer_alerts.py`, новый
  `tests/unit/scorer/test_engagement_baseline.py`, возможно `tests/unit/test_score.py`.

### do (2026-06-10, loop run)
- TDD: RED (4 AC-теста падали ожидаемо) → GREEN. Тест-файл размещён в
  `tests/integration/test_engagement_baseline.py` (нужен живой DB-посев posted_at).
- **Решение:** посты текущего кластера исключаются из исторического baseline
  (exclude_cluster_id) — иначе спайковый пост разбавляет собственный фон (нашли на RED).
- **Решение:** AC3-fallback оставлен на legacy `sum(views)/len(posts)` батча — поведение
  «как сейчас» буквально.
- Индекс `ix_posts_user_channel_posted` покрывает baseline-запрос → миграция 0013 НЕ нужна.
- Итог: 433 unit + 127 integration pass; ruff format/check + mypy strict clean.
- Файлы: config.py (+2 settings), scorer/score.py (engagement_numerator), scorer/tasks.py.

### verify G2 (2026-06-10, loop run)
- ci-fast зелёный (433 unit, ruff/mypy clean). Поведенчески на живом Postgres: ровный канал
  engagement=1.0 → 0 алертов; спайковый 10x → engagement=10.0, 1 алерт (score 20.39 > thr 5);
  холодный канал → fallback + лог `baseline_fallback`. EXPLAIN на 6k строк: Bitmap Index Scan
  по `ix_posts_user_channel_posted` — миграция не нужна.
- **Гочча хоста:** полный `make up` блокирован исчерпанием docker bridge-подсетей
  (development_egress не создаётся) — проверка через one-off контейнер на postgres_net.
  Лечится `docker network prune` (отложено — нужно убедиться, что чужие стеки не пострадают).
- Попутно: dev-БД была на 0010, `make migrate` докатил 0011/0012 (stale dev state).

### review (2026-06-10, loop run)
- Вердикт: pass, блокирующих нет. Применены правки: импорт FORWARD/REACTION_FACTOR поднят на
  module-level + комментарий «weighted_expr зеркалит engagement_numerator»; тестовые
  _WINDOW_SECONDS/_MIN_POSTS читаются из Settings; пустая `tests/unit/scorer/` удалена.
- **Зафиксировано (не код):** асимметрия multi-channel кластера — числитель суммируется по
  всем постам кластера, baseline по primary-каналу; при мульти-канальном кластере engagement
  может завышаться. Скейл E0 — приемлемо; в learnings, follow-up при необходимости.
- Локальный запуск интеграционных тестов с хоста: dev-postgres в internal-сети → пробросен
  через socat-контейнер `tp-pg-fwd` (bridge+postgres_net, host:15432); полный набор:
  124 passed, 10 skipped.
