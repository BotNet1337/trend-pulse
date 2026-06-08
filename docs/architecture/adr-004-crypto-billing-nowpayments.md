# ADR-004 — Crypto billing via NOWPayments (no Stripe)

- Status: **Accepted**
- Date: 2026-06-08
- Context: [overview §6](../product/overview.md), [high-level-architecture.md](./high-level-architecture.md)

## Context

Продукт принимает оплату **криптовалютой напрямую** (overview §6): Solana (USDC/SOL), Ethereum (USDC/ETH), TON (USDT/TON). Никакого Stripe. Нужен платёжный шлюз с API + webhook на успешную оплату. Выбран **NOWPayments** (альтернатива — CoinGate; интерфейс абстрагируем, чтобы можно было заменить).

## Decision

1. **Провайдер за абстракцией.** `billing/gateway/base.py`: `PaymentGateway` Protocol (`create_invoice(plan, period, user) -> Invoice`, `verify_ipn(headers, body) -> IpnEvent`). Реализация `billing/gateway/nowpayments.py`. Замена на CoinGate = новая реализация, ядро биллинга не меняется (ср. с ADR-001).
2. **Модель оплаты — инвойсы + IPN, период считаем сами.** У крипто-шлюзов нет «подписок» как у Stripe. Мы:
   - создаём invoice на период подписки (Pro/Team, месяц) через NOWPayments;
   - пользователь платит крипту (выбор сети/токена на стороне шлюза);
   - NOWPayments шлёт **IPN (webhook)** со статусом платежа; мы **проверяем HMAC-подпись** (`x-nowpayments-sig`, ключ — IPN secret) и сверяем сумму/валюту/order_id;
   - на статусе `finished`/`confirmed` — активируем/продлеваем план в нашей БД (`subscriptions`), идемпотентно по `payment_id`.
3. **Никаких приватных ключей кошельков в приложении.** Получение средств — через NOWPayments на наш payout-адрес; приложение хранит только `NOWPAYMENTS_API_KEY` + `NOWPAYMENTS_IPN_SECRET` (из `sensitive.env`, ADR-005).
4. **Подписки/продление.** Срок плана хранится у нас (`subscriptions.expires_at`); за N дней до конца — инвойс на продление (уведомление пользователю). Истёк → откат на Free + применение лимитов (task-010 limits, ADR-003).
5. **Лимиты планов** Free/Pro/Team — как в overview §6 (каналы 5/100/500, топики 1/5/∞, алерты/день 5/∞/∞, история −/30/90 дней, webhook −/✓/✓, API −/−/✓). Единая точка enforcement (`billing/limits.py`).

## Security (обязательно на task-010)

- Проверка HMAC-подписи IPN; **не доверять телу webhook без верификации**.
- Сверка `order_id`/суммы/валюты с созданным инвойсом; защита от replay (идемпотентность по `payment_id`, статус-машина).
- Секреты только из env (ADR-005); IPN-эндпоинт — только за nginx (network-design).

## Consequences

- (+) Прямой крипто-приём под целевую аудиторию; нет Stripe-зависимости/комиссий.
- (+) Провайдер сменяем (NOWPayments ↔ CoinGate) за абстракцией.
- (−) Нет нативных подписок — период/продление держим сами (сложнее, чем Stripe subscriptions).
- (−) Крипто-волатильность/частичные оплаты/недоплаты — обрабатывать статусы `partially_paid`, `expired`.
- Влияет на: **task-010** (rewrite: Stripe → NOWPayments), roadmap Фаза 3, high-level §1.
