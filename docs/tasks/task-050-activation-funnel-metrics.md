---
id: TASK-050
title: Воронка активации — funnel-события (log_event) + ежедневный Beat-агрегат business_metrics_daily
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "ceba8e4"
branch: "gsd/phase-e6-funnel-metrics"
tags: [epic-e6, backend, observability, metrics]
---

# TASK-050 — Воронка активации: события + дневной агрегат (Epic E6)

> Видеть, на каком шаге теряются люди: регистрация → пак подключён → первый алерт
> доставлен → первая оценка 👍/👎 → первая оплата. Реализация по
> [epic-e6](../product/epics/epic-e6-business-metrics.md): `log_event`-события в 4 точках +
> ежедневный Beat-агрегат в таблицу `business_metrics_daily` (идемпотентный upsert),
> посчитанный из БД (источник истины — таблицы, не логи).

## Context

Техническая observability есть: `observability/logging.py::log_event(event, **fields)`
(JSON-логи, aggregate-only, `_FORBIDDEN_LOG_KEYS` режет сырой контент; task-011/024) — уже
используется (`signal_latency`, `alert_precision`, `pool_health`, `referral.*`). Бизнес-событий
НЕТ: `api/auth/users.py::UserManager.on_after_register` пишет голый `logger.info`;
`api/packs/service.py::subscribe` (TASK-038) и `alerts/notifier.py::deliver` (выставляет
`delivered_at`/`delivery_status`) не эмитят ничего; фидбек 👍/👎 пишется в `alert_feedback`
(TASK-042, `verdict` 1/0).

Данные для агрегата уже в БД: `users.created_at`, `watchlists` (pack-строки имеют
`pack_slug`), `alerts.delivered_at`, `alert_feedback.created_at`,
`subscriptions(plan, expires_at)`, `billing_payments(status="processed", processed_at)`.
Beat-паттерн: `scheduler.py::beat_schedule` — ключ → `{task: <CONST из module/constants.py>,
schedule: float(settings.<interval>)}`; задачи `@celery_app.task(name=CONST)`; немаршрутизи-
рованные идут в default-очередь `celery` (worker потребляет). Последняя миграция — `0017`
(referrals) → следующая `0018`. Урок task-009: новый top-level пакет ОБЯЗАН попасть в
`[tool.mypy] packages`.

## Goal

После задачи: 4 funnel-события эмитятся через `log_event`; ежедневный Beat-таск считает из
БД и upsert'ит строку `business_metrics_daily` за прошедший день (registrations,
packs_attached, first_alerts_delivered, first_feedback, new_paid, churned, active_paid);
повторный прогон идемпотентен; на этих данных TASK-051 строит дашборд. DoD = AC.

## Discussion
<!-- durable record -->
- Q: События или таблица — что источник цифр? → A: оба, разные роли → Decision:
  `log_event` = real-time наблюдаемость (grep/Sentry breadcrumbs), агрегат считается
  ИЗ ТАБЛИЦ БД (логи не персистятся в БД — по ним считать нельзя). Имена событий —
  константы в `observability/constants.py`: `funnel.user_registered`,
  `funnel.pack_attached`, `funnel.alert_delivered`, `funnel.feedback_given`.
- Q: Где считать «первый алерт» / «первая оценка»? → A: в агрегате → Decision: события
  эмитятся на КАЖДОЕ срабатывание (без запроса «а был ли первый» на горячем пути доставки);
  «первый для юзера» определяет агрегатный SQL (`MIN(delivered_at)` per user попадает в day).
- Q: Конверсия/отток — здесь или в 051? → A: счётчики здесь, ratio — на чтении → Decision:
  таблица хранит СЫРЫЕ дневные счётчики (+ `new_paid` = юзеры с первым processed-платежом
  в этот день; `churned` = подписки с `expires_at` в этом дне, не продлённые к моменту
  расчёта; `active_paid` = снапшот активных подписок на конец дня). Проценты и когорты
  считает 051 при отдаче — не дублируем производные.
- Q: Новый пакет или внутрь observability? → A: отдельный → Decision: новый top-level
  `backend/src/analytics/` (`constants.py`, `aggregate.py`, `tasks.py`) — бизнес-метрики
  не смешиваем с тех-observability; СРАЗУ добавить `analytics` в `[tool.mypy] packages`
  (урок task-009) и зарегистрировать модуль тасков в celery include.
- Q: У `watchlists` есть `created_at`? → A: НЕТ (проверено: модель и `UserOwnedBase`
  timestamps не несут) → Decision: добавить `watchlists.created_at` в миграцию 0018
  (`server_default=now()`; существующие строки получат дату миграции — допустимо для
  воронки, зафиксировано здесь).
- Q: Расписание? → A: раз в сутки → Decision: `aggregate-business-metrics` в
  `beat_schedule`, интервал `business_metrics_interval_seconds` (default 86400, named
  constant + settings — no magic literals); таск пересчитывает ВЧЕРАШНИЙ день И сегодняшний
  partial (upsert) — опоздавшие данные догоняются следующим прогоном.

## Scope
> **backend only.** Никакого UI/эндпоинта (это TASK-051). Горячие пути (register, deliver)
> получают по ОДНОЙ строке log_event — никаких новых запросов в них.

- **Touch ONLY:**
  - `backend/migrations/versions/0018_business_metrics_daily.py` — **новая**: таблица
    `business_metrics_daily` (id, `day` DATE UNIQUE, registrations, packs_attached,
    first_alerts_delivered, first_feedback, new_paid, churned, active_paid, computed_at)
    + `watchlists.created_at` (колонки нет — см. Discussion; нужна для шага «пак подключён»).
  - `backend/src/storage/models/business_metrics.py` — **новый**: модель (НЕ UserOwnedBase —
    глобальный агрегат).
  - `backend/src/analytics/` — **новый пакет**: `constants.py` (имя таска
    `AGGREGATE_BUSINESS_METRICS_TASK`, имена funnel-событий — или в
    `observability/constants.py`, решить на do по соседям), `aggregate.py`
    (чистые SQL-агрегаты: функция `compute_day(session, day) -> BusinessMetricsRow`,
    upsert `ON CONFLICT (day) DO UPDATE`), `tasks.py` (`@celery_app.task`).
  - `backend/src/scheduler.py` — beat-entry `aggregate-business-metrics`.
  - `backend/src/config.py` — `business_metrics_interval_seconds` (default-константа 86400).
  - `backend/src/celery_app.py` — include `analytics.tasks`.
  - `pyproject.toml` — `analytics` в `[tool.mypy] packages`.
  - Хуки log_event (по одной строке): `api/auth/users.py::on_after_register`,
    `api/packs/service.py::subscribe` (после успешного flush),
    `alerts/notifier.py::deliver` (после установки `delivered_at`),
    роут фидбека TASK-042 (точный файл — на do: `alerts/`/`api/` feedback-роутер).
  - tests: `backend/tests/unit/analytics/test_aggregate.py` — **новый**;
    `backend/tests/integration/test_business_metrics_daily.py` — **новый**.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** доменную логику register/packs/deliver/feedback (только +1 строка
  эмиссии), `signal_latency`/`alert_precision` (TASK-036/042 — остаются как есть),
  таблицы-источники (кроме возможного `watchlists.created_at`), фронт.
- **Blast radius:** горячий путь доставки алертов (+log_event — O(1), без I/O в БД);
  beat-расписание (новый таск в default-очереди); схема (+1 таблица, аддитивно).

## Acceptance Criteria

- [x] **AC1 — события.** Given регистрация/подписка пака/доставка алерта/первая оценка
  When действие успешно Then в логах JSON-событие с правильным именем и aggregate-only
  полями (user_id, day; БЕЗ контента) — unit с caplog на каждую из 4 точек.
  _Evidence: 572 unit tests pass, caplog-тесты на все 4 события._
- [x] **AC2 — агрегат.** Given в БД: 2 регистрации, 1 пак, 1 доставленный алерт, 1 фидбек,
  1 первый processed-платёж, 1 истёкшая подписка за день D When `compute_day(D)` Then
  строка `business_metrics_daily` с {2,1,1,1,1,1} и корректным `active_paid` (integration,
  реальный Postgres).
  _Evidence: 174 integration tests pass (real pgvector:pg16, AC2 verified)._
- [x] **AC3 — идемпотентность.** Given строка за день D существует When таск выполняется
  повторно Then значения пересчитаны/перезаписаны (upsert), дубликата нет, ошибок нет.
  _Evidence: behavioral check — task body called twice, 1 row, same values._
- [x] **AC4 — «первый» считается верно.** Given юзер с алертами в дни D1<D2 When агрегат
  D2 Then юзер НЕ входит в `first_alerts_delivered` дня D2 (только D1).
  _Evidence: integration test AC4 — MIN-per-user CTE semantics verified._
- [x] **AC5 — G2 (адаптирован).** `make up` → beat реально диспатчит таск → строка
  появляется в таблице; `make ci` зелёный (mypy видит `analytics`: «checked N source files»
  вырос). _Adaptation: в изолированном env beat-таск вызван напрямую (task body), beat-entry
  проверен snapshot-тестом (ключ `aggregate-business-metrics`, schedule=86400.0); mypy: 154
  source files no issues; допустимо, зафиксировано._

## Plan

1. RED: unit на `compute_day` (фикстуры в фейк-сессии/эфемерный PG) + caplog-тесты эмиссии.
2. Миграция 0018 + модель; `make migrate` на чистом томе.
3. `analytics/aggregate.py` — SQL-агрегаты (bind params, `MIN(...) per user` для first-*),
   upsert; `tasks.py` + beat-entry + settings + mypy packages + celery include.
4. Хуки log_event (4 × 1 строка).
5. Integration AC2–AC4 на эфемерном Postgres (рецепт из learnings task-016).
6. Verify G2: полный `-m integration`, beat-диспатч на стеке.

## Invariants

- Горячий путь доставки не получает НИ ОДНОГО нового БД-запроса (только log_event).
- `business_metrics_daily` — единственная новая таблица; пересчёт любого дня в любой
  момент даёт тот же результат из тех же данных (детерминизм).
- log_event не несёт сырой контент/секреты (`_FORBIDDEN_LOG_KEYS` — уже enforced).
- Beat-таск падает «громко» (Sentry, task-024), не глотает исключения.

## Edge cases

- День без активности → строка с нулями (не отсутствие строки — дашборд 051 не должен
  интерполировать дыры).
- Юзер удалился (GDPR CASCADE) → исторические агрегаты НЕ пересчитываются назад задним
  числом (снапшот дня — факт дня); user_id в событиях — число, не email.
- `churned`: подписка истекла в D, продлена в D+1 → в D считалась churned, упрощение
  зафиксировать (точный re-activation-учёт — на чтении в 051 при необходимости).
- Часовой пояс: все границы дня — UTC (`day` = UTC-дата), как `utcnow()` в кодовой базе.
- Двойной beat-тик (рестарт) → upsert идемпотентен по построению.

## Test plan

- unit: `compute_day` математика (включая first-* семантику AC4), нулевой день; caplog
  эмиссии 4 событий.
- integration: миграция применяется; AC2/AC3 на реальном Postgres; beat-entry присутствует
  в `beat_schedule` (snapshot-тест по ключам — паттерн соседних задач).
- e2e: не требуется (нет UI).
- security: не требуется (нет auth/input/secrets; подтвердить на review — события не текут
  контентом).

## Checkpoints

current_step: done
baseline_commit: "ceba8e4"
branch: "gsd/phase-e6-funnel-metrics"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (skip — подтверждено review: нет auth/input/secrets поверхностей)
- [x] 6 ship (PR)
- [x] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E6. Принцип: счётчики — в таблице, производные (конверсия,
когорты) — на чтении в TASK-051; источник истины — таблицы БД, log_event — наблюдаемость.
Зависимости: 042 (feedback), 038 (packs), 010 (payments). Полезен и ДО включения оплат —
воронка регистрация→алерт→оценка работает сразу.)

**do-stage (2026-06-11):** TDD completed. RED: confirmed ModuleNotFoundError for analytics.
GREEN: created backend/src/analytics/ package (constants.py, aggregate.py, tasks.py);
migration 0018 (business_metrics_daily + watchlists.created_at); storage/models/business_metrics.py
(global aggregate, not UserOwnedBase); 4 log_event hooks added (one-liners at: on_after_register,
packs/service.py subscribe after created>0, notifier.py after delivered_at set,
feedback/router.py after feedback upsert). config.py + scheduler.py + celery_app.py + pyproject.toml
updated per Touch ONLY list. Decision: funnel event constants placed in analytics/constants.py
(not observability/constants.py) — business domain separate from tech observability (per Discussion).
Decision: pack_attached event emitted only when created>0 (new rows — not on idempotent re-subscribe).
Decision: rows_created used instead of created in log_event to avoid LogRecord attr collision.
Unit: 7 pass + 543 total unit pass. Integration: 4 pass (AC2, AC3, AC4, beat entry). lint+mypy: clean.

**verify-stage (2026-06-11):** G2 PASS. Static: ruff clean + mypy 154 source files no issues (analytics package included). Unit suite: 572 passed, 184 deselected. Migration 0018 on ephemeral pgvector:pg16 (tp050-verify-pg:15433): business_metrics_daily table + watchlists.created_at confirmed. Integration suite: 174 passed, 10 skipped (Redis/Telegram/email/sentence_transformers — all skip-guarded, expected). Behavioral check (AC5 adapted): seeded user+alert+feedback+payment for yesterday, called aggregate_business_metrics() task body directly twice — row appeared with correct counts (registrations=1, first_alerts_delivered=1, first_feedback=1, new_paid=1), idempotent (1 row, same values on second call). Beat schedule: aggregate-business-metrics key present, schedule=86400.0 (float, 24h). Container tp050-verify-pg cleaned up.

**review-stage (2026-06-11):** PASS (adversarial). Scope clean — every change inside Touch ONLY (storage/models/__init__.py export + tests/unit/test_models.py table-name set are required new-model glue; accepted). Hot-path invariant verified: all 4 log_event hooks are O(1) one-liners adding ZERO DB queries (created/user_id already in scope); fields aggregate-only (user_id/alert_id/pack_slug/rows_created/verdict — none in _FORBIDDEN_LOG_KEYS, no email/content/token). Aggregate SQL: bind params only (no f-string), MIN-per-user CTE first-* semantics correct (AC4 verified by integration), churned/active_paid filter `plan != PLAN_FREE` correct given plan is never reset to free on expiry (only set on payment; effective-free via past expires_at), NULL expires_at correctly excluded, UTC day bounds [start,end), ON CONFLICT (uq_business_metrics_daily_day) upsert idempotent. Migration 0018 additive, chain 0016→0017→0018 correct, downgrade sane, model↔migration match (no drift). Celery/beat: task via AGGREGATE_BUSINESS_METRICS_TASK constant, no-arg JSON-serializable, included in celery_app, interval from settings (named const 86400, no magic literal), failures re-raise via get_session (Sentry, no swallow). mypy packages includes analytics (task-009 gotcha satisfied); no Any/type:ignore. Tests assert correct values (no codified bugs). LOW/accepted: (1) unit test_aggregate compute_day tests patch internal _count_* helpers → tautological for math, but real SQL semantics fully covered by integration AC2/AC3/AC4 — accepted. (2) inline `from ... import` at hook call sites matches existing referral hook convention in users.py — accepted. 5.5 security: SKIP confirmed — no new auth/input/secret surfaces; events carry ids+slug+verdict only, never content.

