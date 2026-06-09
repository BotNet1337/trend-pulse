---
id: TASK-017
title: Billing & Account UI — план Free/Pro/Team, крипто-инвойс, delivery-config, удаление аккаунта (GDPR)
status: in-progress      # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "7990c972617018b129c36af5cb87920165e89c2a"
branch: "gsd/phase-017-billing-account-ui"
tags: [frontend, billing, account, gdpr, delivery-config, security, e2e]
---

# TASK-017 — Billing & Account UI (Epic C · C5)

> Экран плана Free/Pro/Team (текущий план из `GET /users/me`), создание **крипто-инвойса** (`POST /billing/invoice` → показать адрес/QR/статус), **delivery-config** (telegram bot token/chat_id + webhook URL для Pro+ — тонкая backend-добавка `GET/PATCH /users/me/delivery-config`, переиспользовать SSRF-валидацию task-009), и **удаление аккаунта** (GDPR, `DELETE /account`, с подтверждением). Security: токены не в бандле/логах, webhook URL — клиентская валидация + серверный SSRF-guard, подтверждение деструктивных действий. e2e: смена/просмотр плана, создание инвойса (мок IPN), сохранение delivery-config (happy+невалидный webhook), удаление аккаунта с подтверждением.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §6) — оплата **только крипта** (NOWPayments, [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md)), **никакого Stripe**. Тарифы: **Free** $0 (5 каналов, 1 топик, 5 алертов/день, без истории, только Telegram-доставка) · **Pro** $19/мес (100 каналов, 5 топиков, ∞ алертов, история 30 дней, +webhook) · **Team** $79/мес (500 каналов, ∞ топиков, ∞ алертов, история 90 дней, +API access). Реальные роуты (источник истины): `POST /billing/invoice` (`InvoiceResponse` — создаёт NOWPayments-инвойс на сумму плана, за `current_user`); `POST /billing/ipn` (webhook, raw-body, **без auth — НЕ для UI**); `DELETE /account` (GDPR, 204, скоуп только `current_user.id`).

Backend-пробелы, которые C5 закрывает тонкими additive-роутами: **`GET/PATCH /users/me/delivery-config`** (поля `telegram_bot_token`/`chat_id`/`webhook_url` уже на User из [task-009](./task-009-alert-delivery.md)) — read/update конфига доставки; текущий план — из `GET /users/me` (добавлен в C2). PATCH `webhook_url` → **SSRF-валидация на backend уже есть** (task-009 `build_ssrf_safe_client`), переиспользовать; в UI — клиентская валидация формата + предупреждение.

База: [task-013](./task-013-frontend-foundation.md) (дизайн-система, клиент, типы), [task-014](./task-014-auth-flow-ui.md) (guard, `current_user`/`plan`). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — backend-добавки: full type hints, Pydantic на границе, no magic literals (суммы/окна — из `billing/plans.py`), секреты из env; никакого Stripe.

## Goal

После задачи: пользователь видит свой план (Free/Pro/Team из `GET /users/me`) и сравнение тарифов; инициирует апгрейд → `POST /billing/invoice` → UI показывает крипто-адрес/QR/сумму/статус (ожидание оплаты); настраивает доставку (telegram bot token + chat_id; webhook URL — только Pro+) через `GET/PATCH /users/me/delivery-config`; невалидный webhook URL отклоняется (клиентская валидация + серверный SSRF-guard); удаляет аккаунт (`DELETE /account`) с явным подтверждением (GDPR). Security: токены не утекают в бандл/логи; деструктивные действия — за подтверждением. e2e покрывают план, инвойс (мок IPN), delivery-config (happy+невалидный webhook), удаление с подтверждением через nginx. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по overview §6 + task-009/010/011; обратимы. -->
- Q: Откуда текущий план? → A: `GET /users/me` (C2) → Decision: UI читает `plan` из `current_user`; экран показывает текущий план + сравнение Free/Pro/Team (числа из overview §6 / единого источника, не inline-магия).
- Q: Оплата — что показывает UI? → A: `POST /billing/invoice` → `InvoiceResponse` → Decision: при апгрейде вызвать `POST /billing/invoice` (сумма плана считается backend), показать поля инвойса (адрес/сумма/сеть/QR/статус) из `InvoiceResponse`; **никакого Stripe**; апгрейд плана подтверждается backend по IPN (`POST /billing/ipn` — webhook, UI его не дёргает). UI поллит/показывает статус ожидания.
- Q: IPN в e2e? → A: webhook без auth, raw-body → Decision: e2e **мокает IPN** (симулирует подтверждение оплаты на стороне backend-теста/фикстуры) — UI показывает переход статуса; реальный NOWPayments не дёргаем в e2e.
- Q: delivery-config — где хранится и что редактируем? → A: поля на User (task-009) → Decision: **тонкая backend-добавка** `GET/PATCH /users/me/delivery-config` (за `current_user`): `telegram_bot_token`, `chat_id`, `webhook_url`. `webhook_url` — только Pro+ (feature-gate по плану, `403` на Free). PATCH `webhook_url` → переиспользовать SSRF-валидацию task-009 (`build_ssrf_safe_client`/валидатор), не катать свою.
- Q: Токены доставки в UI? → A: чувствительные → Decision: `telegram_bot_token` — write-mostly (PATCH принимает, GET отдаёт маскированно/«задан»/последние символы, не полный токен в бандле/логах); никаких токенов в localStorage/URL/логах; вводятся, не светятся обратно целиком.
- Q: webhook URL валидация? → A: SSRF-риск → Decision: **клиентская** валидация формата (https, не localhost/private — UX-предупреждение) + **серверный SSRF-guard** (task-009, источник истины) → `422`/ошибка при опасном URL; UI показывает понятное предупреждение.
- Q: Удаление аккаунта? → A: `DELETE /account` (GDPR, 204) → Decision: за двойным подтверждением (модалка + ввод/чекбокс); после — logout + редирект; скоуп строго `current_user.id` (backend, task-011).

## Scope
> **frontend** (план/инвойс/delivery-config/удаление) + **тонкая backend-добавка `GET/PATCH /users/me/delivery-config`** (за `current_user`, переиспользует SSRF task-009). `POST /billing/invoice` и `DELETE /account` уже есть — только потребляем. Billing-ядро/IPN (task-010) и SSRF-клиент (task-009) НЕ реализуем заново.

- **Touch ONLY (создать/изменить):**
  - **Backend (тонкая additive-добавка):**
    - `backend/src/trendpulse/api/account/delivery_config.py` (или в существующем account/users-модуле) — **новый** `GET /users/me/delivery-config` (read; `telegram_bot_token` маскированно, `chat_id`, `webhook_url`) и `PATCH /users/me/delivery-config` (update; `webhook_url` — feature-gate Pro+, SSRF-валидация task-009 `build_ssrf_safe_client`); за `Depends(current_user)`.
    - `backend/src/trendpulse/api/account/schemas.py` — Pydantic `DeliveryConfigRead` (маскированный токен)/`DeliveryConfigUpdate` (валидируется на границе; `webhook_url` через SSRF-guard).
    - `backend/src/trendpulse/api/main.py` — `include_router` delivery-config роута (read+patch).
    - `backend/tests/integration/test_delivery_config.py` — AC: 401 без cookie / 200 read (маскированный токен) / PATCH happy / невалидный webhook (SSRF) → ошибка / `webhook_url` на Free → `403`.
  - **Frontend:**
    - `frontend/src/pages/billing/**` — **новые** страницы: план/тарифы (`/billing`), инвойс (адрес/QR/сумма/статус).
    - `frontend/src/pages/account/settings.tsx` + `frontend/src/features/account/**` — delivery-config форма (bot token/chat_id/webhook), удаление аккаунта (адаптировать существующий `features/account/delete`).
    - `frontend/src/features/billing/**` — **новый** feature: `createInvoice` (`POST /billing/invoice`), показ/поллинг статуса инвойса.
    - `frontend/src/features/delivery-config/**` — **новый** feature: `useDeliveryConfig` (GET), `updateDeliveryConfig` (PATCH); клиентская валидация webhook (https/non-private предупреждение).
    - `frontend/src/entities/plan/**` — **новая** entity: сравнение Free/Pro/Team (числа из единого источника, не inline-магия).
    - `frontend/src/shared/api/gen.types.ts` — **регенерировать** после добавления delivery-config роута.
    - `frontend/src/app/router/**` — billing/account-роуты за guard (C2).
    - `frontend/tests/e2e/billing-account.spec.ts` — **новый** e2e: план, инвойс (мок IPN), delivery-config (happy+невалидный webhook), удаление с подтверждением.
    - `frontend/tests/unit/billing/**`, `frontend/tests/unit/delivery-config/**` — **новые** unit: сравнение планов, webhook-валидация, маскирование токена, confirm-флоу.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/trendpulse/billing/**` ядро (NOWPayments/IPN/plans — task-010, только потребляем `POST /billing/invoice` + читаем `PLAN_LIMITS`), `backend/src/trendpulse/alerts/**` SSRF-клиент (task-009 — **переиспользуем**, не переписываем), `DELETE /account`-механику (task-011 — только дёргаем). Не реализовывать watchlists/alerts-экраны (C3/C4). **Никакого Stripe.** Не дёргать `POST /billing/ipn` из UI.
- **Blast radius:** новые billing/account-экраны + delivery-config read/patch-роут; завершает пользовательский C-флоу (план→оплата→доставка→удаление). Security-чувствительная задача: секреты доставки, SSRF webhook, деструктивное удаление → **стадия 5.5 security обязательна**. Backend-добавка аддитивна (read+patch за `current_user`, SSRF переиспользован). Регенерация типов добавляет delivery-config-операции.

## Acceptance Criteria
- [ ] **AC1 — план показан, апгрейд создаёт инвойс (failing-test anchor).** Given залогиненный пользователь (план из `GET /users/me`), When открывает `/billing` и инициирует апгрейд, Then `POST /billing/invoice` → `InvoiceResponse`, UI показывает крипто-адрес/сумму/сеть/QR/статус (ожидание). e2e + integration пишутся ПЕРВЫМИ (RED).
- [ ] **AC2 — `GET/PATCH /users/me/delivery-config` (backend-добавка).** Given новый роут, When без cookie → `401`; с cookie GET → `200` (`telegram_bot_token` маскирован, `chat_id`, `webhook_url`); PATCH валидным конфигом → `200`/сохранено; за `current_user`, tenant-scoped.
- [ ] **AC3 — delivery-config UI happy.** Given Pro+ пользователь, When вводит bot token + chat_id + webhook URL и сохраняет, Then `PATCH` успешен, токен в UI не светится целиком (маскирован), значения сохранены (повторный GET подтверждает).
- [ ] **AC4 — невалидный webhook отклоняется (SSRF).** Given webhook URL на private/localhost/не-https, When сохранение, Then клиентская валидация предупреждает И серверный SSRF-guard (task-009) отклоняет (`422`/ошибка); UI показывает понятное сообщение, конфиг не сохраняется опасным.
- [ ] **AC5 — webhook feature-gate (Free).** Given план Free, When попытка задать webhook URL, Then backend `403` (feature не на плане), UI показывает «webhook доступен на Pro+» + апселл; bot token/chat_id (Telegram) доступны всем планам.
- [ ] **AC6 — удаление аккаунта с подтверждением (GDPR).** Given залогиненный пользователь, When инициирует удаление и проходит явное подтверждение (модалка + ввод/чекбокс), Then `DELETE /account` → `204`, logout + редирект; без подтверждения запрос не уходит.
- [ ] **AC7 — security + поведенческая (G2) через nginx.** Given бандл/логи, When инспекция, Then токены доставки/секреты НЕ в бандле/логах/localStorage/URL; и: `make up` → Playwright `billing-account.spec.ts` против реального стека за nginx — AC1/AC3/AC4/AC6 наблюдаемы (инвойс с мок-IPN: статус переходит в paid), артефакты (trace/screenshot/video on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-017-billing-account-ui`.
1. **RED (backend):** `backend/tests/integration/test_delivery_config.py` — `GET/PATCH /users/me/delivery-config` 401/200, маскированный токен, невалидный webhook (SSRF) → ошибка, `webhook_url` на Free → `403`. Падает (роута нет). AC2/AC4/AC5-якорь.
2. Backend-добавка: `api/account/delivery_config.py` + схемы (маскирование токена, `DeliveryConfigUpdate` через SSRF-валидатор task-009, feature-gate webhook по плану); `include_router`. `make ci-fast` зелёный.
3. Регенерировать `gen.types.ts` — delivery-config-операции.
4. **RED (frontend):** `frontend/tests/e2e/billing-account.spec.ts::plan_and_invoice` — план показан, апгрейд → инвойс. Падает. AC1-якорь.
5. `entities/plan` (сравнение тарифов) + `features/billing` (createInvoice + статус) + `pages/billing`; `features/delivery-config` + форма (клиентская webhook-валидация, маскирование токена); адаптировать `features/account/delete` (confirm-флоу).
6. unit-тесты (сравнение планов, webhook-валидация, маскирование, confirm); **GREEN** локально.
7. **G2 + security:** `make up`; Playwright `billing-account.spec.ts` зелёный через nginx (инвойс с мок-IPN, AC1/AC3/AC4/AC6/AC7); backend integration зелёный (AC2/AC4/AC5); **стадия 5.5**: токены не в бандле/логах, SSRF webhook, confirm деструктивного удаления.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Никакого Stripe — только крипта (NOWPayments)** — `POST /billing/invoice`; сумма плана считается backend, UI не хардкодит суммы как платёжную логику (числа тарифов — из единого источника для копи).
- **Секреты доставки не в бандле/логах/localStorage/URL** — `telegram_bot_token` write-mostly, GET отдаёт маскированно; никаких токенов в клиентском состоянии/логах (CONVENTIONS security).
- **SSRF webhook — серверный guard (task-009) источник истины** — переиспользуем `build_ssrf_safe_client`/валидатор; клиентская валидация — только UX-предупреждение, не замена серверной.
- **Деструктивные действия за подтверждением** — `DELETE /account` (GDPR) только после явного confirm; скоуп строго `current_user.id` (backend task-011).
- **Backend-добавки — read/patch за `current_user`, tenant-scoped, full type hints, Pydantic на границе, no magic literals** (суммы/окна из `billing/plans.py`); SSRF не переписываем.
- **Cookie-auth, реальные данные через nginx** — `withCredentials: true`; e2e/прод против реального API за edge (IPN мокается только в тесте).
- **Единая дизайн-система** (C1) — план-сравнение/инвойс/формы/confirm-модалки на общих токенах; responsive + базовая a11y (модалка с focus-trap, поля с label/aria).
- **Webhook — feature Pro+** — `403` на Free → апселл; Telegram-доставка (bot token/chat_id) доступна всем планам.

## Edge cases
- IPN не пришёл / оплата pending долго → UI показывает статус «ожидание оплаты», не зависает, даёт обновить/повторить; апгрейд плана только по backend-подтверждению.
- Пользователь закрыл инвойс до оплаты → план не меняется; повторный апгрейд создаёт новый инвойс.
- `telegram_bot_token` отправлен пустым/частично → серверная валидация; маскированный GET не «восстанавливает» полный токен на клиент.
- webhook URL = `http://localhost`/`http://169.254.169.254`/private-IP → SSRF-guard task-009 отклоняет (`422`); клиентская валидация предупреждает раньше.
- webhook на Free → `403`; UI не даёт «фейково» сохранить, показывает апселл.
- Двойной сабмит удаления / отмена в модалке → запрос уходит ровно один раз и только после confirm; отмена — без запроса.
- Удаление успешно (`204`), но сессия ещё «жива» в UI → принудительный logout + редирект; последующий `GET /users/me` → `401`.
- Сумма плана/валюта меняется на backend → UI берёт из `InvoiceResponse`, не из inline-константы (no magic literal в платёжной логике).

## Test plan
- **integration (backend):** `test_delivery_config.py` — AC2 (`GET/PATCH` 401/200, маскированный токен, RED-якорь), AC4 (невалидный webhook → SSRF-ошибка task-009), AC5 (`webhook_url` на Free → `403`).
- **unit (frontend):** `tests/unit/billing/**` (сравнение планов, статус инвойса), `tests/unit/delivery-config/**` (webhook-валидация формата, маскирование токена, confirm-флоу удаления).
- **e2e (Playwright):** `tests/e2e/billing-account.spec.ts` — AC1 (план + инвойс с мок-IPN→paid, RED-якорь), AC3 (delivery-config happy, токен маскирован), AC4 (невалидный webhook → ошибка), AC6 (удаление с подтверждением → 204 → logout). Артефакты on-failure.
- **runtime/behavioral (G2):** `make up` → Playwright против реального стека за nginx (AC7); инспекция бандла/логов на отсутствие секретов; ручная проверка SSRF-отклонения webhook и confirm-модалки удаления.
- **security (5.5):** токены не в бандле/логах/localStorage/URL; SSRF webhook (серверный guard task-009 активен); confirm деструктивного удаления; cookie/CSRF (OAuth/billing) без утечек.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 5
baseline_commit: "7990c972617018b129c36af5cb87920165e89c2a"
branch: "gsd/phase-017-billing-account-ui"
lock: "loop-017"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — backend integration 12/12 + Playwright 4/4 e2e за nginx, vitest 120)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (XSS/санитизация, secrets не в бандле, cookie/CSRF, SSRF в webhook-полях)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-003/004 и контексту: экран плана Free/Pro/Team (план из GET /users/me), крипто-инвойс (POST /billing/invoice, никакого Stripe), delivery-config (тонкая backend-добавка GET/PATCH /users/me/delivery-config, SSRF webhook переиспользует task-009), удаление аккаунта (DELETE /account, GDPR, confirm). Security-чувствительно → стадия 5.5 обязательна. deps: 014 (guard/current_user), backend 010 (billing), 009 (delivery/SSRF), 011 (GDPR delete). Billing-ядро/IPN/SSRF не переписываем. locate+plan выполнены этим планированием — executor стартует с «3 do».)
