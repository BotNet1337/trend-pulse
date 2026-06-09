---
id: TASK-023
title: Reliability — re-sweep pending-алертов + Celery-liveness в /ready + alerts-by-status метрика
status: planned          # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-023-reliability-pending-sweep"
tags: [epic-d, backend, reliability, ops]
---

# TASK-023 — Reliability: pending-sweep + Celery /ready + status-метрика (Epic D)

> Закрыть надёжностный footgun (learnings task-008): если брокер/worker падал в момент доставки, alert остаётся `delivery_status='pending'` навсегда — никто не ре-энкьюит `dispatch_alert`. (1) Beat-задача `resweep_pending_alerts` — находит `alerts` со `pending` старше N минут и ре-энкьюит доставку, идемпотентно (без дублей). (2) `/ready` (`api/routes/ops.py`) — добавить проверку живости Celery worker (`inspect().ping()` с timeout ИЛИ heartbeat-ключ в Redis); не вешать probe. (3) Метрика/лог alerts-by-status для алертинга на рост pending. delivery-логику доставки (task-009) по сути не меняем — только ре-энкьюим существующий `dispatch_alert`.

## Context

`backend/src/alerts/tasks.py`: `dispatch_alert(alert_id)` (`DISPATCH_ALERT_TASK = "alerts.tasks.dispatch_alert"`) энкьюится скорером сразу после создания alert; ретраит `TransientDeliveryError` с backoff, на исчерпании ставит `delivery_status = DELIVERY_STATUS_FAILED`. `backend/src/alerts/notifier.py` ставит `DELIVERED`/`FAILED`. Footgun: если до/во время вызова `dispatch_alert` падает брокер или worker, задача теряется, а строка осталась `pending` (дефолт при создании) — нет повторной попытки. learnings task-008 это отмечает.

`backend/src/api/routes/ops.py`: `GET /ready` (task-011) — readiness, проверяет `_check_db()` (`pool_pre_ping`) и `_check_redis()` (`client.ping()`), оба «bounded», probe не вешается. Celery worker НЕ проверяется — `/ready` зелёный даже если worker мёртв и доставка стоит.

`backend/src/scheduler.py`: `beat_schedule` — entries `enqueue-active-user-batches`, `score-tick`, `purge-expired-raw-content` (интервалы из `Settings`: `batch_interval_seconds`, `scorer_interval_seconds`, `retention_purge_interval_seconds`). Сюда добавляется `resweep-pending-alerts` с интервалом из новой настройки. `backend/src/celery_app.py` — `celery_app`, `conf.beat_schedule = beat_schedule`. Observability — `backend/src/observability/` (logging/celery_logging) — место для status-метрики/лога.

Модель `alerts.py`: `first_seen` (timezone-aware), `delivery_status` (`pending`/`delivered`/`failed`). Конвенции: no magic literals (N минут, timeout — settings/named const), bind-params, tenant НЕ важен (системный sweep по всем), idempotent.

## Goal

После задачи: beat-задача `resweep_pending_alerts` периодически находит `alerts` с `delivery_status='pending' AND first_seen < now() - interval(N мин)` и ре-энкьюит `dispatch_alert`, идемпотентно (доставка не дублируется — `notifier` уже гардит `DELIVERED`, sweep не трогает не-pending); N и интервал sweep — named const/settings. `/ready` краснеет (`503`), если Celery worker мёртв (через `inspect().ping()` с timeout ИЛИ heartbeat-ключ в Redis), и НЕ вешается (bounded, как db/redis-проверки). Доступна метрика/лог alerts-by-status (для алертинга на рост pending). integration: симуляция enqueue-failure → sweep доставляет после восстановления.

## Discussion
<!-- durable record of clarifications; обратимы. -->
- Q: Как ловить «потерянные» pending? → A: beat-периодика → Decision: `resweep_pending_alerts` ищет `pending` старше `N` минут (грейс, чтобы не гоняться за свежими в полёте) и ре-энкьюит `dispatch_alert(alert_id)`. N — `Settings.pending_resweep_grace_seconds` (named).
- Q: Идемпотентность ре-доставки? → A: нельзя слать дважды → Decision: `dispatch_alert`/`notifier` уже гардит `DELIVERED` (early-return при `delivery_status == DELIVERED`); sweep выбирает только `pending` (не failed/delivered); ре-энкьюенный `dispatch_alert` повторно проверит статус под сессией. Без нового состояния доставки.
- Q: failed тоже ре-свипать? → A: failed = исчерпаны ретраи (осознанный терминал) → Decision: sweep берёт ТОЛЬКО `pending` (зависшие), не `failed` (иначе бесконечная ре-доставка мёртвых). failed — отдельный manual/alерт-кейс.
- Q: Как проверять worker в `/ready` не вешая probe? → A: `inspect().ping()` блокирующий → Decision: `celery_app.control.inspect(timeout=...).ping()` с коротким bounded timeout ИЛИ worker пишет heartbeat-ключ в Redis (TTL), `/ready` читает ключ (дешевле, не дёргает control-bus). Решение исполнителя; обязателен bound (как `_check_db`/`_check_redis`).
- Q: `/ready` 503 при мёртвом worker? → A: readiness = «готов обслуживать», доставка зависит от worker → Decision: worker down → `/ready` `503` (как db/redis fail). `/health` остаётся чистой liveness (не трогаем).
- Q: Метрика alerts-by-status? → A: нужен сигнал на рост pending → Decision: счётчик/лог по `delivery_status` (count pending/delivered/failed) — через `observability/` (Prometheus-метрика если есть стек, иначе структурный лог). Источник алертинга на застой доставки.
- Q: Гонка sweep и in-flight dispatch? → A: свежий pending может быть в полёте → Decision: грейс N минут отсекает in-flight; повторный enqueue безопасен (idempotent guard). Без распределённого лока (грейс достаточен).

## Scope
> Reliability-добавка: новая beat-задача (ре-энкьюинг существующего `dispatch_alert`), расширение `/ready`, status-метрика. Логику самой доставки (`notifier`/`backends`, task-009) НЕ меняем.

- **Touch ONLY (создать/изменить):**
  - `backend/src/alerts/tasks.py` (или новый `backend/src/alerts/resweep.py`) — `resweep_pending_alerts()` (тело + Celery-задача): select `pending AND first_seen < now()-grace` (bind-params), для каждого — `dispatch_alert.delay(id)`/re-enqueue; идемпотентно.
  - `backend/src/scheduler.py` — beat-entry `resweep-pending-alerts` (интервал из `Settings`).
  - `backend/src/config.py` — `pending_resweep_grace_seconds`, `pending_resweep_interval_seconds`, `celery_ping_timeout_seconds` (named, дефолты).
  - `backend/src/api/routes/ops.py` — `_check_celery()` (bounded `inspect().ping()` или Redis heartbeat-ключ); включить в `/ready` (worker down → 503).
  - `backend/src/observability/` — alerts-by-status метрика/структурный лог (count по `delivery_status`); вызывается из sweep и/или отдельного тика.
  - `backend/src/alerts/__init__.py` — экспорт новой задачи/константы имени (как `DISPATCH_ALERT_TASK`).
  - `backend/tests/unit/test_resweep*.py` — отбор pending старше grace, не трогает delivered/failed, идемпотентность.
  - `backend/tests/integration/test_*reliability*.py` — симуляция enqueue-failure (pending завис) → sweep ре-энкьюит → доставка; `/ready` 503 при мёртвом worker; метрика доступна.
  - `docs/tasks/tasks-index.md` — на ship (оркестратор).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `frontend/**`, `landing/**`, `alerts/notifier.py`/`alerts/backends.py` доставка (task-009 — только ре-энкьюим, не меняем логику отправки), `/health` liveness (task-001), scorer-логику (task-008/022). Не вводить новое состояние доставки.
- **Blast radius:** новая периодическая задача в beat (доп. нагрузка sweep — лёгкий select по индексу + enqueue); `/ready` теперь зависит от живости worker (может краснеть при деградации worker — желаемое поведение, но влияет на orchestration-probes); метрика — новый observability-сигнал. Доставка по сути не меняется (ре-используем `dispatch_alert`).

## Acceptance Criteria
- [ ] **AC1 — pending ре-доставляется после восстановления (failing-test anchor).** Given alert `pending` старше `grace` (enqueue потерян при падении брокера/worker), When `resweep_pending_alerts` тикает после восстановления, Then `dispatch_alert` ре-энкьюится и alert доставляется (`delivered`); свежий pending (<grace) НЕ трогается. integration пишется ПЕРВЫМ (RED — sweep ещё нет).
- [ ] **AC2 — идемпотентность ре-доставки.** Given alert уже `delivered`/`failed`, When sweep тикает, Then он НЕ ре-энкьюится (sweep берёт только `pending`); повторный enqueue одного pending не шлёт сообщение дважды (`notifier` гардит `DELIVERED`).
- [ ] **AC3 — `/ready` краснеет при мёртвом worker.** Given Celery worker недоступен, When `GET /ready`, Then `503` (как db/redis fail); Given worker жив, Then `200`; проверка bounded (timeout/heartbeat) — probe не вешается дольше лимита.
- [ ] **AC4 — alerts-by-status метрика/лог.** Given alerts разных статусов, When sweep/тик, Then доступен сигнал count по `delivery_status` (метрика или структурный лог) — пригоден для алертинга на рост pending.
- [ ] **AC5 — no magic literals + beat-entry.** Given grace/интервал/ping-timeout, When ревью, Then все из `Settings`/named const; `resweep-pending-alerts` в `beat_schedule` с интервалом из settings.
- [ ] **AC6 — тесты + G2.** Given unit (отбор/идемпотентность) + integration (enqueue-failure→sweep→delivered, `/ready` 503 при мёртвом worker), When прогон + `make up`, Then всё зелёное; `/ready` поведение наблюдаемо за nginx. Артефакты on-failure.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-023-reliability-pending-sweep`.
1. **RED (integration):** alert застрял в `pending` (симуляция потерянного enqueue) → ожидаем, что sweep ре-доставит. Падает (sweep нет). AC1-якорь.
2. `config.py` — `pending_resweep_grace_seconds`/`pending_resweep_interval_seconds`/`celery_ping_timeout_seconds` (AC5).
3. `resweep_pending_alerts` (тело + задача): select `pending AND first_seen < now()-grace` (bind-params), re-enqueue `dispatch_alert`; идемпотентно (только pending). unit зелёные (AC1/AC2 GREEN).
4. `scheduler.py` — beat-entry `resweep-pending-alerts` (интервал из settings) (AC5).
5. `ops.py` `_check_celery()` (bounded ping/heartbeat) → в `/ready` (worker down → 503) (AC3).
6. `observability/` — alerts-by-status метрика/лог; вызвать из sweep (AC4).
7. **G2:** `make up` — симуляция enqueue-failure → sweep доставляет; `/ready` 503 при остановленном worker, 200 при живом (за nginx); integration+unit зелёные (AC6). Обновить `tasks-index.md` на ship.

## Invariants
- **Sweep берёт только pending старше grace** — не трогает `delivered`/`failed`; грейс отсекает in-flight.
- **Идемпотентная ре-доставка** — повторный `dispatch_alert` безопасен (`notifier` early-return на `DELIVERED`); без нового состояния доставки.
- **`/ready` bounded** — Celery-проверка с timeout/heartbeat, как `_check_db`/`_check_redis`; probe не вешается. `/health` остаётся чистой liveness.
- **No magic literals** — grace/интервал/ping-timeout — `Settings`; SQL — bind-params.
- **Доставка (task-009) не меняется** — ре-используем `dispatch_alert`/`notifier`/`backends`, логику отправки не трогаем.
- **failed — терминал** — не ре-свипается (иначе бесконечная ре-доставка мёртвых).

## Edge cases
- Свежий pending в полёте (<grace) → sweep пропускает, нет двойной доставки.
- Worker восстановился, но брокер ещё лагает → re-enqueue ляжет в очередь, доставится при готовности; sweep идемпотентен на следующем тике.
- `inspect().ping()` таймаутит (control-bus занят) при живом worker → bounded timeout + (предпочтительно) heartbeat-ключ как более дешёвый сигнал; не ложный 503 от перегруза control-bus.
- Массовый застой pending (брокер долго лежал) → sweep ре-энкьюит пачкой; ограничить размер выборки/батч, чтобы не залить очередь разом (limit + индекс по `(delivery_status, first_seen)` при необходимости).
- Гонка двух beat-тиков sweep на одном pending → idempotent guard в доставке; повторный enqueue не дублирует сообщение.
- `/ready` 503 при деградации worker может выбить сервис из ротации orchestration → желаемо для readiness, но не должно влиять на `/health` liveness (рестарт-петля).
- Метрика при пустой таблице → нули, не ошибка.

## Test plan
- **unit (sweep):** `test_resweep*.py` — отбор `pending AND first_seen<now()-grace`, не берёт delivered/failed, не берёт свежий pending; re-enqueue зовётся; идемпотентность.
- **integration (reliability):** симуляция потерянного enqueue → alert застрял pending → sweep ре-энкьюит → `delivered` (AC1); повторный sweep не дублирует (AC2); `/ready` 503 при остановленном worker, 200 при живом (AC3); alerts-by-status сигнал доступен (AC4).
- **config/beat:** grace/интервал/timeout из `Settings`; `resweep-pending-alerts` в `beat_schedule` (AC5).
- **runtime/behavioral (G2):** `make up` — enqueue-failure→sweep→delivered; `/ready` за nginx меняет цвет при stop/start worker (AC6).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-023-reliability-pending-sweep"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через nginx/стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по проверенным фактам и learnings task-008 footgun: `alerts/tasks.py` `dispatch_alert` (`DISPATCH_ALERT_TASK`) энкьюится скорером, ретраит transient, на исчерпании → FAILED; при падении брокера/worker задача теряется, строка остаётся `pending` навсегда — нет ре-энкьюинга. `ops.py` `/ready` (task-011) проверяет db+redis bounded, но НЕ Celery worker. `scheduler.py` `beat_schedule` (enqueue-batches/score-tick/purge) — интервалы из `Settings` — добавляем `resweep-pending-alerts`. `notifier.py` гардит `DELIVERED` (idempotent re-delivery). observability/ — место метрики. deps: 008 (scorer-alert seam), 009 (delivery). locate+plan выполнены — executor стартует с «3 do».)
