---
id: TASK-050
title: Воронка активации — funnel-события (log_event) + ежедневный Beat-агрегат business_metrics_daily
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
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

- [ ] **AC1 — события.** Given регистрация/подписка пака/доставка алерта/первая оценка
  When действие успешно Then в логах JSON-событие с правильным именем и aggregate-only
  полями (user_id, day; БЕЗ контента) — unit с caplog на каждую из 4 точек.
- [ ] **AC2 — агрегат.** Given в БД: 2 регистрации, 1 пак, 1 доставленный алерт, 1 фидбек,
  1 первый processed-платёж, 1 истёкшая подписка за день D When `compute_day(D)` Then
  строка `business_metrics_daily` с {2,1,1,1,1,1} и корректным `active_paid` (integration,
  реальный Postgres).
- [ ] **AC3 — идемпотентность.** Given строка за день D существует When таск выполняется
  повторно Then значения пересчитаны/перезаписаны (upsert), дубликата нет, ошибок нет.
- [ ] **AC4 — «первый» считается верно.** Given юзер с алертами в дни D1<D2 When агрегат
  D2 Then юзер НЕ входит в `first_alerts_delivered` дня D2 (только D1).
- [ ] **AC5 — G2.** `make up` → beat реально диспатчит таск (форсировать через
  `celery call` или короткий интервал) → строка появляется в таблице; `make ci` зелёный
  (mypy видит `analytics`: «checked N source files» вырос).

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

current_step: 3
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e6-funnel-metrics"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (skip — нет новых поверхностей; подтвердить на review)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E6. Принцип: счётчики — в таблице, производные (конверсия,
когорты) — на чтении в TASK-051; источник истины — таблицы БД, log_event — наблюдаемость.
Зависимости: 042 (feedback), 038 (packs), 010 (payments). Полезен и ДО включения оплат —
воронка регистрация→алерт→оценка работает сразу.)
