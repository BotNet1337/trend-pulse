---
id: TASK-051
title: Дашборд «деньги» — GET /ops/business-metrics (superuser): MRR, подписки, чек, воронка, retention
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e6-money-dashboard"
tags: [epic-e6, backend, metrics, ops]
---

# TASK-051 — Дашборд «деньги»: один JSON-экран (Epic E6)

> Сколько зарабатываем и где теряем — одним запросом. По
> [epic-e6](../product/epics/epic-e6-business-metrics.md): MRR, активные подписки по планам,
> средний чек, конверсия/воронка (из `business_metrics_daily`, TASK-050), repeat-payment
> retention — отдаётся ops-эндпоинтом `GET /ops/business-metrics` под `is_superuser`.
> Grafana/страница — НЕ сейчас (G1-срез: JSON достаточно для решений одного владельца).

## Context

Источники уже в БД: `subscriptions(plan, expires_at)` (активна ⇔ `expires_at > now`),
`billing_payments(order_id, plan, period, amount NUMERIC, currency, status, processed_at)`
— `amount` записывается в USD из `price_for(plan)` при создании инвойса
(`billing/service.py::create_invoice`), т.е. средний чек считается без конвертаций.
Дневная воронка — `business_metrics_daily` (TASK-050). Задержка сигнала p50/p95 — отдельный
канал (`log_event("signal_latency")`, TASK-036) — в JSON НЕ дублируем (источник — логи).

Ops-эндпоинты сейчас без auth (`/health`, `/ready` в `api/routes/ops.py` — probes).
Бизнес-цифры наружу отдавать нельзя: fastapi-users даёт готовый гейт
`current_superuser` (`users.is_superuser` уже в схеме из `SQLAlchemyBaseUserTable`).
Операторских Makefile-таргетов паттерн: `showcase-init`, `referral-paid ID=…`,
`case-mainstream ID=… AT=…` (корневой `Makefile`).

## Goal

После задачи: владелец (superuser) получает одним GET'ом JSON: `mrr`,
`active_subscriptions_by_plan`, `arpu`, `avg_check_30d`, `funnel_last_30d` (из
business_metrics_daily, с конверсией Free→Paid), `repeat_payment_rate`; не-superuser — 403,
аноним — 401; есть операторский путь назначить себе superuser (`make superuser-grant`).
DoD = AC.

## Discussion
<!-- durable record -->
- Q: Эндпоинт, страница или Grafana? → A: epic оставлял выбор → Decision: **только
  JSON-эндпоинт** — один владелец, решения принимаются по числам, не по графикам;
  страница/Grafana = отдельная задача когда появится второй потребитель. Минимальный diff.
- Q: Чем гейтить? → A: `is_superuser` → Decision: `current_superuser =
  fastapi_users.current_user(active=True, superuser=True)` — поле в схеме есть, но
  зависимость в кодовой базе НЕ заведена (есть только `current_user` в
  `api/auth/backend.py`) → завести рядом и использовать. НЕ изобретать api-key/ops-токен.
  Выдача прав — операторский таргет `make superuser-grant EMAIL=…` (UPDATE через
  `docker exec` psql/python — по образцу `referral-paid`).
- Q: MRR как считать (крипта, предоплата)? → A: по активным подпискам → Decision:
  `MRR = Σ PLAN_PRICES_USD[plan]` по подпискам с `expires_at > now()`. Когда появится
  год/квартал (TASK-047/E4) — амортизация по `billing_payments.period` (/3, /12);
  заложить helper `monthly_value(plan, period)` сразу (period уже хранится), чтобы 047
  не переписывал эндпоинт.
- Q: Retention-когорты — полноценные? → A: нет, рано → Decision: `repeat_payment_rate` =
  доля юзеров с ≥2 processed-платежами среди юзеров с первым платежом старше 35 дней.
  Полные когорты — после реальных данных (нечего когортить на нуле платежей).
- Q: Конверсия Free→Paid? → A: на чтении → Decision: из `business_metrics_daily`:
  `Σ new_paid / Σ registrations` за окно 30д (+ дневной ряд для тренда). Не дублируем
  хранение (инвариант TASK-050: производные — на чтении).
- Q: Кэшировать? → A: нет → Decision: запросы — простые агрегаты по малым таблицам;
  один потребитель. Кэш = преждевременная сложность.

## Scope
> **backend only**, читающий слой. Никаких новых таблиц/миграций; никакого фронта.

- **Touch ONLY:**
  - `backend/src/analytics/money.py` — **новый**: чистые read-функции
    (`compute_mrr(session)`, `active_by_plan(session)`, `avg_check(session, days)`,
    `repeat_payment_rate(session)`, `funnel_window(session, days)`), helper
    `monthly_value(plan, period)`; окна — named constants (`_DEFAULT_WINDOW_DAYS = 30`).
  - `backend/src/api/auth/backend.py` — экспорт `current_superuser`
    (`fastapi_users.current_user(active=True, superuser=True)`, рядом с `current_user`).
  - `backend/src/api/routes/ops_business.py` — **новый**: `GET /ops/business-metrics`,
    `Depends(current_superuser)`, Pydantic response-модель `BusinessMetricsResponse`
    (`extra="forbid"`, только агрегаты — никаких email/user_id в ответе).
  - `backend/src/api/main.py` — include нового роутера.
  - `Makefile` — `superuser-grant EMAIL=…` (по образцу `referral-paid`).
  - tests: `backend/tests/unit/analytics/test_money.py` — **новый**;
    `backend/tests/integration/test_ops_business_metrics.py` — **новый** (auth-матрица +
    числа на сидированных данных).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `/health`, `/ready` (probes остаются без auth), `business_metrics_daily`
  схему (читаем как есть), billing-логику, `signal_latency` (логи — его канал), фронт.
- **Blast radius:** новый read-only роут (один); `analytics`-пакет (создан в TASK-050 —
  если 051 пойдёт первой, пакет+mypy-регистрация переезжают сюда); Makefile (+1 таргет).

## Acceptance Criteria

- [ ] **AC1 — числа верные.** Given сидировано: 2 активные подписки pro + 1 team (по новым
  ценам 049), 3 processed-платежа (29/29/99), 1 юзер с двумя платежами When GET Then
  `mrr == 157`, `active_subscriptions_by_plan == {pro: 2, team: 1}`, `avg_check_30d ≈ 52.33`,
  `repeat_payment_rate` посчитан (integration, эфемерный Postgres).
- [ ] **AC2 — auth-матрица.** Given аноним When GET Then 401; Given обычный юзер Then 403;
  Given superuser Then 200 (и ответ не содержит ни одного per-user идентификатора —
  `extra="forbid"` + явный тест полей).
- [ ] **AC3 — воронка из 050.** Given строки business_metrics_daily за 3 дня When GET Then
  `funnel_last_30d` несёт дневной ряд + суммарную конверсию; день-дыра отдаётся нулями
  (контракт TASK-050).
- [ ] **AC4 — superuser-grant.** `make superuser-grant EMAIL=x` идемпотентно ставит флаг;
  несуществующий email → понятная ошибка, не stack-trace.
- [ ] **AC5 — G2.** На живом стеке (`make up`): grant → curl с cookie superuser'а → JSON
  с реальными числами; полный `-m integration` зелёный.

## Plan

1. RED: unit `test_money.py` на каждую функцию (включая `monthly_value` период-aware) →
   `analytics/money.py` минимальная реализация → GREEN.
2. Роут + response-модель + include; integration auth-матрица (AC2) и числа (AC1, AC3).
3. `Makefile::superuser-grant` (+ негативная ветка).
4. Verify G2 на стеке; review; security 5.5 (новый auth-gated роут — ОБЯЗАТЕЛЬНО:
   superuser-гейт, отсутствие утечки PII, ошибки стерильны).

## Invariants

- `/ops/business-metrics` никогда не отдаёт per-user данные — только агрегаты.
- Производные метрики НЕ персистятся (single source: subscriptions/billing_payments/
  business_metrics_daily).
- probes `/health`, `/ready` не меняются (внешний мониторинг TASK-060 зависит от них).
- Эндпоинт read-only: ни одной записи в БД на GET.

## Edge cases

- Ноль данных (свежий прод) → 200 с нулями, не 500/деление на ноль (guard'ы в money.py).
- Подписка с `expires_at == NULL` (никогда не платил, строка-заглушка) → НЕ активна для MRR.
- `repeat_payment_rate` при отсутствии «созревших» юзеров (моложе 35д) → `null`
  (нет данных ≠ 0%).
- Незнакомый `plan` в подписке (legacy/будущий) → пропустить с log_event-warning, не упасть.
- Платёж со статусом pending/expired → не входит в avg_check (только processed).

## Test plan

- unit: money.py функции (нули, NULL expires_at, незнакомый план, monthly_value).
- integration: auth-матрица 401/403/200; сидированные числа AC1/AC3; superuser-grant.
- e2e: не требуется (нет UI).
- security (5.5): ОБЯЗАТЕЛЬНО — новый привилегированный роут: гейт, PII-отсутствие,
  стерильные ошибки, rate-limit наследуется глобальный (120/min достаточно для ops).

## Checkpoints

current_step: 3
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e6-money-dashboard"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED — привилегированный роут, PII, error-гигиена)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E6. G1-срез: JSON-эндпоинт вместо страницы/Grafana — один
потребитель-владелец; UI = отдельная задача при необходимости. Зависимости: 050 (воронка),
010 (payments), 049 (цены — числа в AC взяты по новой сетке). Задержка p50/p95 остаётся
в логах (TASK-036) — не дублируется в JSON.)
