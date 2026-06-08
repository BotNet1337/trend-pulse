---
id: TASK-006
title: Celery infra — app, beat, per-user queues, locks, scheduler
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: ""    # set by executor at ship time
branch: ""             # set by executor at ship time
tags: [backend, celery, redis, beat, queues, multi-tenancy, locks]
---

# TASK-006 — Celery infra (app · beat · per-user queues · locks · scheduler)

> Развернуть Celery-инфраструктуру TrendPulse поверх скелета из task-001: дооснастить `celery_app.py` (broker/result = Redis, JSON-сериализация, task routes), задать beat-расписание в `scheduler.py` (батч `batch:user_{id}` для каждого активного юзера раз в минуту + scorer-тик раз в 5 минут), и обеспечить `max_instances=1`-семантику батча одного юзера через Redis-based per-user lock + идемпотентный drain буфера. Это инфраструктурный seam для pipeline (task-007) и scorer (task-008) — без бизнес-логики обработки.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §4/§5, [`high-level-architecture.md`](../architecture/high-level-architecture.md) §3/§4): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon, multi-tenant SaaS. task-001 уже создал скелет `celery_app.py` (`Celery(broker=…, backend=…)` + ping-задача) и `scheduler.py` (заглушка beat_schedule), task-002 дал схему/модели (`users` с признаком активности), task-005 — общий Redis-буфер сырых постов по источнику. Теперь нужен слой оркестрации задач.

Ключевое архитектурное решение — [ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md): per-user очереди `batch:user_{id}`, отсутствие параллельного запуска батча одного юзера (через единый per-user lock на Redis + идемпотентный drain), отдельный scorer-тик. Beat enqueue'ит батчи активных юзеров раз в минуту; scorer — раз в 5 минут.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md). Критичные для этой задачи: Celery task args JSON-сериализуемы (передаём `user_id`, не ORM-объекты); `max_instances=1` / per-user изоляция; никаких магических литералов (TTL/интервалы — named constants/pydantic-settings, время в секундах); полные type hints, без `Any`/`# type: ignore`; cross-module только через сервис-интерфейсы; секреты только из env.

## Goal

После задачи: worker и beat поднимаются через `make up-d`; в логах worker — `celery@… ready`, beat планирует тики. Beat раз в минуту ставит ровно одну батч-задачу `batch:user_{id}` на каждого активного юзера; повторный батч того же юзера пропускается, пока первый держит per-user lock; scorer-тик встаёт раз в 5 минут. `make ci-fast` зелёный (включая новый unit-тест на lock — AC1). DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по дефолтам ADR-002; все обратимы. -->
- Q: Чем реализовать `max_instances=1` для батча юзера? → A: ADR-002 фиксирует **единый per-user lock (Redis) + идемпотентный drain** → Decision: Redis lock по ключу `lock:batch:user_{id}` с TTL (named constant `BATCH_LOCK_TTL_SECONDS`), `SET NX EX`-семантика acquire, release с проверкой владельца (token), чтобы не снять чужой lock (rationale: beat может попытаться поставить второй батч раньше завершения первого; lock — единственный арбитр, очередь сама дедуп не гарантирует).
- Q: Где живёт lock — отдельный модуль или внутри tasks? → A: тонкий хелпер в `pipeline/` рядом с seam задач → Decision: lock-логика в `pipeline/locks.py` (acquire/contend/release как чистые функции над Redis-клиентом из `storage/`); `pipeline/tasks.py` её использует. Cross-module Redis-клиент берём через `storage`-сервис, не напрямую (CONVENTIONS).
- Q: Как beat узнаёт список активных юзеров? → A: через repository из task-002 → Decision: beat-диспетчер вызывает сервис `list_active_user_ids()` (storage) и enqueue'ит `batch:user_{id}` по каждому id. В рамках этой задачи допустима тонкая обёртка/стаб поверх репозитория task-002 (id-only), без новой бизнес-логики юзеров.
- Q: Очереди — статические или динамические per-user? → A: имя очереди `batch:user_{id}` динамическое (per-tenant) → Decision: задача ставится с `queue=f"batch:user_{user_id}"` через task routes/`apply_async(queue=…)`; worker слушает по шаблону/через подписку диспетчера. Scorer — отдельная статическая очередь `score:global`.
- Q: Что именно делает батч-задача сейчас? → A: это **seam**, не pipeline (task-007) → Decision: `pipeline/tasks.py::run_user_batch(user_id: int)` берёт lock → идемпотентный drain буфера (заглушка-вызов в сервис task-005) → no-op обработка (TODO для task-007) → release lock. Скорер-тик `score_tick()` — заглушка-seam для task-008. Контракт (имена задач, очереди, аргументы) фиксируется здесь.
- Q: Сериализация? → A: CONVENTIONS — JSON-сериализуемые args → Decision: `task_serializer=json`, `result_serializer=json`, `accept_content=["json"]`; задачи принимают только `int`/`str`-аргументы (`user_id`), никаких ORM-объектов.
- Q: Интервалы расписания? → A: overview §4/§5 → Decision: батч — `BATCH_INTERVAL_SECONDS = 60`, scorer — `SCORER_INTERVAL_SECONDS = 300`; вынесены в `config.py`/constants, не хардкод в beat_schedule.

## Scope
> **Раскладка:** трогаем **только `backend/`**; код пакета `trendpulse` (src-layout) + тесты. Окружение/оркестратор (`development/`) уже готов в task-001 — не меняем, используем `make`.

- **Touch ONLY (создать/доработать):**
  - `apps/trendPulse/backend/src/trendpulse/celery_app.py` — дооснастить скелет task-001: broker/result = Redis (из `config.py`), `task_serializer/result_serializer=json`, `accept_content=["json"]`, `task_routes` (`batch:user_*` → per-user очередь, `score_tick` → `score:global`), `task_acks_late`, регистрация задач из `pipeline/tasks.py`. **Сохранить** существующий ping (AC6 task-001 не ломать).
  - `apps/trendPulse/backend/src/trendpulse/scheduler.py` — `beat_schedule`: диспетчер `enqueue_active_user_batches` каждые `BATCH_INTERVAL_SECONDS`, `score_tick` каждые `SCORER_INTERVAL_SECONDS`.
  - `apps/trendPulse/backend/src/trendpulse/pipeline/__init__.py` (если нет), `apps/trendPulse/backend/src/trendpulse/pipeline/tasks.py` — seam-задачи: `run_user_batch(user_id: int)`, `enqueue_active_user_batches()` (beat-диспетчер: `list_active_user_ids()` → `apply_async(queue="batch:user_{id}")`), `score_tick()` (seam для task-008).
  - `apps/trendPulse/backend/src/trendpulse/pipeline/locks.py` — Redis per-user lock: `acquire_user_batch_lock(user_id, token, ttl)`, `release_user_batch_lock(user_id, token)`, context-manager-обёртка; константы `BATCH_LOCK_TTL_SECONDS`.
  - `apps/trendPulse/backend/src/trendpulse/config.py` — добавить (если ещё нет) интервалы/TTL: `batch_interval_seconds`, `scorer_interval_seconds`, lock TTL (named, не магия).
  - `apps/trendPulse/backend/tests/unit/test_locks.py` — **AC1-якорь** (RED→GREEN): acquire/contend/release per-user lock (fakeredis/мок).
  - `apps/trendPulse/backend/tests/unit/test_scheduler.py` — beat_schedule содержит оба тика с верными интервалами; диспетчер ставит по одной задаче на активного юзера (мок repo + `apply_async`).
  - `apps/trendPulse/backend/tests/integration/test_celery_tasks.py` (маркер `integration`) — `run_user_batch.delay()`/контентность через реальный Redis (G2).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`, `development/**` (готово в task-001). Никакой реальной pipeline-обработки (task-007), scorer-формул (task-008), collector-логики (task-005) — только seam-контракты и lock.
- **Blast radius:** задаёт контракт оркестрации для task-007 (батч вызывает pipeline-шаги внутри `run_user_batch` под lock) и task-008 (`score_tick`); фиксирует имена задач/очередей/аргументов и lock-протокол. Потребители — будущие задачи; ломать ping из task-001 нельзя (AC6 task-001).

## Acceptance Criteria
- [ ] **AC1 — per-user lock (failing-test anchor).** Given Redis-клиент (fakeredis/мок), When `acquire_user_batch_lock(user_id, token_a)` → затем `acquire_user_batch_lock(user_id, token_b)` без release, Then первый возвращает `True` (lock взят), второй — `False` (contend); после `release_user_batch_lock(user_id, token_a)` повторный acquire снова `True`; release чужим token'ом не снимает lock. (Тест пишется ПЕРВЫМ, RED.)
- [ ] **AC2 — батч одного юзера не параллелится.** Given `run_user_batch(user_id)` держит lock, When beat/повторный вызов ставит второй батч того же юзера, Then второй батч пропускается (no-op, лог "skipped: locked"), пока первый держит lock; после release — следующий батч проходит. Проверяется в тесте с реальным/фейковым lock.
- [ ] **AC3 — beat enqueue по одному батчу на активного юзера.** Given N активных юзеров (мок `list_active_user_ids()`), When срабатывает `enqueue_active_user_batches()`, Then ровно N вызовов `apply_async` с `queue=f"batch:user_{id}"` (по одному на id), args только JSON-сериализуемые (`user_id: int`).
- [ ] **AC4 — расписание корректное.** Given `scheduler.beat_schedule`, When прочитать его, Then есть запись батч-диспетчера с интервалом `BATCH_INTERVAL_SECONDS` (60) и `score_tick` с `SCORER_INTERVAL_SECONDS` (300); интервалы — из constants/config, не магические литералы.
- [ ] **AC5 — JSON-сериализация задач.** Given `celery_app` конфиг, When прочитать настройки, Then `task_serializer="json"`, `result_serializer="json"`, `accept_content=["json"]`; задачи принимают только `int`/`str` аргументы (нет ORM-объектов в сигнатурах).
- [ ] **AC6 — worker+beat поднимаются.** Given `make build` затем `make up-d`, When `make logs`, Then в логах `worker` — `celery@… ready`; beat планирует тики (видны лог-строки планировщика); существующий ping из task-001 по-прежнему исполняется.
- [ ] **AC7 — поведенческая (G2).** Given поднятый стек, When `run_user_batch.delay(<user_id>)` (через `make sh` + python/celery call), Then задача исполняется и видна в логах worker (`Received task … run_user_batch`, `succeeded`).

## Plan
1. (TDD RED) `tests/unit/test_locks.py` — acquire/contend/release/foreign-release per-user lock на fakeredis; запустить `make ci-fast` → RED (нет `pipeline/locks.py`).
2. `config.py` — добавить `batch_interval_seconds=60`, `scorer_interval_seconds=300`, `batch_lock_ttl_seconds` (pydantic-settings, env-override); named constants для дефолтов.
3. `pipeline/locks.py` — `acquire_user_batch_lock(user_id, token, ttl)` (Redis `SET key value NX EX ttl`), `release_user_batch_lock(user_id, token)` (Lua/проверка владельца перед `DEL`), context-manager `user_batch_lock(user_id)`; Redis-клиент через `storage`-сервис. Прогнать `ci-fast` → GREEN для AC1.
4. `pipeline/tasks.py` — `run_user_batch(user_id: int)`: взять lock → если занят, лог "skipped: locked" и выход (AC2) → идемпотентный drain буфера (вызов сервиса task-005, при отсутствии — стаб) → no-op обработка (TODO task-007) → release lock в `finally`. `enqueue_active_user_batches()`: `list_active_user_ids()` (storage-сервис/стаб) → по каждому `run_user_batch.apply_async(args=[uid], queue=f"batch:user_{uid}")` (AC3). `score_tick()` — seam (TODO task-008).
5. `celery_app.py` — дооснастить: broker/result из `config.redis_url`, `task_serializer/result_serializer=json`, `accept_content=["json"]`, `task_acks_late=True`, `task_routes` (`*run_user_batch` → per-user, `*score_tick` → `score:global`); `include`/import `pipeline.tasks`; **не трогать** ping (AC6 task-001).
6. `scheduler.py` — `beat_schedule`: `{"enqueue-active-user-batches": {task: …enqueue_active_user_batches, schedule: BATCH_INTERVAL_SECONDS}, "score-tick": {task: …score_tick, schedule: SCORER_INTERVAL_SECONDS}}`.
7. (TDD) `tests/unit/test_scheduler.py` — проверка структуры `beat_schedule` (AC4) и диспетчера (мок repo + `apply_async`, AC3); `tests/integration/test_celery_tasks.py` (маркер `integration`) — `run_user_batch.delay()` через реальный Redis (G2/AC7).
8. `make ci-fast` зелёный; затем `make build && make up-d`, проверить AC6 (`make … logs`: `celery@… ready` + beat-тики) и AC7 (`run_user_batch.delay()` → лог worker).

## Invariants
- **`make` (через `development/Makefile`) — единственная точка входа** для build/up/logs/sh/ci; raw `docker compose`/`uv`/`celery` — только внутри таргетов.
- **Celery task args JSON-сериализуемы** — передаём `user_id: int` (и подобные id), НИКОГДА ORM-объекты; `task_serializer=result_serializer=json`, `accept_content=["json"]`.
- **`max_instances=1` для батча юзера** — обеспечивается per-user Redis-lock + идемпотентным drain; нет параллельного `run_user_batch` для одного `user_id`.
- **Lock безопасен** — acquire через `SET NX EX` (всегда с TTL, никогда без срока), release только владельцем (проверка token), чтобы не снять чужой lock.
- **Никаких магических литералов** — интервалы (60/300 с) и lock TTL — named constants/pydantic-settings, время в секундах.
- **Cross-module через сервис-интерфейсы** — Redis-клиент и список активных юзеров берём через `storage`-сервисы, не лезем в их внутренности; `pipeline` не импортирует ORM-модели напрямую в task-аргументы.
- **Полные type hints**, без `Any`/`# type: ignore`; mypy strict проходит.
- **Один образ приложения** для `api`/`worker`/`beat` (различие — команда), как в task-001.
- **Не ломать ping из task-001** (AC6 task-001 остаётся зелёным).

## Edge cases
- **Гонка beat'ов / двойной enqueue** одного юзера → lock арбитрирует; второй батч — чистый no-op (лог), не падает.
- **Crash worker'а внутри батча** (lock не освобождён через `finally`) → lock сам истечёт по `BATCH_LOCK_TTL_SECONDS` (нет вечного дедлока); TTL > типичного батча, но конечен.
- **Release чужого lock** (token mismatch, поздний release после истечения TTL и нового acquire) → проверка владельца перед `DEL` (атомарно, Lua/`GETDEL`-проверка), чужой lock не снимается.
- **Пустой буфер юзера** (drain вернул []) → ранний выход батча, lock всё равно корректно освобождён (идемпотентность).
- **Нет активных юзеров** → `enqueue_active_user_batches()` ставит 0 задач, не падает.
- **Динамические per-user очереди `batch:user_{id}`** → worker должен их слушать (подписка/паттерн); зафиксировать стратегию подписки в комментарии/Makefile, иначе задачи копятся неисполненными.
- **Redis недоступен на старте** → worker/beat не должны молча запускаться без брокера; healthcheck/depends_on из task-001 покрывает порядок старта.
- **Celery + fork на macOS** локально → в контейнере (Linux) ок; локально `--pool=solo` при необходимости (как в task-001).

## Test plan
- **unit:** `tests/unit/test_locks.py` (AC1, RED-first) — acquire/contend/release/foreign-release на fakeredis; `tests/unit/test_scheduler.py` (AC3/AC4) — структура `beat_schedule` + диспетчер (мок repo + `apply_async`, проверка `queue=batch:user_{id}` и одного вызова на юзера); проверка JSON-конфига celery (AC5).
- **integration (по требованию, маркер `integration`):** `tests/integration/test_celery_tasks.py` — `run_user_batch.delay(uid)` через реальный Redis (поднятый compose), идемпотентность повторного батча под lock (AC2).
- **runtime/behavioral (G2):** `make build && make up-d` → `make logs` (AC6: `celery@… ready`, beat-тики, ping жив) → `run_user_batch.delay()` через `make sh` и наблюдение в логах worker (AC7).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (N/A — no auth/secret/input surface; Redis URL via env from task-001)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по ADR-002 (per-user queues/locks/beat) и overview §4/§5, поверх скелета celery_app.py/scheduler.py из task-001; зависит от task-002 (active users repo) и task-005 (общий буфер по источнику). 5.5 security: N/A (no auth/secret/input surface) — нет user-input/auth/OAuth/raw SQL; Redis-URL и креды идут из env через config.py task-001.)
