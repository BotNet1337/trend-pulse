---
id: TASK-009
title: Alert delivery — Telegram Bot API + webhook (notifier, Celery dispatch, idempotent, retried)
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: ""    # set by executor at ship time
branch: ""             # set by executor at ship time
tags: [backend, alerts, notifier, telegram, webhook, celery, delivery, ssrf]
---

# TASK-009 — Alert delivery (Telegram Bot API · webhook · Celery dispatch)

> Доставить алерт, созданный scorer'ом (task-008), пользователю в выбранный канал: `alerts/notifier.py` форматирует сообщение как в overview (🔥 Viral alert), две backend-реализации за общим интерфейсом — Telegram Bot API (дефолт) и HTTP webhook (Team-план), Celery-задача потребляет новые алерты и диспетчит их. Доставка идемпотентна (один алерт — одна отправка), ретраится с backoff на transient-ошибках, фиксирует статус доставки на строке алерта.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon. Это последний шаг критического пути «до первого сигнала» (roadmap: 001 → 002 → 005 → 006 → 007 → 008 → **009**): scorer (task-008) уже создаёт строку `alert` при `score > threshold` юзера и совпадении темы; здесь мы доводим сигнал до пользователя.

Доставка описана в overview §3 (User Journey шаг 4–5: «Настройка доставки — Telegram Bot и/или Webhook URL» → «Получение сигналов в реальном времени»), §4 (раздел «Доставка алертов» с двумя вариантами и JSON-payload webhook'а), §6 (матрица тарифов: Telegram Bot доступен всем, Webhook — Pro/Team, API access — Team). Архитектурно `alerts (notifier)` — отдельный доменный модуль, потребляющий выход `scorer` (high-level-architecture §3 C4-L2, §4 шаг 5 «Deliver»).

Зависит от: **task-008** (scorer создаёт строки `alert`, на которые мы вешаем статус доставки) и **task-003** (auth даёт пользователя и его delivery-config: bot-токен / webhook URL). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md).

## Goal

Когда scorer создал alert, новый алерт автоматически доставляется в настроенные пользователем каналы: сообщение уходит в Telegram-бот пользователя (его токен) в формате overview и/или webhook получает POST с JSON-payload. Доставка идемпотентна (повторный запуск задачи не шлёт дубликат), на transient-сбоях ретраится с экспоненциальным backoff, после исчерпания попыток алерт помечается `failed`; на успехе — `delivered`. Webhook-URL валидируется против SSRF. Всё прогоняется через `make ...`. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения приняты по дефолтам overview/architecture; все обратимы. -->
- Q: Интерфейс доставки? → A: маленький `DeliveryBackend`-протокол с одним методом `send(alert, target) -> DeliveryResult` → Decision: две реализации `TelegramBotBackend` (дефолт) и `WebhookBackend` за общим протоколом (CONVENTIONS: cross-module через service-интерфейсы; overview §4 — два варианта, оба активируемы одновременно). Rationale: добавление будущих каналов (Slack native, email) не трогает диспетчер.
- Q: Чем слать в Telegram — python-telegram-bot или httpx? → A: **httpx** прямой вызов Bot API (`POST https://api.telegram.org/bot<token>/sendMessage`) → Decision: без тяжёлой SDK-зависимости; httpx уже в async-стеке, легко мокать в unit. Rationale: нужен один метод, не весь bot-framework.
- Q: Как notifier получает новые алерты? → A: **Celery-задача `dispatch_alert(alert_id)`** → Decision: scorer (task-008) на создании алерта enqueue'ит `dispatch_alert.delay(alert_id)`; задача читает строку, резолвит delivery-config юзера, шлёт через нужные backend'ы (CONVENTIONS: Celery-аргументы JSON-serializable — передаём `alert_id`, не ORM-объект).
- Q: Идемпотентность? → A: статус-поле + проверка перед отправкой → Decision: на строке `alert` поля `delivery_status` (`pending|delivered|failed`) и `delivered_at`; `dispatch_alert` — no-op, если статус уже `delivered`. Rationale: at-least-once Celery-доставка → нужна защита от дублей (overview §5 multi-tenancy: один алерт одного юзера). Поля добавляются миграцией здесь (расширение модели task-002), не новой таблицей.
- Q: Ретраи? → A: Celery `autoretry_for` transient-ошибок + backoff → Decision: ретраим только transient (network/5xx/Telegram 429), не на 4xx-конфиг-ошибках (битый токен/URL) и не на SSRF-reject; `max_retries` + `retry_backoff` (экспоненциально), после исчерпания → `delivery_status='failed'`. Time/limits — именованные константы/настройки (CONVENTIONS: no magic literals).
- Q: Формат сообщения? → A: как в overview §1 пример → Decision: `format_alert_message(alert) -> str` — чистая функция, RED-якорь AC1; webhook-payload — отдельная чистая функция `build_webhook_payload(alert) -> dict` ровно по схеме overview §4 (`event, topic, title, score, channels_count, first_seen, velocity`).
- Q: Тарифные ограничения (webhook = Pro/Team)? → A: gating по плану → Decision: webhook-backend выбирается только если у юзера plan ∈ {Pro, Team} И задан webhook URL; иначе шлём только Telegram. Жёсткий enforcement лимитов плана — task-010; здесь — простая проверка наличия/доступности канала.
- Q: SSRF на user-supplied webhook URL? → A: **да, валидируем (security 5.5 applicable)** → Decision: `validate_webhook_url(url)` — только `https` (не `http`/`file`/`gopher`), резолв хоста с блокировкой приватных/loopback/link-local/metadata-диапазонов (RFC1918, `127.0.0.0/8`, `::1`, `169.254.0.0/16`, `169.254.169.254`, `0.0.0.0`), запрет редиректов на внутренние адреса. Rationale: payload летит на произвольный пользовательский URL — классический SSRF-вектор.

## Scope
> **Раскладка:** трогаем **только `backend/`** (модуль `alerts/` + одно миграционное расширение строки `alert` из task-002). Никакого UI (история алертов — эпик C, task-009 даёт данные/статусы).

- **Touch ONLY (создать/изменить):**
  - `apps/trendPulse/backend/src/trendpulse/alerts/__init__.py` — публичная поверхность модуля (`dispatch_alert`, `format_alert_message`, протокол `DeliveryBackend`).
  - `apps/trendPulse/backend/src/trendpulse/alerts/notifier.py` — оркестратор доставки: резолв delivery-config юзера, выбор backend'ов, идемпотентная отправка, запись статуса.
  - `apps/trendPulse/backend/src/trendpulse/alerts/formatting.py` — чистые функции `format_alert_message(alert) -> str` (overview §1) и `build_webhook_payload(alert) -> dict` (overview §4 JSON).
  - `apps/trendPulse/backend/src/trendpulse/alerts/backends.py` — `DeliveryBackend`-протокол + `TelegramBotBackend` (httpx → Bot API `sendMessage`) + `WebhookBackend` (httpx POST JSON).
  - `apps/trendPulse/backend/src/trendpulse/alerts/security.py` — `validate_webhook_url(url)` (SSRF-guard: scheme/host allow-list, блок внутренних диапазонов).
  - `apps/trendPulse/backend/src/trendpulse/alerts/tasks.py` — Celery-задача `dispatch_alert(alert_id)` (autoretry + backoff), регистрация в `celery_app`.
  - `apps/trendPulse/backend/src/trendpulse/alerts/errors.py` — доменные ошибки (`TransientDeliveryError`, `PermanentDeliveryError`, `WebhookValidationError`).
  - **Изменить (расширение модели task-002):** `apps/trendPulse/backend/src/trendpulse/storage/models.py` — добавить на строку `alert` поля `delivery_status` (enum `pending|delivered|failed`, default `pending`) и `delivered_at` (nullable timestamp); новая Alembic-миграция `backend/migrations/versions/*_alert_delivery_status.py`.
  - `apps/trendPulse/backend/tests/unit/alerts/test_formatting.py` (AC1 RED-якорь), `tests/unit/alerts/test_backends.py`, `tests/unit/alerts/test_security.py`, `tests/unit/alerts/test_notifier_idempotency.py`, `tests/integration/test_alert_delivery.py` (маркер `integration`), `tests/unit/alerts/__init__.py`.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме обновления `tasks-index.md` на ship), `landing/**`, `frontend/**`. Не трогать `scorer/` логику (task-008) кроме согласованной точки enqueue `dispatch_alert.delay(alert_id)`; не трогать `collector/`, `pipeline/`. Не реализовывать billing-enforcement лимитов плана (task-010) — только проверка доступности канала.
- **Blast radius:** потребитель выхода `scorer` (task-008) — добавляем enqueue на создании алерта. Расширяем строку `alert` модели task-002 (новые nullable/default-поля — обратносовместимо). Задаёт контракт delivery-config (где notifier читает bot-токен/webhook URL из настроек юзера, заданных через task-003/004) и формат webhook-payload, потребляемый внешними сервисами и frontend-историей (эпик C).

## Acceptance Criteria
- [ ] **AC1 — форматтер сообщения (RED-якорь).** Given объект alert (topic `crypto`, title `"Bitcoin ETF approval"`, score 94, 47 каналов, first_seen 14:02), When `format_alert_message(alert)`, Then строка содержит `🔥 Viral alert [crypto]`, заголовок в кавычках, `Score: 94`, `47 каналов`, `first seen 14:02` (формат overview §1). Тест пишется ПЕРВЫМ и падает (RED).
- [ ] **AC2 — Telegram-доставка.** Given alert + юзер с bot-токеном, When `dispatch_alert(alert_id)`, Then в Telegram Bot API уходит `sendMessage` с отформатированным текстом на нужный `chat_id` (Bot API замокан в unit; реальный вызов — в behavioral, если есть креды).
- [ ] **AC3 — webhook-доставка.** Given alert + юзер плана Pro/Team с валидным `https` webhook URL, When `dispatch_alert(alert_id)`, Then на URL уходит POST с JSON-payload ровно по схеме overview §4 (`event=viral_alert, topic, title, score, channels_count, first_seen, velocity`).
- [ ] **AC4 — идемпотентность (без дублей).** Given alert уже в статусе `delivered`, When `dispatch_alert(alert_id)` вызвана повторно, Then ни одной новой отправки не происходит (no-op), статус остаётся `delivered`.
- [ ] **AC5 — ретрай → failed.** Given transient-сбой backend'а (network/5xx/429), When `dispatch_alert` исчерпала `max_retries` с backoff, Then алерт помечается `delivery_status='failed'`; на 4xx/конфиг-ошибке ретраев нет (сразу permanent).
- [ ] **AC6 — статус на успехе.** Given успешная доставка хотя бы в один настроенный канал, When задача завершилась, Then `delivery_status='delivered'` и `delivered_at` проставлены.
- [ ] **AC7 — SSRF-guard webhook URL.** Given webhook URL на внутренний/loopback/link-local адрес (`http://127.0.0.1`, `https://169.254.169.254`, RFC1918, `file://`), When валидация перед отправкой, Then `WebhookValidationError`, POST не выполняется, алерт не падает в бесконечный ретрай (permanent).

## Plan
0. Executor фиксирует `baseline_commit`, ветка `gsd/phase-9-alert-delivery`. Свериться с фактической формой строки `alert` из task-002 и delivery-config юзера из task-003/004.
1. `tests/unit/alerts/test_formatting.py` — RED-якорь AC1: `format_alert_message(alert)` по примеру overview §1. Прогнать — должен упасть.
2. `alerts/formatting.py` — минимальная реализация `format_alert_message` (GREEN), затем `build_webhook_payload(alert) -> dict` строго по схеме overview §4.
3. `alerts/errors.py` — `TransientDeliveryError`, `PermanentDeliveryError`, `WebhookValidationError`.
4. `alerts/security.py` — `validate_webhook_url(url)`: scheme allow-list (`https`), резолв хоста и блок приватных/loopback/link-local/metadata-диапазонов; тесты `test_security.py` (AC7).
5. `alerts/backends.py` — протокол `DeliveryBackend.send(alert, target) -> DeliveryResult`; `TelegramBotBackend` (httpx POST `…/bot<token>/sendMessage`, маппинг 429/5xx → transient, 4xx → permanent); `WebhookBackend` (validate_webhook_url → httpx POST JSON, без редиректов на внутренние). Тесты `test_backends.py` (AC2/AC3) с моком httpx.
6. `alerts/notifier.py` — `deliver(alert)`: idempotency-guard (если `delivered` → no-op), резолв delivery-config (bot-токен / webhook URL + план), выбор backend'ов (Telegram всем; webhook только Pro/Team + валидный URL), отправка, запись `delivery_status`/`delivered_at`. Тест `test_notifier_idempotency.py` (AC4/AC6).
7. `alerts/tasks.py` — Celery `dispatch_alert(alert_id)` с `autoretry_for=(TransientDeliveryError,)`, `retry_backoff`, `max_retries`; на исчерпании → `failed` (AC5). Зарегистрировать в `celery_app`. В task-008-точке создания алерта добавить `dispatch_alert.delay(alert_id)`.
8. `storage/models.py` — добавить `delivery_status`/`delivered_at` на строку `alert`; Alembic-миграция `*_alert_delivery_status.py` (default `pending`, nullable `delivered_at`).
9. `tests/integration/test_alert_delivery.py` (маркер `integration`) — end-to-end через локальный фейковый webhook-сервер + замоканный Bot API: alert → dispatch → POST получен / sendMessage вызван / статус `delivered`.
10. Прогнать `make ci-fast`; затем `make up-d` + `make migrate`; проверить AC2–AC7 вживую (behavioral); Telegram реальный — если заданы тестовые креды в `.env`.

## Invariants
- **Cross-module через service-интерфейсы.** `scorer` (task-008) общается с `alerts` только через публичный `dispatch_alert` / enqueue; notifier читает delivery-config через публичную поверхность `api`/`storage`, не лезет во внутренности других модулей.
- **Идемпотентность доставки.** Один alert ⇒ максимум одна успешная отправка в канал; повторный `dispatch_alert` при `delivered` — строгий no-op (Celery at-least-once).
- **Celery-аргументы JSON-serializable** — передаём `alert_id`, не ORM-объект; `dispatch_alert` сам читает строку.
- **No magic literals** — `max_retries`, `retry_backoff`, HTTP-timeout, Bot API base URL, заблокированные CIDR-диапазоны — именованные константы / pydantic-settings; время в секундах.
- **Полные type hints, без `Any`/`# type: ignore`** — `mypy` зелёный; внешние данные (ответ Bot API, webhook-таргет) валидируются на границе.
- **Чистые форматтеры** — `format_alert_message` / `build_webhook_payload` не мутируют alert, без побочных эффектов (детерминированы → легко тестировать).
- **Секреты только из env/настроек юзера** — bot-токен и webhook URL не логируются и не попадают в payload; никаких хардкод-токенов. В логах — агрегаты/статусы, не содержимое сообщений (overview §7).
- **Ретрай-политика по типу ошибки** — transient ретраятся с backoff, permanent (4xx/битый конфиг/SSRF-reject) — сразу `failed`, без зацикливания.

## Edge cases
- Битый/отозванный bot-токен → Bot API 401/403 (permanent) → не ретраить, пометить `failed`, не ронять весь dispatch (второй канал может пройти).
- Telegram 429 `Too Many Requests` (`retry_after`) → transient, уважать `retry_after` в backoff.
- Webhook-URL резолвится в приватный/metadata-адрес (`169.254.169.254`) → `WebhookValidationError` (permanent), POST не выполняется.
- Webhook отвечает 3xx-редиректом на внутренний адрес → редиректы запрещены / повторно валидируются (обход SSRF-guard).
- Webhook-эндпоинт висит / таймаутит → transient timeout, ретрай с backoff, затем `failed`.
- Юзер на Free-плане с заданным webhook URL → webhook-канал пропускается (gating), шлём только Telegram.
- Юзер без единого настроенного канала → нет доставки; статус остаётся `pending` (или явный `failed` с причиной «no channel»), но задача не падает в ретрай.
- Дубль-enqueue `dispatch_alert` (scorer перезапустил тик) → idempotency-guard по `delivery_status` спасает от двойной отправки.
- Параллельный запуск двух `dispatch_alert` на один `alert_id` → запись статуса под conditional update (compare-and-set на `pending`), чтобы не разойтись.

## Test plan
- **unit:** `test_formatting.py` (AC1, RED первым — `format_alert_message`/`build_webhook_payload` по overview §1/§4); `test_backends.py` (AC2/AC3 — Telegram `sendMessage` и webhook POST через мок httpx, маппинг 429/5xx→transient, 4xx→permanent); `test_security.py` (AC7 — SSRF allow/deny таблица: https-public ok; http/file/loopback/RFC1918/link-local/metadata → reject); `test_notifier_idempotency.py` (AC4/AC6 — `delivered` ⇒ no-op; успех ⇒ `delivered`+`delivered_at`).
- **integration (по требованию, маркер `integration`):** `test_alert_delivery.py` — локальный фейковый webhook-сервер + замоканный Bot API; alert-строка в БД → `dispatch_alert(alert_id)` → POST получен с корректным payload / `sendMessage` вызван / `delivery_status='delivered'`; transient-сбой → ретраи → `failed`.
- **runtime/behavioral (G2):** `make up-d` + `make migrate` → создать тестовый alert → проверить AC2 (Telegram, реальный bot-токен из `.env` если есть), AC3 (webhook на локальный приёмник), AC5 (заглушить приёмник → `failed`), AC4 (повторный dispatch → нет дубля), AC7 (webhook на `127.0.0.1` → reject).

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
- [ ] 5.5 security (applicable: SSRF/webhook + secrets — validate scheme/host, block internal/link-local ranges, no token/secret leakage in payload or logs, bot-token via env)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по overview §3/§4/§6 и high-level-architecture §3/§4; зависит от task-008 (scorer создаёт строки alert) и task-003 (auth/delivery-config); security 5.5 applicable — SSRF на user-supplied webhook URL + secret handling)
