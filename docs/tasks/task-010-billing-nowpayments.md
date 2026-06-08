---
id: TASK-010
title: Billing — crypto via NOWPayments (Free/Pro/Team) + enforcement лимитов плана
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: ""    # set by executor at ship time
branch: ""             # set by executor at ship time
tags: [backend, billing, crypto, nowpayments, limits, ipn, security]
---

# TASK-010 — Billing (crypto · NOWPayments · Free/Pro/Team · enforcement лимитов)

> Подключить крипто-биллинг для TrendPulse через **NOWPayments**: создание invoice под план/период (Pro/Team, месяц), приём и **верификация IPN-webhook** (HMAC-подпись) для активации/продления плана пользователя по статусу платежа, и единая точка enforcement лимитов плана (`billing/limits.py`), которой пользуются watchlist (task-004) и прочие поверхности. Период подписки считаем сами (у крипто-шлюзов нет нативных подписок): продление через renewal-invoice до истечения, истёкший план → откат на Free + применение лимитов. Провайдер — за абстракцией (`PaymentGateway` Protocol), сменяем на CoinGate без изменения ядра. Лимиты — по таблице overview §6. См. [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md).

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md), [`../architecture/high-level-architecture.md`](../architecture/high-level-architecture.md)) — multi-tenant SaaS. [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md) фиксирует крипто-оплату напрямую (overview §6: Solana USDC/SOL, Ethereum USDC/ETH, TON USDT/TON) через **NOWPayments** — **никакого Stripe**. Архитектура требует, чтобы лимиты тарифа (каналы/топики/алерты/история/webhook/API) проверялись **в одном месте** (`billing/limits`), а не размазывались по роутам (ADR-003). Это backend-модуль `billing/` из карты модулей high-level §3.

Задача идёт после **task-003** (auth — `current_user`, JWT, тенант-скоуп по `user_id`) и **task-004** (watchlist CRUD — первый потребитель лимитов: cap на каналы/топики). Опирается на data model task-002 (таблица `users` + `subscriptions` с `plan`/`expires_at`) и на pydantic-settings из task-001 (`config.py`).

Выбор сети/токена (Solana/Ethereum/TON) — на стороне NOWPayments; мы лишь создаём invoice под план/период и реагируем на IPN. Приватных ключей кошельков в приложении нет — средства идут на payout-адрес через NOWPayments (ADR-004 §3); приложение хранит только `NOWPAYMENTS_API_KEY` + `NOWPAYMENTS_IPN_SECRET` из `sensitive.env` ([ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md) §4). IPN-эндпоинт доступен только за nginx (network-design).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md).

## Goal

В backend появляется самодостаточный модуль `billing/`: пользователь может создать NOWPayments invoice под план Pro/Team и период (месяц) и получить payment/redirect (адрес/ссылку оплаты); входящий **IPN-webhook** с **валидной HMAC-подписью** (`x-nowpayments-sig`, ключ — IPN secret) и статусом `finished`/`confirmed` активирует/продлевает план пользователя (`subscriptions.expires_at`), а IPN с невалидной подписью — отвергается (4xx) без доверия телу; повторная доставка того же `payment_id` идемпотентна (без двойного продления); `partially_paid`/`expired` — без активации; истёкший план откатывается на Free. Любая поверхность (watchlist task-004 и др.) перед созданием ресурса вызывает единый `assert_within_limit(user, resource)`, который при превышении лимита плана поднимает доменную ошибку → HTTP 402/403. Free-юзер на 6-м канале блокируется. Все секреты — из env (sensitive.env). Все действия по окружению/тестам — через root `make`. DoD ниже.

## Discussion
<!-- durable record of clarifications. -->
- Q: Stripe или крипта? → A: [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md) + overview §6 → Decision: **крипто-приём через NOWPayments**, никакого Stripe. Предыдущая Stripe-версия этой задачи (`task-010-billing-stripe.md`) отменена — ADR-004 переписывает биллинг на NOWPayments. Тарифная таблица лимитов из overview §6 остаётся источником истины.
- Q: Провайдер жёстко зашит? → A: нет, абстрагируем (ADR-004 §1) → Decision: `billing/gateway/base.py::PaymentGateway` Protocol (`create_invoice(plan, period, user) -> Invoice`, `verify_ipn(headers, body) -> IpnEvent`); реализация `billing/gateway/nowpayments.py`. Замена на CoinGate = новая реализация Protocol, ядро биллинга не меняется.
- Q: Подписки? → A: у крипто-шлюзов нет нативных подписок (ADR-004 §2/§4) → Decision: модель **invoice + IPN**, период держим сами в `subscriptions.expires_at`; за N дней до конца — renewal-invoice (уведомление юзеру); истёк → откат на Free + `assert_within_limit` применяет лимиты. Сети/токены выбираются на стороне NOWPayments — мы создаём invoice под план/период.
- Q: Где источник лимитов? → A: **overview §6 таблица** → Decision: лимиты — именованные константы/конфиг (`billing/plans.py`): `Plan` enum (free/pro/team) + таблица `PLAN_LIMITS` (channels 5/100/500; topics 1/5/None=∞; alerts_per_day 5/None/None; history_days None/30/90; api_access; webhook_delivery). `None` = без лимита. Никаких magic literals в роутах (CONVENTIONS «No magic literals»).
- Q: Единая точка enforcement? → A: ADR-003 «plan-gating в одном месте» → Decision: `billing/limits.py::assert_within_limit(user, resource: Resource)` — единственный enforcement-вход; считает текущее использование через storage-репозитории, сравнивает с `PLAN_LIMITS[user.plan]`; over-limit → доменная `PlanLimitExceeded` → API мапит в 402 (требуется апгрейд) / 403 (фича плана недоступна, напр. webhook/API на Free). watchlist (task-004) вызывает его перед create.
- Q: Как обновляется план? → A: только через верифицированный IPN → Decision: единственный writer плана/`expires_at` — обработчик IPN с валидной HMAC-подписью (`billing/webhook.py`); клиент/SPA план не выставляет (no client-trust). Идемпотентность по NOWPayments `payment_id`.
- Q: Верификация IPN? → A: обязательна (ADR-004 §Security) → Decision: HMAC-подпись `x-nowpayments-sig` от `IPN secret` над отсортированным/raw телом; невалидная/отсутствующая подпись → 4xx, тело не парсится и не применяется. Сверка `order_id`/суммы/валюты с созданным инвойсом. Статус-машина: `waiting`/`confirming`/`confirmed`/`finished`/`partially_paid`/`expired`.
- Q: Сторонние секреты? → A: `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET` — только из env (ADR-005 §4, `sensitive.env`), `.env.example`/deploy.env обновляются; никаких хардкодов; IPN-эндпоинт — только за nginx (network-design).

## Scope
> **Раскладка:** трогаем только `backend/` (Python). Один новый доменный модуль `trendpulse.billing` (+ подпакет `gateway/`) + точечная интеграция в watchlist-роут (task-004) и в `api`/`config`. landing/frontend (UI оплаты — эпик C) — вне этой задачи.

- **Touch ONLY (создать/изменить):**
  - `backend/src/trendpulse/billing/__init__.py` — публичный фасад модуля (экспорт `assert_within_limit`, `Plan`, `PlanLimitExceeded`, сервис invoice/IPN).
  - `backend/src/trendpulse/billing/plans.py` — `Plan` enum (free/pro/team), `BillingPeriod` (month), `PlanLimits` (pydantic/dataclass) и таблица `PLAN_LIMITS` по overview §6 (именованные константы, `None`=∞); цены под invoice (Pro $19/мес, Team $79/мес).
  - `backend/src/trendpulse/billing/limits.py` — единый enforcement: `Resource` enum (channels/topics/alerts_per_day/history/api_access/webhook_delivery), `assert_within_limit(user, resource)`, доменная `PlanLimitExceeded` (+ код 402/403). Использует storage-репозитории для текущего usage (через их публичные функции — CONVENTIONS «cross-module via service interfaces»).
  - `backend/src/trendpulse/billing/gateway/base.py` — `PaymentGateway` Protocol: `create_invoice(plan, period, user) -> Invoice`, `verify_ipn(headers, body) -> IpnEvent`; доменные DTO `Invoice` (payment/redirect url, order_id, amount, currency), `IpnEvent` (payment_id, order_id, status, amount, currency).
  - `backend/src/trendpulse/billing/gateway/nowpayments.py` — реализация Protocol поверх NOWPayments API: `create_invoice` (POST invoice, ключ из settings), `verify_ipn` (HMAC `x-nowpayments-sig` от IPN secret, парсинг тела в `IpnEvent`). Провайдер сменяем (CoinGate — новая реализация).
  - `backend/src/trendpulse/billing/service.py` — оркестрация: `create_invoice(user, plan, period)` через gateway; запись/чтение `subscriptions`; `activate_or_extend(user, plan, period)` (выставляет `expires_at`); `downgrade_expired()` (истёкшие → Free).
  - `backend/src/trendpulse/billing/webhook.py` — `process_ipn(headers, body) -> IpnResult`: `gateway.verify_ipn` (HMAC) → сверка `order_id`/суммы/валюты с инвойсом → статус-машина; идемпотентность по `payment_id` (хранить обработанные); на `finished`/`confirmed` → `service.activate_or_extend`; `partially_paid`/`expired`/прочие → без активации.
  - `backend/src/trendpulse/billing/router.py` — FastAPI router: `POST /billing/invoice` (за `current_user`, тело — план+период), `POST /billing/ipn` (raw body, проверка HMAC, **без** `current_user`). Pydantic-схемы запроса/ответа.
  - **Изменить** `backend/src/trendpulse/config.py` — добавить `nowpayments_api_key`, `nowpayments_ipn_secret`, (опц.) `nowpayments_base_url` в Settings (pydantic-settings, из env/sensitive.env).
  - **Изменить** `backend/src/trendpulse/api/main.py` — `include_router(billing.router)` + маппинг `PlanLimitExceeded` → 402/403 (exception handler).
  - **Изменить** watchlist-роут (task-004, `trendpulse/api/.../watchlist*`) — вызвать `assert_within_limit(user, Resource.channels|topics)` перед create (минимальная точечная вставка).
  - **Изменить** `backend/pyproject.toml` (core-deps: `httpx` для NOWPayments API, если ещё нет), `development/.env.example` + `development/env/deploy.env`/`sensitive.env` (NOWPayments env per ADR-005).
  - `backend/tests/unit/test_billing_ipn.py` (AC1-якорь — HMAC verification), `tests/unit/test_billing_limits.py`, `tests/unit/test_billing_invoice.py`, при необходимости `tests/integration/test_billing_ipn_route.py`.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме обновления `tasks-index.md` на ship), `landing/**`, `frontend/**`, `collector/**`, `pipeline/**`, `scorer/**`. Не менять auth (task-003) и data model (task-002) сверх чтения плана/записи `subscriptions`; не реализовывать UI оплаты; **никакого Stripe** нигде.
- **Blast radius:** новый writer плана/`subscriptions.expires_at` — только IPN-обработчик. Новый потребитель — watchlist (task-004) и любые будущие gated-поверхности через `assert_within_limit`. Меняет публичный контракт `billing` (фасад), `config` (новые env), `api` (новый router + IPN-эндпоинт + 402/403). Внешняя зависимость — NOWPayments API + входящий IPN (только за nginx).

## Acceptance Criteria
- [ ] **AC1 — IPN HMAC verification (failing-test anchor).** Given IPN-тело + заголовок `x-nowpayments-sig`, вычисленный с **неверным** IPN secret, When `gateway.verify_ipn(headers, body)` (или `billing.webhook.process_ipn`), Then поднимается ошибка верификации / возвращается reject (тело не применяется). Тест пишется ПЕРВЫМ (RED) до реализации HMAC-проверки в `nowpayments.py`/`webhook.py`.
- [ ] **AC2 — create invoice.** Given аутентифицированный юзер, план Pro, период month, When `POST /billing/invoice {plan:"pro", period:"month"}`, Then создаётся NOWPayments invoice под цену Pro и в ответе payment/redirect (url) + order_id (NOWPayments API замокан).
- [ ] **AC3 — валидный IPN `finished` активирует план.** Given IPN со статусом `finished`/`confirmed`, **валидной** HMAC-подписью и совпадающими `order_id`/amount/currency, When `POST /billing/ipn`, Then план пользователя становится `pro`, `subscriptions.expires_at` выставлен (период), ответ 200.
- [ ] **AC4 — невалидная подпись отвергается.** Given IPN-тело с **невалидной/отсутствующей** HMAC-подписью, When `POST /billing/ipn`, Then 4xx, план НЕ меняется, тело не применяется (no trust без верификации).
- [ ] **AC5 — идемпотентность/replay по `payment_id`.** Given валидный `finished`-IPN, уже обработанный ранее, When повторная доставка того же `payment_id`, Then состояние не меняется дважды (нет double-extend `expires_at`), ответ 200, без падения.
- [ ] **AC6 — partially_paid/expired не активируют.** Given IPN со статусом `partially_paid` или `expired` (валидная подпись), When `POST /billing/ipn`, Then план НЕ активируется/не продлевается; статус залогирован, ответ 200.
- [ ] **AC7 — Free на cap каналов блокируется.** Given Free-юзер с 5 каналами (cap 5 по overview §6), When попытка добавить 6-й канал через watchlist (task-004), Then 402, канал не создаётся; на Pro (cap 100) тот же шаг проходит; на Team (cap 500) — тоже.
- [ ] **AC8 — фича-гейтинг + истечение.** Given Free-юзер, When `assert_within_limit(user, Resource.webhook_delivery)` (или `api_access`), Then 403 (фича недоступна на плане); Pro проходит webhook, Team — webhook + api_access. Истёкший Pro (`expires_at` в прошлом) откатывается на Free → `assert_within_limit(Resource.channels)` блокирует при usage > free-cap.

## Plan
0. locate: подтвердить точки интеграции — `config.py` (Settings), `api/main.py` (router include + handlers), watchlist-роут (task-004), storage-репозитории для usage-счётчиков (каналы/топики/алерты-за-день) и `subscriptions` (plan/`expires_at`, task-002). Завести ветку, зафиксировать `baseline_commit`.
1. `billing/plans.py` — `Plan(str, Enum)` free/pro/team; `BillingPeriod`; `PlanLimits` (channels, topics, alerts_per_day, history_days, api_access, webhook_delivery); `PLAN_LIMITS: dict[Plan, PlanLimits]` строго по overview §6 (`None`=∞); цены Pro/Team. Именованные константы, без magic literals.
2. `billing/gateway/base.py` — `PaymentGateway` Protocol + DTO `Invoice`/`IpnEvent`.
3. **RED:** `tests/unit/test_billing_ipn.py` — HMAC: тело + подпись с неверным secret → `verify_ipn`/`process_ipn` reject (AC1). Прогнать — падает (нет реализации).
4. `billing/gateway/nowpayments.py` — `create_invoice` (NOWPayments API, ключ из settings), `verify_ipn` (HMAC `x-nowpayments-sig` от IPN secret → `IpnEvent`). GREEN для AC1.
5. `config.py` — добавить `nowpayments_api_key`, `nowpayments_ipn_secret` (+ base url). `.env.example` + deploy.env/sensitive.env per ADR-005. `pyproject.toml` (`httpx` если нужно).
6. `billing/limits.py` — `Resource` enum, `PlanLimitExceeded(code:int)`, `assert_within_limit(user, resource)`: usage через storage-сервис vs `PLAN_LIMITS[user.plan]`; quantitative over-limit → 402, feature-gate → 403. Тест `test_billing_limits.py` (AC7/AC8).
7. `billing/service.py` — `create_invoice(user, plan, period)` через gateway; `activate_or_extend(user, plan, period)` (период → `expires_at`); `downgrade_expired()`.
8. `billing/webhook.py` — `process_ipn`: verify (HMAC) → сверка `order_id`/amount/currency → статус-машина; идемпотентность по `payment_id`; `finished`/`confirmed` → `activate_or_extend`; `partially_paid`/`expired` → no-op. Тесты AC3/AC4/AC5/AC6.
9. `billing/router.py` — `POST /billing/invoice` (`Depends(current_user)`), `POST /billing/ipn` (raw `Request.body()`, header `x-nowpayments-sig`, без auth). Pydantic-схемы. Тест AC2.
10. `api/main.py` — `include_router`; exception handler `PlanLimitExceeded` → JSON 402/403 (envelope как patterns.md). Точечно: watchlist-роут (task-004) — вызвать `assert_within_limit` перед create (AC7).
11. verify (G2): root `make ci-fast`; затем `make build && make up` (или `make dev-up`) и прогнать invoice/IPN/limit-флоу против реального FastAPI (NOWPayments — мок/тестовый ключ), проверить AC2–AC8 вживую; обновить `tasks-index.md` на ship.

## Invariants
- **Единая точка enforcement.** Лимиты плана проверяются ТОЛЬКО через `billing.limits.assert_within_limit`; роуты не повторяют пороги (ADR-003, CONVENTIONS «no magic literals», «plan-gating в одном месте»).
- **План меняет только верифицированный IPN.** Единственный writer плана/`subscriptions.expires_at` — обработчик IPN с валидной HMAC-подписью; клиент/SPA план не выставляет.
- **No trust без верификации.** Тело IPN не парсится/не применяется до успешной HMAC-проверки (`x-nowpayments-sig` от IPN secret).
- **Сверка инвойса.** `order_id`/сумма/валюта IPN сверяются с созданным инвойсом до активации (защита от подмены).
- **Провайдер за абстракцией.** Ядро биллинга зависит от `PaymentGateway` Protocol, не от NOWPayments напрямую; CoinGate — новая реализация без изменения `limits`/`service`/`webhook`-контрактов (ADR-004 §1).
- **Период считаем сами.** Нет нативных крипто-подписок; срок — `subscriptions.expires_at`; продление — renewal-invoice; истёк → Free + лимиты (ADR-004 §2/§4).
- **Секреты — только env.** `NOWPAYMENTS_API_KEY`/`NOWPAYMENTS_IPN_SECRET` из pydantic-settings (sensitive.env, ADR-005); никаких хардкодов; в репо только `.env.example`/несекретный deploy.env; IPN — только за nginx.
- **Лимиты — конфиг, не литералы.** Значения из overview §6 живут в `PLAN_LIMITS`; `None`=без лимита.
- **Идемпотентность IPN.** Повторная доставка одного `payment_id` не меняет состояние дважды и не падает.
- **Cross-module через сервис-интерфейсы.** Usage и смена плана/`subscriptions` — через публичные функции `storage`, без лазанья во внутренности (CONVENTIONS).
- **Full type hints, mypy strict.** Никаких bare `Any` / `# type: ignore`; ошибки — доменные, не bare `except` (CONVENTIONS).

## Edge cases
- IPN без/с битым заголовком `x-nowpayments-sig` → 4xx, тело игнорируется (AC4).
- Повторная доставка IPN (NOWPayments ретраит) → идемпотентность по `payment_id` (AC5).
- `order_id`/сумма/валюта IPN не совпадают с инвойсом → reject, без активации (лог, не угадываем).
- `partially_paid` (недоплата) / `expired` (инвойс протух) → без активации (AC6); политика возврата/доплаты — out of scope (отдельная задача).
- Промежуточные статусы `waiting`/`confirming` → ack 200, без смены плана (ждём `finished`/`confirmed`).
- Крипто-волатильность: сумма в крипте плавает — сверяем по той валюте/сумме, что зафиксировал NOWPayments в инвойсе/IPN, не пересчитываем сами.
- Downgrade при истечении (`expires_at` в прошлом) → план понижается на Free, существующие ресурсы не удаляем; новые блокируются `assert_within_limit` (AC8). Удаление избытка — out of scope (grace policy/отдельная задача).
- `None`(∞)-лимит (topics на Team, alerts на Pro/Team) → `assert_within_limit` всегда проходит quantitative-проверку.
- Feature-gate vs quantitative: api_access/webhook_delivery → 403 (нет права на плане), числовой cap → 402 (нужен апгрейд) — разные коды.
- Renewal до истечения: создаётся новый invoice, оплата продлевает `expires_at` от текущего конца (не от now), чтобы не терять остаток периода.
- Гонка двойного create на границе cap (две параллельные вставки на 5→6) → проверка usage в той же транзакции/через атомарный счётчик storage; полноценный distributed-lock — за рамками, но не допускать обхода cap «по чтению».

## Test plan
- **unit (RED-first):** `test_billing_ipn.py` — AC1 (неверный secret → reject HMAC), AC3 (валидный `finished` → activate + `expires_at`), AC4 (невалидная подпись → reject), AC5 (повтор `payment_id` → идемпотентность), AC6 (`partially_paid`/`expired` → no-op), несовпадение `order_id`/amount → reject. `test_billing_limits.py` — AC7 (Free@cap channels → `PlanLimitExceeded`/402), AC8 (feature-gate webhook/api → 403; истёкший Pro → Free → блок), `None`-лимит проходит. `test_billing_invoice.py` — AC2 (invoice под нужную цену/период, NOWPayments API замокан).
- **integration (по требованию, маркер `integration`):** `test_billing_ipn_route.py` — `POST /billing/ipn` через TestClient: подписанное тело (валидный/невалидный secret) → 200/4xx; watchlist create на cap → 402 (AC7) с реальным FastAPI + БД.
- **runtime/behavioral (G2):** `make build && make up` (или `make dev-up`) → invoice-endpoint отдаёт payment/redirect (NOWPayments мок/тестовый ключ), IPN (валид/невалид) активирует/не активирует план в БД, идемпотентность повторной доставки, Free на 6-м канале получает 402, истёкший план откатывается на Free.

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
- [ ] 5.5 security (applicable: IPN HMAC verification + secrets + idempotency/replay — verify `x-nowpayments-sig` HMAC, no trust of body without verification, `order_id`/amount/currency match, idempotency by `payment_id`, NOWPayments API key/IPN secret via env (sensitive.env, ADR-005), IPN endpoint only behind nginx)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по эталону task-001; крипто-биллинг следует [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md) (NOWPayments, invoice+IPN, провайдер за абстракцией) + overview §6 (сети/токены + тарифная таблица) + [ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md) (секреты в sensitive.env, IPN за nginx); зависит от task-003 (auth/`current_user`) и task-004 (watchlist — первый потребитель `assert_within_limit`). Заменяет отменённую Stripe-версию `task-010-billing-stripe.md` — никакого Stripe.)
