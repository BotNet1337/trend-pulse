---
id: TASK-076
title: Redis OOM guard — explicit maxmemory (noeviction) + capped raw-post buffer
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "3c900b1"
branch: "task/076-redis-oom-guard"
tags: [redis, oom, compose, collector, buffer, broker, reliability]
---

# TASK-076 — Stop the Redis OOM (Stage 0 reanimation)

> Redis на проде OOM-килится cgroup'ом примерно раз в 20 минут. Самый маленький
> диф, который останавливает kill, не теряя при этом брокер/очереди Celery.

## Context

Проверено на проде 2026-06-13 (read-only): `dmesg` показывает повторяющиеся
`Memory cgroup out of memory: Killed process redis-server`. Корень:
`release/compose/redis.yml` стартует `redis:7` БЕЗ `command`, поэтому Redis работает
с `maxmemory 0` (с точки зрения самого Redis — без лимита) и политикой `noeviction`,
тогда как cgroup контейнера ограничен 256M (`deploy.resources.limits.memory: 256M`).
Redis растёт выше 256M → ядро его убивает.

Redis в этой системе — ОДНОВРЕМЕННО брокер/result-backend Celery И буфер сырых
постов. На момент инцидента ~231MB застряли в 4 не-дренированных списках
`raw:telegram:*` (45k–103k постов каждый). Запись в буфер: `collector/buffer.py`
`write_post` → `rpush` в `raw:{kind}:{handle}` без ограничения длины.

## Goal

Redis перестаёт получать OOM-kill, при этом НЕ теряет молча брокерские/очередные
ключи Celery. Жёсткое проектное ограничение: НЕ ставить `allkeys-lru`/`allkeys-random`
(вытеснит задачи Celery и метаданные результатов). Брокер должен при заполнении
шумно отказывать в записи, а не быть убитым. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Какую политику вытеснения ставить? → A: **`noeviction`** (явно).
  Rationale: Redis здесь ещё и брокер Celery; любой `allkeys-*` начнёт молча
  выкидывать поставленные в очередь задачи и результаты. С `noeviction`
  переполненный Redis отвечает на запись `OOM command not allowed...` —
  громкий отказ вместо тихой потери задачи и без kill'а ядром.
- Q: Какое значение `maxmemory`? → A: **224mb** (cgroup-лимит 256M минус запас на
  накладные расходы аллокатора/фрагментацию/RSS-overhead). Параметризовано через
  `REDIS_MAXMEMORY` в `release/version.env` (как остальные тюнаблы compose),
  дефолт `224mb`. Так значение и лимит правятся в одном месте при смене сайзинга.
- Q: Чинить ли здесь корень роста буфера (недренаж/большой lookback)? → A: **Нет.**
  Это отдельные задачи (T2 drain-bug, T3 lookback cap). Здесь — только страховка:
  ограничить длину каждого `raw:{kind}:{handle}` на стороне записи, чтобы одна
  горячая/недренируемая лента не залила Redis. Для детектора виральности recency
  важнее истории, поэтому при переполнении дропаем САМЫЕ СТАРЫЕ посты.
- Q: Как ограничивать длину списка? → A: `rpush` + `ltrim(key, -MAX, -1)` в одной
  pipeline-транзакции на каждую запись (см. Invariants). Константа
  `MAX_RAW_BUFFER_LEN` в `collector/constants.py`. Кап выбран 50_000 — на порядок
  выше нормального тика, но удерживает один список в единицах МБ, не сотнях.
- Decision (owner-gated): фикс начинает действовать на проде ТОЛЬКО после
  `make deploy` владельцем (rolling-update Redis с новым `command`) — compose-правка
  сама по себе прод не меняет. `redis-cli CONFIG SET` вживую — тоже owner-gated.

## Scope

- `release/compose/redis.yml` — добавить explicit `command` с `--maxmemory`
  (`${REDIS_MAXMEMORY}`) и `--maxmemory-policy noeviction`.
- `release/version.env` — новый пин `REDIS_MAXMEMORY=224mb`.
- `backend/src/collector/constants.py` — `MAX_RAW_BUFFER_LEN`.
- `backend/src/collector/buffer.py` — `write_post` ограничивает длину списка.
- `backend/tests/unit/collector/test_buffer_ttl.py` — тесты на кап (TDD).

Вне scope: `frontend/`, `templates/`, корневой drain-bug/lookback, live deploy.

## Acceptance Criteria

- [x] **AC1 — explicit maxmemory.** `release/compose/redis.yml` задаёт `command`
  с `--maxmemory ${REDIS_MAXMEMORY}` и `--maxmemory-policy noeviction`; значение
  `REDIS_MAXMEMORY` (`224mb`) пинится в `release/version.env` и < 256M cgroup-лимита.
- [x] **AC2 — без вытеснения брокера.** Политика — `noeviction` (не `allkeys-*`):
  переполненный Redis отказывает в записи, а не дропает задачи Celery.
- [x] **AC3 — буфер ограничен.** После N (> кап) записей `write_post` в один
  source-ключ `llen(key) == MAX_RAW_BUFFER_LEN`, и сохранены САМЫЕ СВЕЖИЕ посты
  (старые вытеснены).
- [x] **AC4 — TTL и контракт сохранены.** TTL по-прежнему ставится
  (`RAW_POST_TTL_SECONDS`), `write_post` возвращает ключ, ошибки Redis по-прежнему
  поднимают `BufferWriteError`.
- [x] **AC5 — нет дрейфа.** `make ci-fast` зелёный (fmt-check + lint + mypy + unit).

## Plan

1. (RED) Дописать тесты в `test_buffer_ttl.py`: кап длины + сохранение свежих +
   TTL по-прежнему ставится после трима.
2. (GREEN) `MAX_RAW_BUFFER_LEN` в constants; `write_post` — pipeline `rpush` +
   `ltrim(key, -MAX, -1)` + `expire`, всё в одной транзакции.
3. `redis.yml`: `command: redis-server --maxmemory ${REDIS_MAXMEMORY} --maxmemory-policy noeviction`.
4. `version.env`: `REDIS_MAXMEMORY=224mb`.
5. verify: `make ci-fast`; review (adversarial).

## Invariants

- Запись в буфер атомарна: `rpush` + `ltrim` + `expire` в одной MULTI/EXEC,
  чтобы между push и trim конкурентный дренаж не оставил список несогласованным.
- Дренаж (`drain_source`) не меняется — он по-прежнему атомарно read+delete.
- `maxmemory-policy` остаётся `noeviction` — брокер никогда не теряет задачи молча.

## Edge cases

- Список короче капа → `ltrim(-MAX, -1)` — no-op, поведение прежнее.
- Сбой Redis в любой из команд pipeline → `BufferWriteError` (execute поднимает).
- `MAX_RAW_BUFFER_LEN` хранит самые свежие: `rpush` добавляет в хвост,
  `ltrim(key, -MAX, -1)` оставляет последние MAX (хвост) — самые новые.

## Test plan

- Unit (`test_buffer_ttl.py`): существующие зелёные + новые:
  `test_buffer_capped_at_max_len`, `test_buffer_keeps_newest_posts`,
  `test_ttl_set_after_trim`, `test_under_cap_keeps_all`.
- `make ci-fast` (fmt-check + lint + mypy + unit) зелёный.
- Прод-поведение (OOM прекращается) проверяется ТОЛЬКО после owner-deploy — вне
  CI; отмечено в deploy_required.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 6
baseline_commit: "3c900b1"
branch: "task/076-redis-oom-guard"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (skip — diff не касается auth/input/secrets/SQL/public-API)
- [x] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
