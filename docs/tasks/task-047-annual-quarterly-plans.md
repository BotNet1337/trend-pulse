---
id: TASK-047
title: Годовые/квартальные планы со скидкой (BillingPeriod QUARTER/YEAR, деньги вперёд)
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [epic-e4, backend, frontend, landing, billing, pricing]
---

# TASK-047 — Годовые/квартальные планы со скидкой (Epic E4)

> Реже платить = меньше точек ручного продления ([epic-e4](../product/epics/epic-e4-frictionless-money.md)):
> добавить `BillingPeriod.QUARTER` (−10%) и `BillingPeriod.YEAR` (−20%) к инвойсу.
> Цены — явные константы в `plans.py`. Продление существующей подписки на период
> уже работает (`activate_or_extend` period-aware) — расширяем только сетку.

## Context

Период сейчас один: `backend/src/billing/plans.py:24-30` — `BillingPeriod` содержит
только `MONTH`; `PERIOD_DAYS` (`plans.py:46-50`) — `{MONTH: 30}`. Цена — только
месячная: `PLAN_PRICES_USD` (`plans.py:123-126`, Pro $29 / Team $99 после TASK-049),
`price_for(plan)` (`plans.py:132-137`). Вызывающие `price_for`: 
`billing/service.py:40` (`create_invoice` — пишет pending `BillingPayment`) и
`billing/gateway/nowpayments.py:78` (`NowPaymentsGateway.create_invoice` — сумма для
NOWPayments). Оба УЖЕ получают `period` параметром — сигнатуру расширяем без ломки
потоков.

Остальная цепочка уже period-aware (epic просил «проверить» — проверено по коду):

- `billing/service.py:57-59` — `_period_end` берёт длительность из `PERIOD_DAYS[period]`;
  `activate_or_extend` (`service.py:62-87`) продлевает от `max(now, expires_at)` —
  ADR-004 §4, остаток периода не сгорает.
- `storage/models/subscriptions.py:98` — `BillingPayment.period: String(32)` —
  `"quarter"`/`"year"` влезают, **миграция не нужна**.
- `billing/webhook.py:84-86` — активация по IPN восстанавливает
  `BillingPeriod(payment.period)` из инвойса — новые значения проходят автоматически.
- `billing/router.py:31-36` — `InvoiceRequest.period: BillingPeriod = MONTH` —
  Pydantic-enum на границе, новые значения валидируются сами; нужен только regen
  OpenAPI-типов фронта (`frontend/src/shared/api/gen.types.ts`).
- Renewal-sweep (`billing/tasks.py:82-98`, TASK-027) работает от `expires_at`,
  длительность периода ему безразлична.

Витрины: SPA жёстко шлёт месяц — `frontend/src/pages/billing/billing.tsx:37`
(`createInvoiceMutation.mutate({ plan, period: 'month' })`); цены —
`frontend/src/entities/plan/constants.ts:23-27` (`PLAN_PRICE_USD`), карточки —
`frontend/src/features/billing/ui/plan-comparison.tsx:111-117` («$X /month»).
Landing полностью config-driven: `landing/public/config.json` → `pricing.plans[]`
(price/period), рендер `landing/src/pages/pricing.tsx:22-23,66-71`.
Источник истины цен — `docs/product/overview.md` §6 (урок task-017/049).

## Goal

После задачи: `price_for(Plan.PRO, BillingPeriod.YEAR) == Decimal("278")` (и вся
сетка ниже); `POST /billing/invoice {plan, period: "year"}` создаёт инвойс на годовую
сумму; finished-IPN по нему продлевает `expires_at` на 365 дней от
`max(now, текущий expiry)`; SPA даёт выбрать период с показом экономии; landing и
overview §6 показывают годовую цену. DoD = AC.

## Discussion
<!-- durable record. Решения с rationale. -->
- Q: Размер скидок? Epic E4 говорит «скидка 20–30%», промпт-вилка — квартал ~10% /
  год ~20%. → A: epic задаёт вилку БЕЗ разбивки по периодам → Decision: **год −20%**
  (нижняя граница epic-вилки — тот же принцип, что в TASK-049: продукт без отзывов,
  поднять скидку позже дешевле), **квартал −10%** (половина годовой; epic-вилка
  читается как годовая). Числа — явные константы, передоговориться = 1 строка.
- Q: Скидка вычисляется (`price * 12 * 0.8`) или цены — явные константы? → A: цены
  остаются константами (решение зафиксировано) → Decision: явная таблица
  `PLAN_PERIOD_PRICES_USD: dict[Plan, dict[BillingPeriod, Decimal]]`, суммы округлены
  до целого доллара ВНИЗ (в пользу юзера): Pro 29/78/278, Trader 99/267/950
  (квартал: 87→78 ≈ −10.3%, 297→267 ≈ −10.1%; год: 348→278 ≈ −20.1%, 1188→950 ≈ −20.0%).
  Никакой runtime-арифметики скидок — нечему расходиться.
- Q: Автосписание/рекуррент для года? → A: нет → Decision: крипта = предоплата
  (ADR-004), год/квартал — это просто инвойс на бОльшую сумму с бОльшим
  `PERIOD_DAYS`. Никаких новых механик оплаты.
- Q: Сигнатура `price_for`? → A: call-sites всего 2 и оба уже держат `period` в руках
  → Decision: `price_for(plan, period)` — period **обязательный** (явность,
  CONVENTIONS); `ValueError` для Free и для незнакомой пары plan/period.
- Q: Нужна ли миграция под новые значения периода? → A: нет → Decision:
  `BillingPayment.period` — `String(32)` (`subscriptions.py:98`), enum живёт только
  в Python; `Plan` enum и схему БД не трогаем (инвариант 049).
- Q: Длительности? → A: Decision: `_QUARTER_DAYS = 90`, `_YEAR_DAYS = 365` — named
  constants в `PERIOD_DAYS`, без календарной/високосной магии (месяц уже 30 дней
  фикс — консистентно).
- Q: Free=воронка уже есть (TASK-049) — что с витриной Free при периодах? → A:
  Decision: у Free периодов нет (router и так отдаёт 400 на Free-инвойс,
  `router.py:62-63`); тоггл периода влияет только на карточки Pro/Trader.

## Scope
> **backend** (enum+цены+тесты) + **frontend** (тоггл периода + константы) +
> **landing** (config.json + рендер годовой цены) + **docs** (overview §6).
> Механику активации/продления/IPN НЕ меняем — она уже period-aware.

- **Touch ONLY:**
  - `backend/src/billing/plans.py` — `BillingPeriod.QUARTER = "quarter"`,
    `BillingPeriod.YEAR = "year"`; `_QUARTER_DAYS`/`_YEAR_DAYS` + `PERIOD_DAYS`;
    константы `_PRO_QUARTER_PRICE_USD = Decimal("78")` и т.д.;
    `PLAN_PERIOD_PRICES_USD`; `price_for(plan, period)` (docstring: скидки −10/−20,
    TASK-047).
  - `backend/src/billing/service.py:40` — `amount = price_for(plan, period)`.
  - `backend/src/billing/gateway/nowpayments.py:78` — `amount = price_for(plan, period)`.
  - `backend/tests/unit/test_billing_invoice.py` — сетка цен по периодам (включая
    `test_service_pro_price_is_29` → дополнить периодом), `_period_end` 90/365,
    `price_for` raises для Free/незнакомого периода.
  - `backend/tests/unit/test_billing_webhook.py` — finished-IPN по инвойсу
    `period="year"` → `expires_at` +365д; продление активной month-подписки годом
    (остаток сохраняется).
  - `backend/tests/integration/test_billing_ipn_route.py` (или соседний billing-int
    тест) — `POST /billing/invoice {period: "year"}` → amount "278",
    `BillingPayment.period == "year"`.
  - `frontend/src/shared/api/gen.types.ts` — regen OpenAPI-типов (BillingPeriod).
  - `frontend/src/entities/plan/constants.ts` — `PLAN_PERIOD_PRICE_USD`
    {pro: {month:29, quarter:78, year:278}, team: {month:99, quarter:267, year:950}},
    `BILLING_PERIOD_LABEL`; `PLAN_PRICE_USD` остаётся (месячный якорь карточек).
  - `frontend/src/pages/billing/billing.tsx` — state выбранного периода;
    `mutate({ plan, period })` вместо хардкода `'month'` (строка 37).
  - `frontend/src/features/billing/ui/plan-comparison.tsx` — тоггл
    month/quarter/year + цена периода + копия «save ~10%/~20%», «billed every
    3 months / yearly».
  - `frontend/tests/unit/billing/plan-constants.spec.ts` — новые константы;
    юнит на тоггл (сумма в кнопке = константа периода).
  - `landing/public/config.json` — в каждый платный план `pricing.plans[]` добавить
    `quarterlyPrice`/`yearlyPrice` (+ note «save 20% with annual billing»).
  - `landing/src/pages/pricing.tsx` — строка годовой цены под месячной
    (config-driven, отсутствие поля = не рендерим — обратная совместимость).
  - `docs/product/overview.md` §6 — колонки/сноска квартал/год.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `Plan` enum и `PLAN_LIMITS` (`plans.py:16-21,87-115`),
  `billing/limits.py` (gating не зависит от периода), статусная машина IPN
  (`webhook.py`), dual-verify HMAC (TASK-058), миграции/схема БД, renewal-sweep
  `billing/tasks.py` (от периода не зависит; one-click = TASK-048), grace-логика
  (TASK-048), `_bmad/**`, `.claude/**`.
- **Blast radius:** публичный API — enum `BillingPeriod` РАСШИРЯЕТСЯ (старые клиенты
  с `month` работают без изменений, default в `InvoiceRequest` остаётся MONTH);
  суммы новых инвойсов; OpenAPI-типы фронта (regen); landing config-схема
  (опциональные поля). Открытые month-инвойсы продолжают оплачиваться: IPN сверяет
  amount СУЩЕСТВУЮЩЕГО инвойса (`webhook.py:125-136`), не константы.

## Acceptance Criteria

- [ ] **AC1 — сетка цен.** Given таблица периодов When
  `price_for(plan, period)` Then Pro 29/78/278 и Team 99/267/950 (`Decimal`);
  `price_for(Plan.FREE, *)` и незнакомая пара → `ValueError`.
- [ ] **AC2 — инвойс на период.** Given Pro-юзер When
  `POST /billing/invoice {plan:"pro", period:"year"}` Then 200, `amount == "278"`,
  pending `BillingPayment` с `period == "year"`; When `period` опущен Then month
  (default, обратная совместимость).
- [ ] **AC3 — активация/продление.** Given pending year-инвойс When его finished-IPN
  Then `expires_at = now + 365д`; Given активная month-подписка (осталось 10 дней)
  When оплачен year-инвойс Then `expires_at = старый_expiry + 365д` (остаток не
  сгорел, `service.py:74-77`).
- [ ] **AC4 — витрины.** Given SPA billing-страница When тоггл «Yearly» Then карточки
  Pro/Trader показывают 278/950 + «save ~20%», кнопка создаёт инвойс с
  `period:"year"`; landing pricing рендерит годовую цену из config.json;
  overview §6 синхронизирован.
- [ ] **AC5 — G2.** `make ci` зелёный (unit+integration), frontend unit + tsc/eslint,
  landing build; живой прогон: создать year-инвойс через API, finished-IPN (фейк
  подписью) → `expires_at` +365.

## Plan

1. `backend/src/billing/plans.py` — RED: unit-тесты сетки `PLAN_PERIOD_PRICES_USD`,
   `PERIOD_DAYS` (90/365) и ошибок `price_for` → падают → минимальная правка
   (enum-значения, константы, таблица, сигнатура) → GREEN.
2. `billing/service.py:40` + `gateway/nowpayments.py:78` — передать `period` в
   `price_for`; юнит `test_service_create_invoice_persists_pending_and_delegates`
   дополнить периодом.
3. Integration: invoice year (AC2) + finished-IPN year-продление (AC3) — поверх
   существующих фикстур `test_billing_ipn_route.py`.
4. Frontend: regen `gen.types.ts` → `entities/plan/constants.ts`
   (`PLAN_PERIOD_PRICE_USD`) → `plan-comparison.tsx` (тоггл) →
   `billing.tsx` (state + mutate) → unit-тесты.
5. `landing/public/config.json` + `landing/src/pages/pricing.tsx` — годовая цена
   (опциональные поля, graceful при отсутствии).
6. `docs/product/overview.md` §6 — сетка периодов.
7. Verify (G2): `make ci`; ручной сценарий AC5.

## Invariants

- IPN-активация сверяет amount/currency СУЩЕСТВУЮЩЕГО инвойса
  (`webhook.py:125-136`) — добавление периодов не влияет на оплату ранее созданных
  инвойсов; идемпотентность по `payment.status == processed` (`webhook.py:66-72`)
  не ослабляется.
- `Plan` enum, `PLAN_LIMITS` и схема БД не меняются (нет миграции).
- Цены — константы в `plans.py`; никакой runtime-арифметики скидок; платёжная сумма
  для UI — ВСЕГДА из `InvoiceResponse` (инвариант 049).
- Лимиты/гейтинг (`limits.py`) НЕ зависят от периода — только от плана.
- Источник истины цен: overview §6 ↔ `plans.py`; frontend/landing — производные
  (урок task-017).

## Edge cases

- `period` отсутствует в body → default `MONTH` (`router.py:36`) — старые клиенты
  и e2e живут без правок.
- Free + любой период → 400 «the free plan has no invoice» как сейчас
  (`router.py:62-63`) — тест не меняется.
- Открытый pending month-инвойс + юзер тут же создал year-инвойс → два pending;
  каждый активирует свой период при оплате, `activate_or_extend` суммирует от
  `max(now, expiry)` — двойная оплата не теряется.
- Неизвестная строка периода в старой `BillingPayment.period` при активации →
  невозможна (пишем только из enum), но `BillingPeriod(payment.period)` упадёт
  `ValueError` → IPN 400, инвойс не потерян — поведение как сейчас.
- Landing закэширован у клиента → годовая цена после деплоя лендинга в том же
  PR-релизе (как 049).

## Test plan

- unit: `test_billing_invoice.py` — сетка цен (6 значений), `ValueError`-ветки,
  `_period_end` 90/365, делегирование `period` в gateway; frontend
  `plan-constants.spec.ts` + тоггл периода.
- integration: `POST /billing/invoice period=year` → 278 + строка в
  `billing_payments`; finished-IPN year → +365д; продление активной month-подписки
  годом.
- e2e: существующие C1–C5 не трогаем (default month); опц. — клик «Yearly» на
  billing-странице показывает 278 (smoke).
- security: не требуется (нет новых auth/input-поверхностей: enum валидируется
  Pydantic, суммы серверные) — подтвердить на review.

## Checkpoints

current_step: 3
baseline_commit: "c390c4c"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E4 «деньги без трения»: реже платить = меньше ручных
продлений. Проверено по коду: вся цепочка invoice → IPN → activate_or_extend уже
period-aware, задача сводится к расширению enum + явной таблице цен + витринам.
Скидки: год −20% (нижняя граница epic-вилки 20–30%), квартал −10%.)
