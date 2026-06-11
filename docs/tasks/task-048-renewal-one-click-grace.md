---
id: TASK-048
title: One-click renewal из письма + grace period 72h + обработка partially_paid
status: review              # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "77d3427"
branch: "task/048-renewal-one-click-grace"
tags: [epic-e4, backend, billing, email, templates, migration]
---

# TASK-048 — Renewal one-click + grace + partially_paid (Epic E4)

> Убираем трение продления ([epic-e4](../product/epics/epic-e4-frictionless-money.md)):
> renewal-письмо (TASK-027) ведёт прямо на ПРЕДСОЗДАННЫЙ NOWPayments-инвойс
> (один клик до оплаты); истечение не обрывает в Free мгновенно — grace 72h;
> `partially_paid` IPN → письмо «доплати разницу» вместо тихого лога.

## Context

**Renewal-цепочка (TASK-027):** beat-task `check_expiring_subscriptions`
(`backend/src/billing/tasks.py:156-168`, ядро `_check_expiring_subscriptions`
`tasks.py:72-148`) сканирует `expires_at` в окнах 7/3/1 дней
(`billing/constants.py:10` `RENEWAL_REMINDER_DAYS`), идемпотентность —
`Subscription.last_reminder_window` (`storage/models/subscriptions.py:70`).
Письмо шлёт `send_renewal_reminder` (`billing/notifications.py:32-87`): сейчас
`renewUrl = settings.frontend_base_url + "/billing"` (`notifications.py:59`,
`constants.py:23`) — юзер должен залогиниться и пройти весь invoice-flow руками.
Шаблон: `templates/templates.json:96-113` (`billing.renewal`, props userName/
planName/daysLeft/renewUrl), рендер `templates/src/templates/billing/renewal.tsx`.

**Инвойс:** `billing/service.py:31-54` `create_invoice` пишет pending
`BillingPayment` + создаёт hosted-инвойс через gateway; `Invoice.payment_url`
(`billing/gateway/base.py:24-32`) живёт только в ответе — **в БД не персистится**
(`storage/models/subscriptions.py:79-107` — колонки payment_url нет). Gateway
строится из settings: `billing/deps.py:21-30` `get_gateway` — Celery-safe (кидает
`BillingNotConfiguredError`, не HTTPException).

**Expiry:** `billing/limits.py:43-59` `effective_plan` — единственная точка
plan-gating (ADR-003): `expires_at <= utcnow()` → Free СРАЗУ (`limits.py:57`).
Потребители: `limits.py:117` (`assert_within_limit`), `scorer/tasks.py:407`
(Free-задержка алертов, TASK-040), `api/api_keys/service.py` (API-доступ) — обрыв
бьёт по всем поверхностям одновременно.

**partially_paid:** статусная машина `billing/webhook.py:107-114` — все
неактивирующие статусы (`partially_paid`/`expired`/intermediate) падают в
`logger.info` и обновляют `payment.status`; юзер о недоплате не узнаёт. `IpnEvent`
(`gateway/base.py:35-43`) несёт только `amount` (= `price_amount` инвойса), поля
`actually_paid` из IPN-тела NOWPayments нет (`nowpayments.py:176-194` `_to_event`).

Миграции: последняя `backend/migrations/versions/0019_field_encryption.py` →
новая = **0020**.

## Goal

После задачи: renewal-письмо содержит ссылку прямо на оплачиваемый NOWPayments-
инвойс текущего плана/периода (предсоздан при отправке, переиспользуется между
окнами 7/3/1); истёкшая подписка сохраняет план ещё 72h (`effective_plan`),
потом Free; `partially_paid` IPN порождает письмо «доплати разницу X» со ссылкой
на ту же платёжную страницу — ровно один раз, активация по последующему finished
работает штатно. DoD = AC.

## Discussion
<!-- durable record. Решения с rationale. -->
- Q: One-click = автосписание/сохранённый метод оплаты? → A: нет → Decision:
  крипта = предоплата, никаких автосписаний (ADR-004). «Один клик» = ссылка в
  письме ведёт сразу на hosted payment-страницу ПРЕДСОЗДАННОГО инвойса — без
  логина и без ручного create-invoice в SPA.
- Q: Когда предсоздавать инвойс? → A: Decision: в момент отправки reminder'а
  (внутри sweep, до `send_renewal_reminder`): find-or-create pending-инвойса
  (user, plan, period). Reuse между окнами 7→3→1 — чтобы не плодить по инвойсу на
  окно; для reuse нужен персистентный `payment_url` → **новая nullable-колонка
  `billing_payments.payment_url` (миграция 0020)**, заполняется в
  `service.create_invoice` из ответа gateway. Та же колонка нужна письму
  «доплати» (см. ниже) — одно изменение схемы закрывает обе фичи.
- Q: Какой период у renewal-инвойса? → A: Decision: период ПОСЛЕДНЕГО
  processed-платежа юзера (продлеваем «как платил»), fallback `MONTH` (подписка
  выдана вручную / платежей нет). С TASK-047 автоматически подхватит quarter/year.
  047 — НЕ блокер: без него последний период всегда month.
- Q: Gateway недоступен/не сконфигурирован при отправке reminder'а? → A: Decision:
  graceful degradation — try/except вокруг предсоздания; при ошибке письмо уходит
  со старым `renewUrl = frontend_base_url + /billing`. Reminder важнее one-click;
  sweep не падает (паттерн best-effort как referral-hook `webhook.py:94-106`).
- Q: Grace — сколько и как «мягко»? → A: epic: «3 дня мягкой деградации» →
  Decision: **72h = `GRACE_PERIOD_SECONDS = 259_200`** named constant в
  `billing/constants.py` (leaf-модуль без import-циклов, урок task-023/027).
  «Мягкая деградация» = план ПОЛНОСТЬЮ сохраняется в grace-окне, после — Free:
  частичная матрица фич = новые фич-флаги по всем поверхностям, не surgical.
  Правка ровно в `effective_plan` (единственная точка, ADR-003) — grace
  автоматически распространяется на лимиты, real-time алерты и API-ключи.
- Q: partially_paid — как не заспамить (NOWPayments ресендит IPN)? → A: Decision:
  письмо шлём только на ПЕРЕХОДЕ статуса (`payment.status != event.status`) —
  повторный partially_paid-IPN уже видит `status == "partially_paid"` и молчит.
  Сумма доплаты = `payment.amount - actually_paid`; для этого `IpnEvent`
  расширяется опциональным `actually_paid: Decimal | None` (frozen dataclass,
  поле с default=None — существующие конструирования в тестах не ломаются).
- Q: Ссылка в письме «доплати» — откуда? → A: Decision: `payment.payment_url` из
  НАШЕЙ БД (записан при создании инвойса через NOWPayments API) — **никогда из
  IPN-тела** (подписанного, но внешнего ввода; URL из IPN = фишинг-вектор).
  Fallback при NULL — `frontend_base_url + /billing`.
- Q: Ошибка отправки письма роняет IPN? → A: нет → Decision: email-hook в
  partially_paid-ветке обёрнут try/except (инвариант webhook'а: ack 200,
  статус сохранён, письмо best-effort).
- Q: Слать ли «у тебя grace, плати» письмо после истечения? → A: вне scope →
  Decision: минимальный diff — sweep шлёт только ДО истечения (`tasks.py:92`
  `expires_at > now` не трогаем); grace-письмо — отдельная задача, если метрики
  E6 покажут потребность.
- Q: Цены/enum? → A: цены остаются константами `plans.py`, `Plan` enum не трогаем
  (инварианты 049) — задача их не касается вовсе.

## Scope
> **backend** (sweep + webhook + effective_plan + модель/миграция) +
> **templates** (новый email `billing/underpaid`). Frontend/landing не трогаем —
> обе ссылки ведут на hosted-страницу NOWPayments.

- **Touch ONLY:**
  - `backend/src/billing/constants.py` — `GRACE_PERIOD_SECONDS = 259_200` (72h,
    epic E4); `_UNDERPAID_TEMPLATE = "billing/underpaid"`, `_UNDERPAID_SUBJECT`
    (leaf-модуль: только stdlib/константы — см. шапку файла).
  - `backend/src/billing/limits.py:57` — `effective_plan`: Free, когда
    `expires_at + timedelta(seconds=GRACE_PERIOD_SECONDS) <= utcnow()` (+docstring
    «AC8 + grace TASK-048»).
  - `backend/src/storage/models/subscriptions.py` — `BillingPayment.payment_url:
    Mapped[str | None]` (`String(_PAYMENT_URL_MAX)`, named width const).
  - `backend/migrations/versions/0020_billing_payment_url.py` — add column
    nullable (downgrade: drop).
  - `backend/src/billing/service.py` — `create_invoice`: записать
    `payment.payment_url = invoice.payment_url` после ответа gateway; новый
    `find_or_create_renewal_invoice(session, *, user, sub, gateway) -> str | None`
    (lookup pending по user+plan+period с payment_url, свежее
    `max(RENEWAL_REMINDER_DAYS)` дней; иначе create).
  - `backend/src/billing/tasks.py` — в цикле sweep: try-предсоздание инвойса
    (gateway из `billing.deps.get_gateway`, `deps.py:21-30`) → `renew_url` в
    `send_renewal_reminder`; except → fallback-URL, warning без PII.
  - `backend/src/billing/notifications.py` — `send_renewal_reminder(*,
    subscription, user, window_days, renew_url: str | None = None)` (None →
    текущий `/billing`); новый `send_underpaid_notice(*, user, payment,
    amount_due: Decimal | None, pay_url: str)`.
  - `backend/src/billing/webhook.py:107-114` — ветка `partially_paid`: переход
    статуса → best-effort email-hook (try/except, паттерн referral
    `webhook.py:94-106`); юзер через `session.get(User, payment.user_id)`.
  - `backend/src/billing/gateway/base.py:35-43` — `IpnEvent.actually_paid:
    Decimal | None = None`.
  - `backend/src/billing/gateway/nowpayments.py:176-194` — `_to_event`: парсить
    `actually_paid` через существующий `_to_decimal` (отсутствует/невалиден → None,
    не ошибка — поле опциональное).
  - `templates/templates.json` — entry `billing.underpaid` (schema: userName,
    planName, amountDue nullable, payUrl + previewDefaults).
  - `templates/src/templates/billing/underpaid.tsx` — по образцу `renewal.tsx`.
  - Тесты (см. Test plan): `backend/tests/unit/test_billing_webhook.py`,
    `test_billing_limits.py`, `test_billing_invoice.py`,
    `test_billing_gateway_dualverify.py` (конструктор IpnEvent не ломается),
    `backend/tests/integration/test_renewal_notifications.py`,
    `test_billing_ipn_route.py`, `test_migrations.py` (0020).
- **Do NOT touch:** цены/`Plan`/`PLAN_LIMITS` (`plans.py`), активирующая ветка
  статусной машины и идемпотентность (`webhook.py:60-106`), dual-verify HMAC
  (TASK-058, `nowpayments.py:105-149`), окна `RENEWAL_REMINDER_DAYS` и механика
  `last_reminder_window` (`tasks.py:104-122`), `frontend/**`, `landing/**`,
  `_bmad/**`, `.claude/**`.
- **Blast radius:** схема БД (+1 nullable колонка `billing_payments`, миграция
  0020 — безопасна, без backfill); `effective_plan` — ВСЕ потребители получают
  grace разом (`limits.py:117` лимиты, `scorer/tasks.py:407` real-time алерты,
  `api/api_keys/service.py` API-доступ) — это и есть цель; beat-task начинает
  ходить во внешний NOWPayments API (timeout 15s, `nowpayments.py:39`; sweep
  последовательный — на текущих объёмах ок, отметить в Details); `IpnEvent`
  DTO расширяется (default → потребители не ломаются); templates-сервис
  деплоится вместе с backend (новый шаблон до первого underpaid-письма).

## Acceptance Criteria

- [x] **AC1 — one-click ссылка.** Given активная pro-подписка истекает через 3 дня
  и NOWPayments сконфигурирован When срабатывает sweep Then письмо `billing/renewal`
  содержит `renewUrl == payment_url` предсозданного pending-инвойса (plan=pro,
  period=последний оплаченный), и строка в `billing_payments` существует с
  заполненным `payment_url`.
- [x] **AC2 — reuse инвойса.** Given инвойс предсоздан в окне 3д When наступает
  окно 1д Then письмо переиспользует ТОТ ЖЕ инвойс (вторая строка не создаётся).
- [x] **AC3 — fallback.** Given gateway не сконфигурирован (или create-invoice
  бросил) When sweep Then письмо уходит с `renewUrl = frontend_base_url + /billing`,
  sweep продолжает остальных юзеров.
- [x] **AC4 — grace.** Given pro истёк 24h назад When `effective_plan` Then PRO
  (свои каналы живы, алерты без задержки, API-ключи работают); Given истёк 73h
  назад Then FREE (лимиты/задержка применяются).
- [x] **AC5 — оплата one-click инвойса.** Given юзер в grace-окне When finished-IPN
  по предсозданному инвойсу Then `activate_or_extend` продлевает от `max(now,
  expires_at)` (`service.py:74-77`), план активен, идемпотентный replay — no-op.
- [x] **AC6 — partially_paid.** Given pending-инвойс на $29 When IPN
  `partially_paid` c `actually_paid=20` Then ack 200, активации НЕТ, юзеру письмо
  `billing/underpaid` с суммой доплаты $9 и ссылкой `payment_url`; When тот же
  IPN повторно Then второе письмо НЕ уходит; When затем `finished` Then план
  активируется штатно (нет `processed_at` в partial-ветке — `webhook.py:107-114`).
- [x] **AC7 — best-effort почта.** Given SMTP/templates падает When partially_paid
  IPN Then всё равно 200, `payment.status == "partially_paid"` сохранён, ошибка
  залогирована без PII.

## Plan

1. Миграция 0020 + `subscriptions.py` (`payment_url`) — RED: `test_migrations.py`
   + unit на персист в `create_invoice` → GREEN (минимальная колонка + запись в
   `service.py`).
2. `limits.py` grace — RED: unit-границы 71h/73h после expiry (+ существующий
   AC8-тест корректируется честно: «expired → Free» становится «expired+grace →
   Free») → GREEN: однострочная правка условия + `GRACE_PERIOD_SECONDS` в
   `constants.py`.
3. `gateway/base.py` + `nowpayments.py` — `actually_paid` (RED: unit `_to_event`
   с/без поля) → GREEN.
4. `service.py::find_or_create_renewal_invoice` + `tasks.py` интеграция +
   `notifications.py` параметр `renew_url` — RED: unit (reuse, fallback,
   period=последний оплаченный) + integration `test_renewal_notifications.py`
   (письмо несёт payment_url) → GREEN.
5. `webhook.py` partially_paid-ветка + `send_underpaid_notice` + шаблон
   `underpaid.tsx`/`templates.json` — RED: unit (переход статуса → 1 письмо;
   replay → 0; finished после partial активирует; email-фейл → ack) → GREEN.
6. Verify (G2): `make ci`; живой прогон: подписка с expiry через 2 дня → beat →
   письмо в mailpit со ссылкой; IPN partially_paid (валидная HMAC-подпись фейком)
   → письмо «доплати»; finished → план активен; expiry в прошлом <72h → API
   отвечает как paid.

## Invariants

- IPN-активация сверяет amount/currency СУЩЕСТВУЮЩЕГО инвойса
  (`webhook.py:125-136`); идемпотентность по `payment.status == processed`
  (`webhook.py:66-72`) — не ослабляются и покрыты регрессионными тестами.
- `partially_paid` НИКОГДА не активирует план и НЕ ставит `processed_at` —
  последующий `finished` обязан активировать.
- Письма и предсоздание инвойсов — best-effort: ни одна ошибка email/gateway не
  валит IPN-ack или renewal-sweep (rollback только своей записи, как
  `tasks.py:135-147`).
- URL для писем берутся ТОЛЬКО из нашей БД/настроек (`payment_url` записан из
  ответа NOWPayments API при создании, `frontend_base_url` из settings) — никогда
  из IPN-тела.
- `effective_plan` остаётся единственной точкой plan-gating (ADR-003) — grace не
  дублируется ни в scorer, ни в api_keys.
- PII не логируется (только subscription_id/user_id/order_id; адрес и payment_url
  в логи не попадают); секреты NOWPayments не логируются (инвариант TASK-058).
- `Plan` enum, цены, окна 7/3/1 — без изменений.

## Edge cases

- У юзера нет ни одного processed-платежа (подписка выдана вручную) → период
  renewal-инвойса = MONTH (fallback).
- Pending-инвойс найден, но `payment_url IS NULL` (создан до 0020) → не
  переиспользуем, создаём новый (NOWPayments-страница старого всё равно неизвестна).
- Pending-инвойс старше `max(RENEWAL_REMINDER_DAYS)` дней → hosted-инвойс мог
  протухнуть на стороне NOWPayments → создаём свежий (lookup ограничен по
  `created_at`).
- Юзер оплатил one-click инвойс ПОСЛЕ окончания grace (уже Free) →
  `activate_or_extend` стартует от `now` (`service.py:74-76`) — деньги не
  пропадают, период полный.
- `actually_paid` отсутствует/не число в IPN → `None` → письмо без точной суммы
  («invoice partially paid — complete the payment»), не ошибка верификации.
- `actually_paid >= amount` при статусе partially_paid (курсовая пыль на стороне
  NOWPayments) → `amount_due <= 0` → сумму в письме не показываем, ссылку даём
  (статусы решает NOWPayments, мы не доактивируем сами).
- Поздний out-of-order `partially_paid` ПОСЛЕ processed → перехватывается
  idempotency-guard'ом раньше ветки (`webhook.py:66-72`) — письма нет.
- Оплата в grace + последующий sweep: `last_reminder_window`-механика уже
  переживает расширение окна (`tasks.py:104-122`, комментарий) — новые reminder'ы
  для нового периода сработают.
- Гонка «sweep создаёт инвойс» × «юзер сам жмёт upgrade в SPA» → два pending —
  безвредно: оплатится один (или оба — оба продлят, ADR-004 §4).

## Test plan

- unit: `test_billing_limits.py` — grace-границы (истёк 1h/71h → план жив; 73h →
  Free; `expires_at IS NULL` → Free как раньше); `test_billing_webhook.py` —
  partially_paid: первый IPN → email-hook вызван 1 раз c amount_due=9, replay →
  0, finished после partial → активация, email-фейл → ack 200;
  `test_billing_invoice.py` — `payment_url` персистится; gateway — `_to_event`
  c/без `actually_paid`; tasks — find-or-create (create/reuse/протухший/fallback
  без gateway), период из последнего платежа.
- integration: `test_renewal_notifications.py` — sweep с фейковым gateway →
  письмо содержит payment_url, вторая отправка reuse'ит инвойс;
  `test_billing_ipn_route.py` — partially_paid → 200 + статус в БД;
  `test_migrations.py` — 0020 up/down.
- templates: рендер `billing/underpaid` (schema-валидация props, preview как у
  `billing.renewal`).
- security (5.5 — ОБЯЗАТЕЛЕН): IPN-input поверхность расширена (`actually_paid`)
  + исходящие письма со ссылками — проверить: URL не из IPN-тела, нет PII/сумм в
  логах, HMAC-цепочка TASK-058 не задета.

## Checkpoints

current_step: 7
baseline_commit: "77d3427"
branch: "task/048-renewal-one-click-grace"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (IPN input + email-ссылки — обязателен)
- [x] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 по epic E4: каждое ручное продление крипты — точка оттока
(learnings task-010). Три рычага одной задачей: ссылка в письме сразу на оплату,
grace 72h вместо обрыва, недоплата не теряется молча. Связь с TASK-047 — мягкая:
period renewal-инвойса = «как платил последний раз», без 047 это всегда month.
Отмечено для ops: sweep теперь ходит в NOWPayments API последовательно с
timeout 15s — при росте базы подписок вынести предсоздание в отдельные
per-user таски.)

(executed 2026-06-11, baseline 77d3427: к моменту do head миграций сдвинулся —
TASK-066 заняла 0020 (`0020_scores_channels_count`), поэтому миграция задачи =
**0021_billing_payment_url** (`down_revision="0021"→"0020"`); все упоминания
«0020» в Context/Scope читать как 0021. Subject underpaid-письма — бренд
«Foresignal» (TASK-072, EN-only); внутри письма layout-компоненты пока несут
старый «TrendPulse» — ребрендинг templates-сервиса вне scope. Доп. правки сверх
Touch ONLY, честные по grace: `tests/unit/alerts/test_delayed_delivery.py`
(«expired вчера» → «expired за пределами grace»); юнит-тесты `_to_event`
actually_paid легли в `tests/unit/test_billing_ipn.py` (родной файл gateway);
invoice-row коммитится сразу после предсоздания (до отправки письма), чтобы
фейл письма не откатывал инвойс — retry следующего тика реюзает его по
payment_url. Sweep при фейле gateway деградирует на /billing и продолжает
остальных (интеграционно покрыто). Verify: 657 unit + 240 integration (pgvector
pg16, host-порт 15435) + mypy strict + ruff + openapi-drift-check (без дрейфа,
API не менялся) + vitest frontend 238 + templates eslint/tsc + живой рендер
`billing/underpaid` (200, amount/null-amount, safeHref режет javascript:).)
