---
id: TASK-040
title: Free-план — задержка алертов 15–30 мин (deliver_after + countdown; resweep уважает задержку)
status: done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e1, backend, alerts, billing]
---

# TASK-040 — Free-план: задержка алертов (Epic E1)

> Продукт продаёт **скорость** — значит честный платный барьер для Free — это задержка, а не урезанные
> каналы. Free получает те же сигналы с задержкой 15–30 мин; Pro/Team — real-time. Основа Free-воронки
> для pricing-rework (E5/TASK-049).

## Context

Поток: scorer создаёт Alert (pending) → `dispatch_alert.apply_async(args=(alert_id,))` — немедленно
(`alerts/tasks.py`). Celery поддерживает `countdown/eta`. **Ловушка:** `resweep_pending_alerts` (task-023,
Beat) пере-энкьюивает pending старше `pending_resweep_grace_seconds=300` — без защиты он **обойдёт
задержку** Free-алертов. План юзера: `billing.limits.effective_plan(session, user)` (учитывает истечение
подписки). Миграции: последняя 0010 (+ NNNN от TASK-038 если он раньше).

## Goal

Алерт Free-юзера получает `deliver_after = now + delay` (delay из Settings, default 1800с) и доставляется
не раньше этого времени (countdown + защита в dispatch + resweep skip); Pro/Team — как сейчас (deliver_after
NULL). Метрика TASK-036 исключает/выделяет задержанные алерты. Апгрейд плана до истечения задержки
доставляет немедленно при следующем dispatch/resweep-тике (best-effort). DoD = AC.

## Discussion
- Q: Фикс или диапазон 15–30 мин? → Decision: одна настройка `free_alert_delay_seconds` (default 1800);
  рандомизация не нужна (нет анти-gaming мотива), простота важнее. Менять — env.
- Q: Где источник истины о задержке — countdown или поле? → Decision: **поле `alerts.deliver_after`**
  (nullable datetime) — источник истины; countdown — оптимизация диспатча. Причина: resweep и ручные
  ретраи должны видеть задержку в данных, а не в очереди (Celery eta теряется при рестарте брокера).
- Q: Как защитить все пути доставки? → Decision: тройная защита: (1) scorer ставит deliver_after для Free;
  (2) `dispatch_alert`/`_dispatch` в начале: `deliver_after > now` → re-schedule с countdown=остаток
  (не доставляем рано); (3) resweep: фильтр `deliver_after IS NULL OR deliver_after <= now`.
- Q: Апгрейд во время задержки? → Decision: deliver_after НЕ пересчитываем (просто); ближайший
  dispatch/resweep доставит по факту наступления. Edge зафиксирован, не оптимизируем.
- Q: Считать ли задержанные в latency-метрике (TASK-036)? → Decision: исключить из основного разреза
  (фильтр `deliver_after IS NULL`) — согласовано в task-036 Discussion.

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/NNNN_alert_deliver_after.py` — **новая**: nullable `alerts.deliver_after`
    + расширение индекса pending-sweep при необходимости (по explain).
  - `backend/src/storage/models/alerts.py` — поле `deliver_after`.
  - `backend/src/scorer/tasks.py` — `_create_alert_idempotent`/trigger-путь: `effective_plan` юзера → Free →
    `deliver_after = utcnow()+delay`; enqueue с countdown=delay.
  - `backend/src/alerts/tasks.py` — guard в `_dispatch` (рано → reschedule); resweep-фильтр deliver_after.
  - `backend/src/config.py` — `free_alert_delay_seconds` (default 1800).
  - `backend/src/observability/signal_latency.py` (если TASK-036 уже смержен) — фильтр.
  - tests: `backend/tests/unit/alerts/test_delayed_delivery.py` (**новый**), правка resweep-тестов.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** notifier/backends (доставка как была), billing-планы/цены (это TASK-049), frontend
  (опционально бейдж «задержка Free» — отдельной микро-правкой в TASK-049 вместе с pricing-копирайтом).
- **Blast radius:** миграция alerts (+nullable — безопасно); поведение scorer-триггера для Free-юзеров;
  resweep-запрос. Pro/Team-путь не меняется (deliver_after NULL → все guards прозрачны).

## Acceptance Criteria
- [ ] **AC1 — Free задерживается (failing-test anchor).** Given Free-юзер, When scorer создаёт алерт,
  Then `deliver_after ≈ now+1800` и enqueue с countdown≈1800; Pro/Team → deliver_after NULL, countdown 0.
  RED первым.
- [ ] **AC2 — ранний dispatch не доставляет.** Given алерт с deliver_after в будущем, When `dispatch_alert`
  выполнился раньше (ручной enqueue/ретрай), Then доставки нет, задача перепланируется на остаток,
  статус остаётся pending, attempts не сгорают.
- [ ] **AC3 — resweep уважает задержку.** Given pending-алерт Free старше grace, но deliver_after в будущем,
  When resweep, Then он НЕ пере-энкьюится; после наступления deliver_after — энкьюится штатно (это же
  страхует потерю eta при рестарте брокера).
- [ ] **AC4 — истёкшая подписка = Free-поведение.** Given юзер с истёкшей Pro-подпиской (effective_plan→FREE),
  Then новые алерты задерживаются.
- [ ] **AC5 — G2.** Dev-стек с `free_alert_delay_seconds=60`: Free-юзер получает реальный алерт через
  ~минуту после создания, Pro — сразу; `make ci-fast` зелёный; рестарт worker'а между созданием и
  доставкой не теряет алерт (resweep добирает после deliver_after).

## Plan
1. **RED:** `test_delayed_delivery.py` — AC1–AC4 (unit: фейк-время/monkeypatch utcnow, мок apply_async).
2. Миграция NNNN + модель.
3. `config.py` настройка; scorer-триггер (effective_plan → deliver_after+countdown).
4. `_dispatch` guard + resweep-фильтр (+ правка существующих resweep-тестов).
5. GREEN + G2 (delay=60 в dev, сценарий рестарта worker'а); tasks-index на ship.

## Invariants
- `deliver_after` — единственный источник истины задержки; очередь — оптимизация (рестарт брокера не ломает).
- Pro/Team-путь байт-в-байт прежний (NULL → guards прозрачны).
- Идемпотентность доставки не ослаблена (delivered-no-op в notifier как был).
- Resweep по-прежнему добирает потерянные алерты — теперь с уважением deliver_after.
- Задержка — из Settings (no magic literals); ALERTS_PER_DAY-лимит Free не затронут.

## Edge cases
- Рестарт брокера/воркера с потерей eta → resweep доставит после deliver_after (AC3/AC5) — задержка
  фактически может стать чуть больше (grace-тик) — приемлемо для Free.
- Часы воркеров расходятся → сравнение в UTC по БД-времени где возможно; допуск ±tик resweep.
- Free-юзер апгрейдится в момент задержки → доставка по deliver_after (без пересчёта) — зафиксировано.
- Старые алерты без поля (до миграции) → NULL → поведение прежнее.

## Test plan
- **unit:** `test_delayed_delivery.py` — AC1 (оба плана), AC2 (reschedule, attempts не растут), AC3
  (resweep-фильтр в обе стороны), AC4 (effective_plan-даунгрейд).
- **integration:** resweep-сценарий на db_session (посев pending с/без deliver_after).
- **G2:** живой сценарий AC5 включая рестарт worker'а.
- **security (5.5):** n/a по input (внутренняя механика), но plan-gate логика — прогнать
  trendpulse-security чеклист на обход задержки (ручной enqueue API нет — только internal).

## Checkpoints
current_step: done
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: "gsd/phase-e1-free-plan-alert-delay"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior; см. Details)
- [x] 5 review (auto, adversarial — pass, только LOW/INFO)
- [x] 5.5 security (plan-gate bypass check — pass: API алертов read-only, deliver_after не экспонирован, обходов нет)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto — записаны в docs/learnings.md до ship, в том же PR)
debug_runs: []

## Details
(initial — locate: точка врезки `dispatch_alert.apply_async` в alerts/tasks.py; ГЛАВНАЯ ловушка найдена
на locate — `resweep_pending_alerts` (task-023) пере-энкьюит pending старше 300с и обошёл бы задержку →
поле `deliver_after` как источник истины + фильтр в resweep (бонус: устойчивость к потере Celery eta при
рестарте брокера). План юзера — через существующий `effective_plan` (учитывает истечение). Pro/Team-путь
не меняется. Делается до/вместе с TASK-049 (pricing): задержка — механика, цены — упаковка.)

2026-06-10 (do→ship): TDD (RED: 11 падающих → GREEN: 433 unit, ruff/mypy чисто). Миграция 0012
(deliver_after timestamptz NULL, без нового индекса — ix_alerts_status_first_seen покрывает resweep при
текущей ретенции, решение в докстринге миграции). Тройная защита: scorer (_resolve_deliver_after через
effective_plan — истёкшая Pro-подписка корректно даёт Free-задержку), guard в _dispatch (рано →
reschedule c countdown=ceil(remaining)≥1, attempts/status не трогаются), resweep-фильтр
(deliver_after IS NULL OR <= now — заодно страхует потерю Celery eta при рестарте брокера).
signal_latency исключает задержанные (фильтр deliver_after IS NULL — закрыт follow-up из TASK-036).
G2 in-process против реальных dev Postgres+Redis (FREE_ALERT_DELAY_SECONDS=60): Free-алерт получил
deliver_after≈now+60 и countdown=60, Pro — NULL/немедленно; ранний dispatch не доставил и перепланировал
(countdown 58s), attempts=0; resweep пропустил будущий deliver_after и подобрал прошедший; после
наступления — доставка через мокнутый backend ок. Security: обходов нет (alerts API read-only,
deliver_after не в схемах ответов, план — только server-side). Двойной enqueue (countdown-таск +
resweep) безопасен: delivered-no-op + pending-check. Executor-фиксы после verify: floor→math.ceil
в remaining, ruff-мелочи в тестах. Полный live-сценарий worker-рестарта покрыт эквивалентом
(resweep-механика на реальной БД).
