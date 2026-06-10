---
id: TASK-049
title: Pricing rework — Free=воронка (паки+задержка), Pro $29, Trader $99 (API), grandfathering
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e5-pricing-rework"
tags: [epic-e5, backend, frontend, landing, billing, pricing]
---

# TASK-049 — Pricing rework: продаём ценность, не каналы (Epic E5)

> Новая сетка ([epic-e5](../product/epics/epic-e5-pricing-packaging.md)): **Free** = паки +
> задержка (механика TASK-040 уже в коде), **Pro $29** = свои каналы + real-time + webhook,
> **Trader $99** (внутр. `Plan.TEAM`) = API-ключи + история 90д. Цены — константы (менять
> дёшево, owner может поднять до $39/$149 одной строкой). Grandfathering действующих
> подписок — автоматический (крипта = предоплата, цена применяется только к новым инвойсам).

## Context

Цена сейчас привязана к числу каналов (затратная логика): `backend/src/billing/plans.py` —
`_PRO_PRICE_USD = Decimal("19")`, `_TEAM_PRICE_USD = Decimal("79")`, `PLAN_PRICES_USD`,
`price_for(plan)` (используется invoice-созданием в `billing/service.py::create_invoice` и
`billing/gateway/nowpayments.py`). Лимиты — `PLAN_LIMITS` по `Resource` (CHANNELS 5/100/500,
TOPICS 1/5/∞, ALERTS_PER_DAY 5/∞/∞, HISTORY 0/30/90, WEBHOOK −/+/+, API −/−/+ (TASK-028),
PACKS 1/5/5 (TASK-038)). Free-задержка уже работает: `config.py::free_alert_delay_seconds`
(1800s) применяется в `scorer/tasks.py::_calculate_deliver_after` (TASK-040).

Витрины цены: frontend `frontend/src/entities/plan/constants.ts` (`PLAN_PRICE_USD`
{free:0, pro:19, team:79}, `PLAN_DISPLAY_NAME`, **`PLAN_MAX_WATCHLISTS` {free:3, pro:25} —
рассинхронизирован с backend CHANNELS {5,100}**, давний дрейф), `features/billing/ui/
plan-comparison.tsx`; landing — полностью config-driven из `landing/public/config.json`
(`pricing.plans`: price/channels/topics/alertsPerDay/historyDays/webhook/apiAccess);
продуктовый источник истины — `docs/product/overview.md` §6 (урок task-017: при расхождении
чинить ОБА конца от overview). Юнит-экономика новой сетки: [`unit-economics.md`](../product/unit-economics.md).

Связь: TASK-030 (error-envelope + /api/v1) — предпосылка ПРОДАЖИ API-тарифа (стабильный
контракт), но не блокер смены цен; поднимается следом.

## Goal

После задачи: `price_for(Plan.PRO) == 29`, `price_for(Plan.TEAM) == 99`; Free не может
создавать СВОИ каналы (CHANNELS=0, паки + задержка = воронка); лендинг/SPA/overview §6
показывают новую сетку с display-именем «Trader» для верхнего тарифа; действующие подписки
доживают оплаченный период без изменений; e2e C1–C5 зелёные. DoD = AC.

## Discussion
<!-- durable record. Решения с owner-валидацией цен; константы — менять дёшево. -->
- Q: Точные цены ($29 vs $39; $99 vs $149)? → A: epic E5 оставляет owner'у → Decision:
  **старт $29 / $99** (нижняя граница вилки — продукт без отзывов, поднять проще после
  первых платящих). Константы `_PRO_PRICE_USD` / `_TEAM_PRICE_USD` — смена = 1 строка + тесты.
- Q: Переименовывать `Plan.TEAM` → `Plan.TRADER` в коде/БД? → A: нет → Decision: enum-значение
  `"team"` НЕ трогаем (нет миграции `users.plan`/`subscriptions.plan`, нет ломки API-контракта);
  «Trader» — только display-слой (`PLAN_DISPLAY_NAME`, landing config, overview-копия).
- Q: Free совсем без своих каналов? → A: да, roadmap зафиксировал «готовые наборы + задержка
  вместо „5 своих каналов real-time"» → Decision: `_FREE_CHANNELS = 0`. Существующие
  Free-юзеры со своими каналами НЕ ломаются: `assert_within_limit` проверяет только
  СОЗДАНИЕ — старые watchlist-строки продолжают работать (естественный grandfathering).
  PACKS Free=1, ALERTS_PER_DAY=5, delay 1800s — без изменений.
- Q: Trader = «мин. задержка + приоритетный скоринг» из epic? → A: фич нет в коде →
  Decision: на витринах обещаем ТОЛЬКО реализованное (API-ключи, real-time, webhook,
  история 90д, 500 каналов). Приоритетный скоринг — E7 (TASK-053), не анонсируем
  (урок task-018: не публиковать ложные раскрытия).
- Q: Grandfathering — нужен код? → A: нет → Decision: крипта = предоплата без автосписаний;
  `price_for` вызывается ТОЛЬКО при создании нового инвойса → активные подписки доживают
  период по факту. Инвариант: активация по IPN сверяет amount СУЩЕСТВУЮЩЕГО инвойса —
  смена констант не рвёт оплату ранее созданных инвойсов (проверить тестом).
- Q: Рассинхрон `PLAN_MAX_WATCHLISTS` (3/25/∞) vs backend CHANNELS (5/100/500)? → A: чинить
  здесь → Decision: выровнять на новые backend-значения {free:0, pro:100, team:500};
  UI-копия «watchlists» → «channels» там, где речь о лимите плана.

## Scope
> **backend** (цены + Free CHANNELS=0) + **frontend** (константы/копия) + **landing**
> (config.json) + **docs** (overview §6). Механику задержки/паков/инвойсов НЕ меняем —
> только значения и витрины.

- **Touch ONLY:**
  - `backend/src/billing/plans.py` — `_PRO_PRICE_USD=29`, `_TEAM_PRICE_USD=99`,
    `_FREE_CHANNELS=0` (+ комментарий «Free = воронка, TASK-049»).
  - `backend/tests/unit/test_billing_invoice.py` — цены 29/99 (включая
    `test_service_pro_price_is_19` → переименовать честно).
  - `backend/tests/unit/test_billing_limits.py` — Free CHANNELS=0: первый же свой канал
    → 402; пак подписывается (PACKS=1 не тронут).
  - `frontend/src/entities/plan/constants.ts` — `PLAN_PRICE_USD` {0,29,99},
    `PLAN_DISPLAY_NAME.team="Trader"`, `PLAN_MAX_WATCHLISTS` → {0,100,500} (или переимен.
    `PLAN_MAX_CHANNELS` — решить на do по числу call-sites, минимальный diff).
  - `frontend/src/features/billing/ui/plan-comparison.tsx` — копия фич по новой сетке
    (Free: «curated packs + delayed alerts», без «5 channels»).
  - `frontend/tests/unit/billing/plan-constants.spec.ts` — новые значения.
  - `frontend/tests/e2e/**` — сценарии, опирающиеся на Free=5 своих каналов (task-015 e2e
    добивал лимит создания) → перевести на Pro-юзера или pack-flow.
  - `landing/public/config.json` — `pricing.plans`: prices 0/29/99, имя Trader,
    Free: channels 0 + копия «curated packs, alerts delayed 30 min», без несуществующих фич.
  - `docs/product/overview.md` §6 — таблица тарифов (новая сетка, Trader).
  - `docs/product/unit-economics.md` — отметить «цены зафиксированы 049».
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** механика `assert_within_limit`/`effective_plan`, `free_alert_delay_seconds`
  и scorer-задержка (TASK-040), PACKS-механика (TASK-038), API-keys auth (TASK-028),
  IPN/webhook (TASK-010), `BillingPeriod` (год/квартал = TASK-047/E4), `_bmad/**`, `.claude/**`.
- **Blast radius:** invoice-суммы (новые инвойсы), лимит создания watchlist для Free
  (single enforcement point `billing/limits.py`), витрины ×3 (SPA/landing/overview).
  Открытые неоплаченные инвойсы со старой ценой: IPN сверяет amount инвойса — активируются
  штатно (тест AC4).

## Acceptance Criteria

- [ ] **AC1 — цены.** Given новая сетка When `price_for(Plan.PRO)`/`price_for(Plan.TEAM)`
  Then `Decimal("29")`/`Decimal("99")`; созданный инвойс несёт новую сумму
  (unit + integration `POST /billing/invoice`).
- [ ] **AC2 — Free = воронка.** Given Free-юзер без watchlist'ов When создаёт СВОЙ канал
  Then 402 `PLAN_LIMIT_EXCEEDED`; When подписывает пак Then 200 и алерты приходят с
  `deliver_after` (существующая механика 038/040, integration).
- [ ] **AC3 — витрины согласованы.** `grep -rn '19' / '79'` по plan-константам frontend/
  landing/overview = 0 старых цен; display «Trader»; `PLAN_MAX_*` == backend CHANNELS;
  unit-тесты констант зелёные.
- [ ] **AC4 — grandfathering.** Given активная подписка plan=team (старая цена) When смена
  констант Then `effective_plan` не меняется до `expires_at`; Given неоплаченный инвойс
  на $19 When приходит его finished-IPN Then активация проходит (amount сверяется с
  инвойсом, не с новой константой).
- [ ] **AC5 — G2.** Полный `-m integration` + frontend unit + e2e C1–C5 зелёные на стеке
  (`make up`); скриншот pricing-страниц лендинга и SPA с новой сеткой.

## Plan

1. `billing/plans.py` — RED: обновить unit-тесты цен/лимитов (29/99, Free CHANNELS=0) →
   падают → минимальная правка констант → GREEN.
2. Integration: тест AC4 (инвойс по старой цене активируется IPN'ом) + AC2 (Free: свой
   канал 402, пак ок).
3. `frontend/src/entities/plan/constants.ts` + `plan-constants.spec.ts` + `plan-comparison.tsx`
   — значения/имя/копия; поправить e2e, опирающиеся на Free=5.
4. `landing/public/config.json` — сетка/копия; визуальная проверка pricing-страниц.
5. `docs/product/overview.md` §6 + `unit-economics.md` — синхронизировать таблицы.
6. Verify (G2): `make ci` + `make up` + e2e + ручной прогон биллинг-страницы.

## Invariants

- Цены живут в ДВУХ местах с одним источником истины (overview §6 ↔ backend `plans.py`;
  frontend/landing — производные) — расхождение чинится от overview (урок task-017).
- `Plan` enum-значения и схема БД не меняются (нет миграции).
- Платёжная сумма для UI — ВСЕГДА из `InvoiceResponse`, не из фронт-констант.
- Существующие данные юзеров не трогаются (никаких retro-удалений watchlist'ов).

## Edge cases

- Free-юзер с 5 «своими» каналами из старой сетки → продолжают собираться и алертить
  (enforcement только на create); создать 6-й нельзя. Осознанно, фиксируем в Details.
- Неоплаченный инвойс на $19 в момент деплоя → оплачивается и активирует план (AC4).
- `PLAN_MAX_WATCHLISTS` потребители: если переименование дороже 3-4 call-sites — оставить
  имя, поменять значения + комментарий (минимальный diff решает do-стадия).
- Лендинг кэширован у клиента (static) → новая цена после деплоя/инвалидации — деплой
  лендинга в том же PR-релизе.

## Test plan

- unit: `test_billing_invoice.py` (цены), `test_billing_limits.py` (CHANNELS=0 → 402,
  PACKS не тронут), frontend `plan-constants.spec.ts`.
- integration: invoice новая сумма; старый инвойс + finished IPN → активация; Free
  pack-flow жив.
- e2e: C1–C5 прогон; биллинг-страница показывает 29/99/Trader; landing pricing рендерится
  из нового config.json.
- security: не требуется (нет auth/input/secrets поверхностей) — суммы серверные, как были.

## Checkpoints

current_step: 3
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e5-pricing-rework"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (skip — нет auth/input/secrets; подтвердить на review)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E5: цены от ценности (скорость/точность/API), Free = воронка.
Старт с нижней границы вилки $29/$99 — поднимать после первых платящих дешевле, чем
отпугнуть нулевым social proof. White-label/разовые отчёты — вычеркнуты (расфокус).)
