---
id: TASK-027
title: Subscription renewal/expiry notifications — Beat-задача check_expiring_subscriptions (Telegram/email, идемпотентно)
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-027-subscription-renewal-notifications"
tags: [epic-d, backend, billing, retention]
---

# TASK-027 — Subscription renewal/expiry notifications (Epic D)

> Реализовать требование [ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md) §4 (пока не сделано): Beat-задача `check_expiring_subscriptions` находит `Subscription.expires_at` в окне (за 7/3/1 день — named constants) и шлёт уведомление **о продлении** (НЕ viral-alert — отдельный notification-тип) через notifier (Telegram) И/ИЛИ email (templates [task-025](./task-025-templates-email-service.md)). **Идемпотентно** — одно уведомление не шлётся повторно (флаг/лог отправленных). AC: подписка с `expires_at` в окне → уведомление отправлено один раз; истёкшая → effective Free (уже есть в `effective_plan`); integration: near-expiry → задача шлёт. Security: tenant-scoped.

## Context

TrendPulse billing ([ADR-004](../architecture/adr-004-crypto-billing-nowpayments.md), [task-010](./task-010-billing-nowpayments.md)): крипто-оплата (NOWPayments). `Subscription` (`backend/src/storage/models/subscriptions.py`) имеет `expires_at`; `effective_plan` (`backend/src/billing/limits.py`) при истечении откатывает пользователя на Free. ADR-004 §4 требует **уведомлять пользователя о приближающемся истечении** (renewal-нудж) — этого пока НЕТ: пользователь молча проваливается на Free после expiry. Это retention-фича (вернуть платящего до того, как он потеряет доступ).

Инфраструктура для отправки уже есть: Celery Beat (`backend/src/scheduler.py` `beat_schedule`, `celery_app.py` — broker/backend Redis, worker подписан на `celery,batch,score:global`; unrouted-задачи падают на `celery`-очередь); Telegram-доставка alert'ов (`backend/src/alerts/notifier.py`, task-009); email-инфра (templates `/render` + SMTP + mailpit, task-025). Уведомление о продлении — это НОВЫЙ notification-тип (не viral-alert): не должен идти по alert-pipeline, отдельная задача + отдельный текст/шаблон.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — no magic literals (окна 7/3/1 день — named constants), task args JSON-serializable (id, не ORM), tenant-scoped, full type hints, идемпотентность (не спамить).

## Goal

После задачи: (1) Beat-задача `check_expiring_subscriptions` периодически (интервал из settings) сканирует подписки, чьи `expires_at` попадают в окна-напоминания (за 7/3/1 день — named constants); для каждой шлёт **renewal-уведомление** (отдельный notification-тип, не viral-alert) через notifier (Telegram) и/или email (task-025) с CTA на продление. (2) Идемпотентность: каждое окно-уведомление для подписки шлётся РОВНО ОДИН раз (трекинг отправленных — флаг на подписке/таблица-лог/идемпотентный ключ). (3) Истёкшая подписка → effective Free (поведение `effective_plan` уже есть, не дублируем). (4) Уведомления tenant-scoped (только владельцу подписки). DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по ADR-004 §4 + task-009/010/025; обратимы. -->
- Q: Когда уведомлять? → A: ADR-004 §4 → Decision: окна за **7/3/1 день** до `expires_at` — named constants (`RENEWAL_REMINDER_DAYS = (7, 3, 1)`), не magic literal. Задача ловит подписки, у которых `expires_at` попадает в текущее «срабатывание» каждого окна.
- Q: Канал доставки? → A: Telegram уже есть, email добавлен task-025 → Decision: слать через notifier (Telegram, reuse task-009 доставки) И/ИЛИ email (render renewal-шаблон через task-025 + SMTP). Минимум — один канал; предпочтительно оба, если у пользователя заданы. Выбор/наличие канала — по delivery-config пользователя.
- Q: Это viral-alert? → A: НЕТ → Decision: отдельный notification-тип — НЕ идёт по alert-pipeline (scorer/dispatch_alert), не пишется в таблицу `alerts`, отдельный текст/шаблон («ваша подписка Pro истекает через N дней — продлите»). Переиспользуем только транспорт (Telegram send / email send), не alert-семантику.
- Q: Как обеспечить идемпотентность? → A: Beat тикает периодически → Decision: трекинг отправленных уведомлений — например `Subscription.last_reminder_sent_window` (какое окно уже отправлено) ИЛИ отдельная таблица/лог `subscription_reminders(subscription_id, window_days, sent_at)` с уникальным ключом `(subscription_id, window_days)`. Перед отправкой проверяем «не слали ли уже это окно». Минимально-инвазивно: флаг/поле на подписке предпочтительнее новой таблицы, если хватает.
- Q: Окно «попадания» при дискретном тике? → A: Beat тикает раз в N → Decision: ловим подписки, где `expires_at - now` пересекло границу окна с прошлого тика (или `<= window_days и не отправлено для этого окна`). Идемпотентный ключ гарантирует один раз даже при нескольких тиках в окне.
- Q: Что с уже истёкшими? → A: `effective_plan` уже откатывает на Free → Decision: НЕ дублируем downgrade-логику; задача — только напоминания ДО истечения. Опц.: одно «подписка истекла» post-expiry уведомление (если в скоупе) — тоже идемпотентно.
- Q: Routing задачи? → A: celery_app include → Decision: новая задача в `billing/tasks.py` (или `pipeline`/новый модуль), добавить в `celery_app.include`; unrouted → падает на `celery`-очередь, которую worker уже слушает (как dispatch_alert/purge — без compose-изменений). Beat-entry в `scheduler.py` с интервалом из settings.

## Scope
> **backend** billing/retention-добавка: новая Beat-задача `check_expiring_subscriptions` + renewal notification (Telegram/email reuse) + идемпотентность-трекинг + Beat-entry. Alert-pipeline (scorer/dispatch) и `effective_plan`-downgrade НЕ трогаем (renewal — отдельный тип).

- **Touch ONLY (создать/изменить):**
  - `backend/src/billing/tasks.py` — **новый** (или расширить): Celery-задача `check_expiring_subscriptions` — query подписок в окне, идемпотентная отправка renewal-уведомления per-окно.
  - `backend/src/billing/constants.py` — **новый/расширить**: `RENEWAL_REMINDER_DAYS = (7, 3, 1)`, имена задачи/окон (no magic literals).
  - `backend/src/billing/notifications.py` — **новый**: формирование renewal-сообщения (Telegram-текст / email через `notifications/email` task-025 renewal-шаблон), выбор канала по delivery-config пользователя.
  - `backend/src/storage/models/subscriptions.py` — добавить трекинг идемпотентности (поле `last_reminder_window`/`reminded_windows` ИЛИ новая таблица `subscription_reminders`) + Alembic-миграция.
  - `backend/alembic/versions/*` — **новая** миграция (поле/таблица трекинга).
  - `backend/src/scheduler.py` — Beat-entry `check_expiring_subscriptions` (интервал из settings).
  - `backend/src/celery_app.py` — добавить `billing.tasks` в `include`.
  - `backend/src/config.py` — `renewal_check_interval_seconds` (default), при необходимости.
  - `templates/src/templates/auth/` или новый `templates/src/templates/billing/renewal.tsx` — **renewal email-шаблон** (если email-канал; через task-025 сервис).
  - `backend/tests/unit/test_renewal_windows.py` — окна 7/3/1, идемпотентность (per-окно один раз), tenant-scope.
  - `backend/tests/integration/test_renewal_notifications.py` — near-expiry подписка → уведомление отправлено один раз (Telegram mock / email→mailpit).
  - `docs/tasks/tasks-index.md` — на ship (НЕ в этой задаче-планировании).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/scorer/**` и alert-pipeline (`pipeline/**`, `alerts/tasks.py::dispatch_alert` — renewal НЕ идёт по alert-пути), `backend/src/billing/limits.py::effective_plan` (downgrade уже есть — не дублируем), `billing/gateway/**` NOWPayments (платёж не трогаем), `billing/webhook.py` IPN. Не слать renewal как viral-alert; не писать в таблицу `alerts`.
- **Blast radius:** новая Beat-задача (периодический скан подписок) + Alembic-миграция (поле/таблица трекинга — additive). Reuse транспортов: Telegram (task-009 notifier) + email (task-025). Новый notification-тип не пересекается с alert-pipeline. Идемпотентность критична — иначе спам пользователю при каждом тике. Worker слушает `celery`-очередь (unrouted) — без compose-изменений.

## Acceptance Criteria
- [ ] **AC1 — near-expiry подписка получает renewal-уведомление один раз (failing-test anchor).** Given подписка с `expires_at` в окне (напр. за 3 дня), When отрабатывает `check_expiring_subscriptions`, Then renewal-уведомление отправлено владельцу (Telegram и/или email) РОВНО один раз; повторный тик в том же окне — НЕ шлёт повторно. Тест пишется ПЕРВЫМ (RED).
- [ ] **AC2 — окна 7/3/1 день (named constants).** Given подписки с `expires_at` за 7/3/1 день, When задача отрабатывает, Then уведомление шлётся на каждой границе окна; окна — named constants (`RENEWAL_REMINDER_DAYS`), не magic literal; подписки вне окон — пропускаются.
- [ ] **AC3 — отдельный notification-тип (не viral-alert).** Given renewal-уведомление, When оно формируется, Then это НЕ viral-alert: не идёт через scorer/dispatch_alert, не пишется в таблицу `alerts`; текст/шаблон — про продление подписки с CTA.
- [ ] **AC4 — идемпотентность при повторных тиках.** Given уведомление за окно уже отправлено, When задача тикает снова в том же окне, Then повтор НЕ шлётся (трекинг per `(subscription, window)`); следующее (более близкое) окно шлётся отдельно один раз.
- [ ] **AC5 — истёкшая → effective Free (без дублирования).** Given подписка истекла, When проверяется план, Then `effective_plan` (task-010, уже есть) откатывает на Free; задача renewal НЕ дублирует downgrade-логику (только напоминает ДО).
- [ ] **AC6 — tenant-scoped доставка.** Given несколько пользователей, When шлются уведомления, Then каждое уходит ТОЛЬКО владельцу подписки (Telegram chat_id/email из его delivery-config); нет утечки между арендаторами.
- [ ] **AC7 — поведенческая (G2) через стек.** Given `make up` (+ сид подписки с near-expiry `expires_at`), When отрабатывает Beat/ручной триггер задачи, Then уведомление наблюдаемо (email→mailpit API / Telegram-send mock-лог); повторный запуск не дублирует; артефакты сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-027-subscription-renewal-notifications`.
1. **RED:** `test_renewal_notifications.py` — near-expiry подписка → уведомление один раз, повтор не шлёт. Падает (задачи нет). AC1-якорь.
2. `billing/constants.py` (`RENEWAL_REMINDER_DAYS=(7,3,1)`) + миграция трекинга (`last_reminder_window`/таблица) + `billing/tasks.py::check_expiring_subscriptions` (query окна, идемпотентная отправка) + `billing/notifications.py` (renewal-текст Telegram / email через task-025). `make ci-fast` зелёный.
3. Beat-entry в `scheduler.py` (интервал из settings) + `billing.tasks` в `celery_app.include`.
4. `test_renewal_windows.py` (окна 7/3/1, идемпотентность per-окно, tenant-scope), renewal email-шаблон. **GREEN** локально.
5. **G2:** `make up` (+сид near-expiry подписки); триггер задачи → уведомление в mailpit/Telegram-mock; повтор не дублирует (AC7).
6. Security-проверка: tenant-scope доставки (chat_id/email только владельца).
7. Обновить `tasks-index.md` на ship.

## Invariants
- **Идемпотентность per `(subscription, window)`** — каждое окно-напоминание шлётся РОВНО один раз; трекинг (поле/таблица с уникальным ключом) проверяется перед отправкой; повторные Beat-тики не спамят.
- **Renewal ≠ viral-alert** — отдельный notification-тип; НЕ идёт по scorer/dispatch_alert, НЕ пишется в `alerts`; reuse только транспорта (Telegram send / email send).
- **No magic literals** — окна 7/3/1 (`RENEWAL_REMINDER_DAYS`), интервал задачи, имена задачи/окон — named constants/settings.
- **Tenant-scoped** — уведомление уходит только владельцу подписки (его chat_id/email); query фильтрует по подписке→user; нет cross-tenant утечки.
- **Не дублировать downgrade** — `effective_plan` (task-010) уже откатывает на Free при expiry; задача только напоминает ДО, не трогает план-логику.
- **Task args JSON-serializable** — передавать `subscription_id`/`user_id`, не ORM-объекты (CONVENTIONS/celery_app); full type hints.
- **Best-effort доставка** — сбой канала (Telegram/SMTP) не валит задачу для остальных подписок; ошибка логируется (без PII), идемпотентность-флаг ставится только при успешной отправке (иначе повтор на след. тике).

## Edge cases
- Beat тикнул несколько раз внутри одного окна → идемпотентный ключ `(subscription, window)` гарантирует один раз (AC4).
- Подписка отменена/уже Free → не слать renewal (только активным платным подпискам с будущим `expires_at`).
- `expires_at` ровно на границе окна / таймзоны → консистентное сравнение в UTC; не пропустить и не задвоить.
- У пользователя не задан ни Telegram chat_id, ни email → пропустить (нечего слать) либо лог «канал не настроен», без падения.
- Сбой отправки (Telegram/SMTP down) → НЕ ставить «отправлено»-флаг (чтобы повторить на след. тике), задача не падает целиком, обрабатывает остальные.
- Подписка с `expires_at` в прошлом (уже истекла) → renewal-напоминания не слать (это пройденные окна); downgrade — у `effective_plan`.
- Большое число подписок → query с фильтром по окну (индекс по `expires_at`), не сканировать всё; батчить отправку.
- Изменение `expires_at` (продление) после отправки напоминания → новые окна относительно нового `expires_at` (трекинг привязан к окну/expires; при продлении напоминания пересчитываются для новой даты).

## Test plan
- **unit:** `test_renewal_windows.py` — попадание в окна 7/3/1 (named constants), вне окна — пропуск; идемпотентность (один раз per окно, повтор no-op); tenant-scope (адресат = владелец); сбой канала → флаг не ставится.
- **integration:** `test_renewal_notifications.py` — near-expiry подписка (сид) → `check_expiring_subscriptions` шлёт один раз (Telegram mock / email→mailpit); повтор не дублирует (AC1/AC4); истёкшая → effective Free неизменно (AC5); renewal не пишется в `alerts` (AC3).
- **runtime/behavioral (G2):** `make up` (+сид подписки с `expires_at` near-expiry) → ручной триггер/Beat задачи → уведомление в mailpit API (email) или Telegram-send-mock-лог; повторный запуск не дублирует; артефакт (JSON mailpit / лог).
- **security:** tenant-scope доставки (chat_id/email строго владельца); PII не в логах; renewal-текст без утечки чужих данных.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-027-subscription-renewal-notifications"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-016/017 и контексту Epic D: реализовать ADR-004 §4 renewal-уведомления (пока не сделано). Beat-задача `check_expiring_subscriptions` сканирует `Subscription.expires_at` в окнах за 7/3/1 день (named constants), шлёт отдельный renewal-notification-тип (НЕ viral-alert, не через scorer/dispatch_alert, не в таблицу alerts) через Telegram (reuse task-009 notifier) и/или email (task-025). Идемпотентно — один раз per (subscription, window) через флаг/таблицу-трекинг + Alembic. effective_plan-downgrade (task-010) не дублируем. deps: 010 (billing/Subscription/effective_plan), 009 (Telegram-доставка/notifier), 025 (email-инфра). Security: tenant-scoped доставка. locate+plan выполнены этим планированием — executor стартует с «3 do».)

### Подсказки исполнителю (initial)
- **Окна:** `RENEWAL_REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)` в `billing/constants.py`. Query: подписки, где `expires_at` между `now` и `now + max(window)` дней И конкретное окно ещё не отправлено.
- **Идемпотентность (минимально-инвазивно):** предпочесть поле на `Subscription` — напр. `reminded_windows: list[int]`/`last_reminder_window: int | None` (какое самое близкое окно уже отправлено). Если нужен аудит — таблица `subscription_reminders(subscription_id, window_days, sent_at)` с `UniqueConstraint(subscription_id, window_days)`. Флаг ставить ТОЛЬКО после успешной отправки.
- **Задача:** в `billing/tasks.py`, имя-константа; добавить в `celery_app.include=[... "billing.tasks"]`; unrouted → очередь `celery` (worker уже слушает, как dispatch_alert/purge). Beat-entry в `scheduler.py` `beat_schedule` с `schedule=float(_settings.renewal_check_interval_seconds)`.
- **Канал:** `billing/notifications.py` — собрать сообщение; Telegram через reuse `alerts/notifier.py` send-примитива (chat_id из delivery-config пользователя, НЕ alert-семантика); email через `notifications/email.send_templated_email("renewal", {...})` (task-025), renewal-шаблон в templates-сервисе. Слать по доступным каналам; нет канала → skip+log.
- **tenant-scope:** адресат строго `subscription.user` (chat_id/email из его delivery-config); query join подписка→user.
- **JSON args:** задача принимает/передаёт ids, не ORM (CONVENTIONS). Внутри — открыть сессию, прочитать, отправить, отметить флаг в одной транзакции (или отметить после успешной отправки).
- **G2:** сид подписки `expires_at = now + 3 days`; триггернуть задачу (celery call/ручной); проверить mailpit API (email) или Telegram-mock-лог; запустить повторно — ассертить отсутствие дубля.
