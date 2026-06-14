---
id: TASK-083
title: Ingest пост-деплой фиксы — коллектор читает СВЕЖИЕ посты (newest-first), runtime-доказательство persist embeddings
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "99dcf57"
branch: "fix/083-ingest-recent-since-and-embedding-proof"
tags: [collector, telethon, ingest, embedding, pipeline, runtime-bug, post-deploy]
---

# TASK-083 — Recent-post ingest + runtime-доказательство persist embeddings

> Пост-деплой верификация прода (main 99dcf57, live) вскрыла два рантайм-бага, мимо
> которых прошли оффлайн-тесты. **Bug A (CRITICAL):** коллектор после Redis-флаша
> читает СТАРЫЕ посты (прод: `posted_at=2024-03-18`/`2024-09`), а не последние часы —
> блокирует все свежие сигналы. **Bug B:** `posts.embedding` остаётся NULL в рантайме
> несмотря на #125 (TASK-082) — на поверку это артефакт того, что NULL-посты записаны
> СТАРЫМ воркером ДО деплоя; сам #125 в рантайме корректен, но его тест был
> `importorskip`-нут и не доказывал прод-путь.

## Context

### Bug A — `reverse=True` отдаёт старейшее окна / при отсутствии маркера — старейшее канала
Прод-улики (read-only ssh, 2026-06-13):
- `posts` id 57941–57943 (channel 4): `external_id=22418..22420`, `posted_at=2024-03-18`,
  `fetched_at=2026-06-13 11:30:26` — диапазон канала 4: `external_id 4..28217`, `2017→2026`.
  Свежий (28217 / 2026-06-12) НЕ прочитан; прочитаны старые низкие ID.
- С момента старта нового воркера (`StartedAt=11:40:47`) каждый тик: `collected posts=0`
  при `since=now-60s` — `reverse=True` + свежий `offset_date` не отдаёт свежак.

Telethon-семантика (подтверждено по
`backend/.venv/.../telethon/client/messages.py`, `_MessagesIter._init`/`_load_next_chunk`):
- `reverse=False` (дефолт): `offset_date` — ЭКСКЛЮЗИВНАЯ ВЕРХНЯЯ граница ("messages
  *previous* to this date"), порядок newest→oldest. (корень task-077: walk всей истории).
- `reverse=True` + `offset_date`: НИЖНЯЯ граница, oldest→newest — но отдаёт СТАРЕЙШЕЕ
  окна первым (cap `limit` режет САМОЕ СВЕЖЕЕ — не тот конец для детектора виральности).
- `reverse=True` + `offset_date` falsy: `_init` ставит `offset_id = 1` → канал с
  САМОГО СТАРОГО сообщения вперёд (ловушка флаша маркера → 2024-посты).

`_resolve_since` (`collector/tasks.py:117`) при отсутствии маркера НИКОГДА не отдаёт
None — фолбэк `now - collect_lookback_seconds` (600s). Покрыт
`test_first_tick_uses_lookback_window_not_full_history`. Т.е. баг — в ИДИОМЕ чтения
ридера, не в вычислении `since`.

**Выбранная идиома:** `iter_messages(entity, reverse=False, limit=MAX_MESSAGES_PER_TICK)`
(БЕЗ `offset_date` → дефолтный newest→oldest) + ранний **BREAK** на первом сообщении
`date < since`. Отдаёт САМЫЕ СВЕЖИЕ посты окна, никогда не deep-pull, корректно и при
отсутствующем маркере (`since = now - lookback`, не None); `limit` — жёсткий бэкстоп.

### Bug B — NULL embedding: артефакт старого воркера, а не дефект #125
- `fetched_at=11:30:26` у трёх NULL-постов < `StartedAt=11:40:47` нового воркера → их
  записал воркер ДО #125. Все 57 943 строки NULL, потому что свежих persist'ов после
  #125 ещё НЕ было (Bug A заморозил коллекцию: `posts=0`).
- Прогон РЕАЛЬНОЙ sentence-transformers модели через полный `process_user_batch`
  (прод-форма: 3 разных поста, реальный `embed_with_cache` поверх fakeredis) →
  3 поста, каждый non-null 384-d. **#125 в рантайме корректен.**
- Реальная дыра: верификация #125 (`test_run_batch.py`) `importorskip`-нута без ml, а
  unit `test_persists_posts_with_their_embedding` патчит `embed_with_cache → None`,
  обходя прод-путь `_run_pipeline(..., vectors=precomputed)`. Нужен CI-тест, который
  гоняет РЕАЛЬНЫЙ кэш-путь и не может тихо скипнуться.

## Goal

Минимальный диф: (A) ридер читает свежее окно newest-first + break, идиома проверена
против установленного telethon; FakeClient моделирует РЕАЛЬНУЮ telethon-семантику (в т.ч.
`offset_id=1`-ловушку и upper-bound дефолта) — тесты ловят и oldest-vs-newest, и
None/absent-`since` регрессии. (B) CI-тест прогоняет прод-путь persist embeddings через
реальный `embed_with_cache` (fakeredis, без ml) — доказательство, что #125 работает в
рантайме и регрессия не пройдёт молча. Без миграций, без правок scorer/frontend.

## Discussion
<!-- durable record -->
- Q: Почему не `reverse=True`+`offset_date` (фикс task-078)? → A: он чинил НАПРАВЛЕНИЕ
  (не walk всей истории), но (1) отдаёт старейшее окна → cap режет свежак; (2) при
  отсутствии маркера `offset_id=1` → старейшее канала (прод-баг) → Decision:
  **`reverse=False` (newest→oldest) + BREAK на `date < since` + `limit`**. Самое свежее
  окна, без deep-pull, корректно при любом `since` (включая фолбэк-окно).
- Q: BREAK или continue на старом сообщении? → A: newest→oldest ⇒ первое `date < since`
  означает, что все последующие старее → **BREAK** (раньше был `continue` — лишний
  проход; теперь стоп).
- Q: Менять `_resolve_since`? → A: нет — фолбэк `now - lookback` уже корректен и покрыт
  тестами (никогда не None). Баг был в идиоме ридера.
- Q: Bug B — это дефект #125? → A: нет → доказано: NULL-посты записаны старым воркером
  (`fetched_at` < `StartedAt`); реальная модель через прод-путь даёт non-null 384-d.
  Дыра — в ВЕРИФИКАЦИИ (over-mock). Decision: CI-тест на реальный `embed_with_cache`.
- Q: Миграция? → A: НЕ нужна (колонка есть, схема не трогается).

## Scope

- **Touch ONLY:**
  - `backend/src/collector/telegram/reader.py` — `_read_one`: `reverse=False` +
    BREAK на `date < since` (newest-first window).
  - `backend/src/collector/constants.py` — комментарий `MAX_MESSAGES_PER_TICK` под
    новую идиому.
  - `backend/tests/unit/collector/conftest.py` — `FakeClient.iter_messages` моделирует
    реальную telethon-семантику (newest→oldest дефолт = upper-bound; reverse=oldest→newest
    с `offset_id=1`-ловушкой при falsy `offset_date`).
  - `backend/tests/unit/collector/test_reader_history_bound.py` — RED→GREEN: newest-first
    приоритет, no-marker не отдаёт старьё, seam `reverse=False`+cap.
  - `backend/tests/unit/test_batch_processor.py` — runtime-faithful тест persist
    embeddings через РЕАЛЬНЫЙ `embed_with_cache` (fakeredis, без ml).
  - Этот док + `docs/tasks/tasks-index.md`.
- **Do NOT touch:** `frontend/`, `templates/`, scorer, миграции/схема,
  `docs/learnings.md`.

## Acceptance Criteria

- AC1 (Bug A): при `since` в недавнем окне ридер отдаёт САМЫЕ СВЕЖИЕ посты окна
  (никогда старейшее), bounded `MAX_MESSAGES_PER_TICK`; на seam — `reverse=False`+`limit`.
- AC2 (Bug A): даже без маркера (фолбэк `now-lookback`) ридер не отдаёт древний бэклог
  канала; FakeClient моделирует `offset_id=1`-ловушку, тест её ловит.
- AC3 (Bug A): окно > cap → возвращаются НОВЕЙШИЕ `MAX_MESSAGES_PER_TICK`, не старейшие.
- AC4 (Bug B): CI-тест (без ml, fakeredis) гоняет прод-путь `process_user_batch` через
  РЕАЛЬНЫЙ `embed_with_cache` → каждая `Post` несёт non-null 384-d вектор.
- AC5: `make ci-fast` зелёный (ruff/mypy/unit).

## Verification (G2)

- RED→GREEN unit (модель — РАНТАЙМ, не моки):
  `test_reader_prioritizes_newest_when_window_exceeds_cap`,
  `test_reader_requests_newest_first_window` — падали на `reverse=True` (отдавал
  старейшее / seam=True), зелёные после фикса.
  `test_reader_no_marker_fetches_recent_not_oldest`,
  `test_reader_does_not_walk_past_since`, `test_reader_caps_messages_per_tick` —
  guard'ы фолбэка/cap.
  `test_persists_post_embeddings_through_real_cache_path` — прод-путь
  (`embed_with_cache` реальный поверх fakeredis), без патча на кэш.
- Реальная модель (worktree, ml установлен): полный `process_user_batch` с реальным
  sentence-transformers → 3 поста non-null 384-d (Bug B не воспроизводится).
- `make ci-fast`: 756 passed, 266 deselected — зелёный.

## Notes

- Применяется в проде только после деплоя владельцем/оркестратором (Bug A —
  свежая коллекция возобновится; Bug B — новые посты получат вектор; ретроспективно
  NULL не пересчитывается, текст почищен через 48ч).
- Прод-улики Bug B (все NULL) — следствие Bug A (заморозка коллекции) + старого
  воркера; после деплоя обоих фиксов свежие посты понесут 384-d вектор.

## Checkpoints
<!-- resume state -->
- [x] Reproduce Bug A: прод-улики (2024-посты, posts=0), telethon-семантика по venv.
- [x] Reproduce Bug B: реальная модель через прод-путь → non-null; NULL = старый воркер.
- [x] RED: reader-тесты падают на `reverse=True` (oldest/seam).
- [x] GREEN: `reverse=False`+BREAK; FakeClient моделирует семантику; 5 reader + новый
      batch_processor тест зелёные.
- [x] `make ci-fast` зелёный (756 passed).
- [x] Doc + index.
- [x] PR #126 https://github.com/BotNet1337/trend-pulse/pull/126 (MERGED).
