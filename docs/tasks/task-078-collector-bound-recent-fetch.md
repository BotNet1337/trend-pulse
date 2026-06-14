---
id: TASK-078
title: Telegram-коллектор читает только свежее окно (`since`), а не всю историю канала — фикс full-history backfill
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "6cb80b3"
branch: "task/078-collector-bound-recent-fetch"
deps: [TASK-005, TASK-076]
tags: [collector, telegram, telethon, flood-wait, buffer, ingest, hotfix]
---

# TASK-078 — Ограничить выборку Telegram-коллектора свежим окном `since`

> На каждом collect-тике `reader._read_one` должен читать ТОЛЬКО посты новее
> `since` (свежее окно), а не всю историю канала. Минимальный диф: правильная
> идиома Telethon (`reverse=True` + `offset_date=since`) + жёсткий потолок
> `MAX_MESSAGES_PER_TICK` как страховка.

## Context

**Доказанный корень (диагностика T2, task-077):**
`backend/src/collector/telegram/reader.py` (~строка 203) звал
`client.iter_messages(entity, offset_date=since)` БЕЗ `reverse=True`, БЕЗ
`min_id`, БЕЗ `limit`. При дефолтном `reverse=False` у Telethon `offset_date` —
это ВЕРХНЯЯ граница («messages *previous* to this date will be retrieved»,
exclusive), и итератор уходит назад по ВСЕЙ истории канала
(на проде посты охватывали 2026→2017). То есть `since` НЕ работал как нижняя
граница.

Последствия на проде: штормы FLOOD_WAIT на `GetHistoryRequest`, raw-буферы
росли до 100k+ постов, `lock:collect:tick` держался весь TTL (~600s) и душил
весь ингест, пайплайн никогда не устаканивался → `viral_score=0`.

Существующий тест `test_first_tick_uses_lookback_window_not_full_history`
проверял только ЗНАЧЕНИЕ `since` и использовал `FakeCollector`, который не
моделирует обратный обход Telethon — поэтому транспортный баг был не покрыт.

## Discussion
<!-- durable record -->
- Q: Какая точно идиома Telethon читает «строго новее даты»? → A: проверено по
  установленному исходнику telethon (`.venv/.../telethon/client/messages.py`,
  докстринг `iter_messages`): `reverse=True` → «messages returned from oldest to
  newest», и «the meaning of `offset_id` and `offset_date` parameters is
  reversed, although they will still be exclusive» → с `reverse=True`
  `offset_date=since` означает «строго ПОЗЖЕ `since`, oldest→newest». Default
  `reverse=False`: `offset_date` exclusive ВЕРХНЯЯ граница (backward walk = баг).
  Decision: `iter_messages(entity, offset_date=since, reverse=True, limit=MAX_MESSAGES_PER_TICK)`.
- Q: Нужен ли локальный фильтр `message.date >= since`, если сервер уже фильтрует?
  → A: да, оборонительно → Decision: оставить `if since is not None and
  message.date is not None and message.date < since: continue` — фиксирует нижнюю
  границу на нашей стороне независимо от серверного exclusive-offset и не вредит.
- Q: Где задать потолок? → A: именованная константа в `collector/constants.py` →
  Decision: `MAX_MESSAGES_PER_TICK = 500` (CONVENTIONS: no magic literals). Маппится
  на `iter_messages(limit=...)` — даже мисконфиг `since` (огромный lookback, фолбэк
  на corrupt-marker, `None`) не сможет дёрнуть глубокий pull.
- Q: Менять ли `collect_lookback_seconds`? → A: нет → Decision: дефолт = 600s
  (10 мин), это уже свежее окно. Реальный фикс — граница в reader, а не конфиг.
  Скоуп не расширяем.

## Scope

Хирургия — только:
- `backend/src/collector/telegram/reader.py` — вызов `iter_messages` + оборонительный фильтр.
- `backend/src/collector/telegram/client.py` — `TelegramClientProtocol.iter_messages` (новые kwargs `reverse`/`limit`).
- `backend/src/collector/constants.py` — `MAX_MESSAGES_PER_TICK`.
- тесты: `tests/unit/collector/conftest.py` (FakeClient моделирует семантику Telethon),
  новый `tests/unit/collector/test_reader_history_bound.py`,
  новый `tests/unit/collector/test_buffer_drain_roundtrip.py`,
  `tests/unit/collector/test_account_pool_rotation.py` (синхронизация сигнатуры `_FloodOnceClient.iter_messages`).
- этот task-doc + `tasks-index.md`.

НЕ трогаем: `frontend/`, `templates/` (их правит параллельный луп), `config.py` (lookback ок).

## Acceptance Criteria

- AC1: `reader._read_one` зовёт `iter_messages` c `reverse=True`, `offset_date=since`,
  `limit=MAX_MESSAGES_PER_TICK`; постов с `date < since` не буферит.
- AC2: при истории, охватывающей `since`, reader отдаёт только посты `date >= since`
  (никогда — старый бэклог).
- AC3: даже при `since=None`/огромном окне читается не более `MAX_MESSAGES_PER_TICK`.
- AC4: контракт buffer↔drain зафиксирован round-trip-тестами (что написал
  `write_post`, то находит `drain_source` по тому же ключу, с полной реконструкцией).
- AC5: существующий FLOOD_WAIT-хэндлинг и rotation не сломаны (весь collector unit-сьют зелёный).

## Plan

1. (do/TDD) RED: `test_reader_history_bound.py` — 3 теста на границу `since`,
   forward-scan kwargs и потолок; `FakeClient` моделирует обратный/прямой обход
   Telethon. + `test_buffer_drain_roundtrip.py` — фиксирует контракт.
2. (do) GREEN: `MAX_MESSAGES_PER_TICK` в constants; `iter_messages`-вызов в reader
   (`reverse=True`+`offset_date`+`limit`) + оборонительный фильтр; расширить
   Protocol kwargs; синхронизировать `_FloodOnceClient`.
3. (verify) `make test` + `make ci-fast` (format/ruff/mypy/unit).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 6
baseline_commit: "6cb80b3"
branch: "task/078-collector-bound-recent-fetch"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal)
- [x] 3 do (TDD: failing reader-level test → minimal code)
- [x] 4 verify (G2 — tests + ci-fast)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (skip — нет auth/input/secrets/SQL; транспорт TG)
- [x] 6 ship — PR #121 https://github.com/BotNet1337/trend-pulse/pull/121 (MERGED)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(do/verify 2026-06-13, executor agent-a29d253, baseline 6cb80b3 = #120 redis-OOM
fix off main: Telethon-семантика проверена по установленному исходнику
`backend/.venv/lib/python3.12/site-packages/telethon/client/messages.py` —
докстринг `iter_messages` подтверждает: default `reverse=False` → `offset_date`
exclusive ВЕРХНЯЯ граница + backward walk (баг); `reverse=True` → oldest→newest и
смысл `offset_date` инвертируется в exclusive НИЖНЮЮ границу (фикс). TDD: RED —
3 reader-теста падали (no `reverse`/`limit`, отдавал 700/700 при потолке 500,
`reverse` is False); round-trip-тесты сразу зелёные (контракт цел, теперь
залочен). GREEN: фикс reader + Protocol + constants; регресс в
`test_account_pool_rotation::test_pool1_short_flood_retries_without_reconnecting`
(локальный `_FloodOnceClient.iter_messages` имел старую сигнатуру) — синхронизирован.
Прод-эффект требует owner-деплоя (`make deploy` owner-gated) вместе с T1 redis-фиксом.)
