---
id: TASK-069
title: Lifecycle-письма — welcome после верификации, weekly digest, win-back (+ unsubscribe)
status: review         # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "650663d"
branch: "task/069-email-lifecycle"
tags: [email, lifecycle, notifications, templates, beat, retention, migration]
---

# TASK-069 — Lifecycle-письма: welcome, weekly digest, win-back

> Сейчас письма только транзакционные (verify/reset — TASK-026, renewal — TASK-027).
> Добавить активационно-удерживающий контур: welcome после верификации (CTA «подключи
> пак»), еженедельный digest «top signals недели» по пакам юзера, win-back при 14д
> неактивности — всё с обязательным unsubscribe и частотными лимитами.

## Context

Инфраструктура писем уже есть и проверена тремя транзакционными потоками:

- **Транспорт:** `backend/src/notifications/email.py::send_templated_email`
  (`:125-148`) — рендер через node templates-сервис (`render_email` → POST
  `{templates_service_url}/render/{template}`) + SMTP (`send_email`, ошибки
  `EmailRenderError`/`EmailSendError`, без vendor lock-in — TASK-025).
- **Auth-хуки:** `backend/src/api/auth/users.py` — `UserManager.on_after_register`
  (`:89`), `on_after_request_verify` (`:182`, шлёт `auth/verify-email`),
  `_send_email_best_effort` (`:240-264`) — thread-dispatch, ошибки логируются без
  PII, поток не блокируется.
- **Beat-паттерн домена:** `backend/src/billing/tasks.py::check_expiring_subscriptions`
  (TASK-027) — скан окна, идемпотентность через `Subscription.last_reminder_window`
  (миграция 0009), письмо через `billing/notifications.py::send_renewal_reminder`
  (`:32-83`); расписание — `backend/src/scheduler.py:53`
  (`renewal_check_interval_seconds`, интервалы из настроек, float-секунды).
- **Templates-сервис:** реестр `templates/templates.json` + tsx в
  `templates/src/templates/`. Шаблон **`auth/welcome` уже существует**
  (`templates/templates.json:41-57`, props `userName`+`dashboardUrl`;
  `templates/src/templates/auth/welcome.tsx`) — но в backend НЕ подключён
  (grep «welcome» по `backend/src/` пуст; хук `on_after_verify` не реализован).

Данные для digest/win-back: `Alert.delivered_at`/`delivery_status`
(`backend/src/storage/models/alerts.py:39,42`), `Watchlist.pack_slug`
(`backend/src/storage/models/watchlists.py:38`), `User.is_verified`
(fastapi-users base). Активационная воронка — TASK-050. «Открытий» письма/алерта
мы не трекаем (доставка в Telegram) — суррогат активности см. Discussion.

## Goal

После верификации юзер получает welcome с CTA на паки; раз в неделю верифицированный
юзер с паками получает digest топ-сигналов своей недели; юзер без доставленных
алертов 14д получает одно win-back; каждое lifecycle-письмо несёт рабочую
unsubscribe-ссылку; неверифицированным и отписавшимся lifecycle-письма не уходят
никогда. DoD = AC.

## Discussion
<!-- durable record. Анти-спам инварианты — ядро задачи. -->
- Q: **Анти-спам инвариант** — границы? → A/Decision: (1) lifecycle-письма
  (welcome/digest/win-back) уходят ТОЛЬКО `is_verified=True` и ТОЛЬКО при
  `lifecycle_emails_opt_out=False`; (2) в каждом lifecycle-письме — явная
  unsubscribe-ссылка (футер) + заголовок `List-Unsubscribe`; (3) транзакционные
  письма (verify/reset/renewal) под opt-out НЕ подпадают — это сервисные
  уведомления, их отключение ломает продукт/биллинг.
- Q: **Частотные лимиты**? → A/Decision: digest ≤ 1 раза в 7 дней
  (`digest_last_sent_at`), win-back ≤ 1 на цикл неактивности и не чаще 1 раза в
  30 дней (`winback_last_sent_at`); welcome — ровно 1 раз (событийный, на
  верификацию). Суммарный потолок не нужен: при соблюдении пер-типовых лимитов
  максимум ~5 lifecycle-писем/месяц.
- Q: Welcome — на регистрацию или на верификацию? → A: на верификацию → Decision:
  реализуем `UserManager.on_after_verify` (штатный хук fastapi-users; на
  регистрацию уже уходит verify-письмо — два письма подряд = спам). Шаблон
  `auth/welcome` готов; `dashboardUrl` → страница паков SPA
  (`frontend_base_url` — `backend/src/config.py:380` + именованная path-константа,
  паттерн `billing/constants.py:22`), CTA-копия «подключи пак» уже в шаблоне/правится
  в tsx при необходимости.
- Q: Digest-контент «top signals недели по пакам юзера» — откуда? → A: из алертов
  юзера → Decision: top-K (K=5) `Alert` юзера за 7д с
  `delivery_status='delivered'`, сорт по `score` DESC; группировка/подпись пака —
  join через `cluster_id` → `Watchlist.pack_slug` юзера. Темы санитизировать
  `textutils.sanitize_topic_label` (compliance §7 — как в trending/cases).
  Пустая неделя (0 алертов) → digest НЕ шлём (письмо без контента = спам).
- Q: Win-back триггер «14д без открытия алертов» — «открытий» нет в данных? → A:
  суррогат → Decision: неактивность = `MAX(Alert.delivered_at)` юзера старше 14д
  (или алертов нет вовсе) при наличии ≥1 watchlist. Порог — настройка
  `winback_inactive_days=14` (pydantic-settings, не magic literal). Контент:
  «ваши паки молчат / посмотрите trending» + CTA. Re-arm: после нового
  `delivered_at` новее `winback_last_sent_at` цикл считается новым.
- Q: Unsubscribe без логина — как подписать токен? → A: без новых зависимостей →
  Decision: `fastapi_users.jwt.generate_jwt/decode_jwt` (уже в стеке) с выделенной
  audience `"trendpulse:unsubscribe"` и существующим `jwt_secret`; payload —
  `{user_id}`, без срока жизни письмо живёт долго → lifetime токена 90д
  (константа). Эндпоинт `GET /v1/email/unsubscribe?token=...` идемпотентно ставит
  `lifecycle_emails_opt_out=True`, отвечает простым HTML/redirect на лендинг;
  невалидный/просроченный токен → 400 error-envelope (TASK-030), без раскрытия
  причин. Поверхность unauth + input ⇒ **стадия 5.5 security обязательна**.
- Q: Расписание — cron или интервал? → A: интервал (паттерн проекта) → Decision:
  один beat-тик `lifecycle-emails-tick` раз в сутки
  (`lifecycle_email_interval_seconds=86400`, по образцу
  `renewal_check_interval_seconds`); внутри тика due-отбор по
  `digest_last_sent_at`/`winback_last_sent_at` — идемпотентно при рестартах,
  точное время суток некритично (паттерн scheduler.py, float-секунды).
- Q: Состояние (`opt_out`, `*_last_sent_at`) — таблица или колонки users? → A:
  колонки → Decision: 3 аддитивные колонки в `users`
  (`lifecycle_emails_opt_out BOOL NOT NULL DEFAULT false`,
  `digest_last_sent_at`/`winback_last_sent_at TIMESTAMPTZ NULL`) — паттерн
  delivery-config полей users (миграция 0004); отдельная таблица = overkill для
  3 полей. Номер миграции — следующий свободный (на момент плана head = 0019;
  TASK-066 ожидаемо займёт 0020 ⇒ здесь, вероятно, **0021** — проверить на do).

## Scope

- **Touch ONLY:**
  - `backend/src/api/auth/users.py` — хук `on_after_verify` → welcome через
    `_send_email_best_effort` (шаблон `auth/welcome`, subject из реестра).
  - `backend/src/notifications/lifecycle.py` — НОВЫЙ: due-отбор (pure-функции
    `is_digest_due`/`is_winback_due`), сбор digest-контента, отправка +
    проставление `*_last_sent_at`; unsubscribe-токен
    (`generate_unsubscribe_token`/`parse_unsubscribe_token`).
  - `backend/src/notifications/tasks.py` — НОВЫЙ: Celery-таск
    `send_lifecycle_emails` (скан юзеров, best-effort per-user, PII не логируем —
    паттерн `billing/tasks.py`).
  - `backend/src/notifications/email.py::send_email/send_templated_email` —
    опциональный параметр `headers: dict[str, str] | None` (для
    `List-Unsubscribe`); поведение без параметра не меняется.
  - `backend/src/scheduler.py` — beat-запись `lifecycle-emails-tick`.
  - `backend/src/config.py` — `lifecycle_email_interval_seconds`,
    `winback_inactive_days`, `digest_top_k`, `digest_period_days` (именованные
    константы-дефолты, env-переопределяемые).
  - `backend/src/api/routes/` — НОВЫЙ роут `email_unsubscribe.py`
    (`GET /email/unsubscribe`), монтаж в `v1_router`
    (`backend/src/api/main.py:264+`); затем `make gen-openapi gen-types`
    (drift-check, `Makefile:220`).
  - `backend/src/storage/models/users.py` — 3 колонки; миграция
    `backend/migrations/versions/00NN_users_lifecycle_emails.py` (NN = следующий
    свободный, ожидаемо 0021).
  - `templates/templates.json` + `templates/src/templates/lifecycle/weekly-digest.tsx`,
    `templates/src/templates/lifecycle/win-back.tsx` — 2 новых шаблона (welcome уже
    есть); во все 3 lifecycle-шаблона — unsubscribe-ссылка в футере
    (`templates/src/components/footer.tsx` — опциональный prop `unsubscribeUrl`).
  - Тесты: `backend/tests/unit/notifications/` (НОВЫЙ пакет),
    `backend/tests/unit/test_scheduler.py`, `backend/tests/integration/`
    (unsubscribe-роут; тик по образцу `test_renewal_notifications.py` /
    `test_email_delivery.py`).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** транзакционные потоки verify/reset (TASK-026), renewal
  (TASK-027 — `billing/notifications.py`, `billing/tasks.py`), SMTP/рендер-ядро
  сверх аддитивного `headers`, alert-доставку (`alerts/`), funnel-агрегацию
  TASK-050 (`analytics/aggregate.py` — читаем таблицы напрямую, не агрегаты),
  fastapi-users роуты, `_bmad/**`, `.claude/**`.
- **Blast radius:** схема `users` (3 аддитивные колонки с дефолтами — читатели не
  ломаются); beat-расписание (+1 entry — изоляция `max_instances`/очередей по
  ADR-002 как у соседей); public API (+1 unauth GET — error-envelope + rate-limit
  обязательны, `api/rate_limit.py`); templates-сервис (+2 шаблона, +1 опц. prop
  футера — существующие рендеры не меняются); объём исходящей почты (лимиты выше).

## Acceptance Criteria

- [x] **AC1 — welcome.** Given юзер завершает верификацию e-mail When срабатывает
  `on_after_verify` Then уходит ровно одно письмо `auth/welcome` с
  `dashboardUrl` на страницу паков; повторная верификация письма не дублирует;
  сбой SMTP не ломает верификацию (best-effort, лог без PII).
- [x] **AC2 — digest.** Given верифицированный юзер с паком и ≥1 delivered-алертом
  за 7д, `digest_last_sent_at` старше 7д (или NULL) When beat-тик Then уходит
  digest с top-K сигналов (sanitize_topic_label, score, pack), проставляется
  `digest_last_sent_at`; повторный тик в тот же день письмо НЕ шлёт.
  Given 0 алертов за 7д Then digest не уходит вовсе.
- [x] **AC3 — win-back.** Given верифицированный юзер с watchlist, у которого
  `MAX(delivered_at)` старше 14д (или алертов нет) и win-back в этом цикле не
  слался When тик Then уходит одно win-back; следующее возможно только после
  новой активности или через 30д.
- [x] **AC4 — unsubscribe.** Given lifecycle-письмо When юзер открывает
  unsubscribe-ссылку (без логина) Then `lifecycle_emails_opt_out=True`,
  повторный клик идемпотентен; When следующий тик Then этому юзеру не уходит НИ
  digest, НИ win-back, но verify/reset/renewal продолжают работать. Невалидный
  токен → 400 без деталей.
- [x] **AC5 — анти-спам.** Given неверифицированный юзер с любыми данными When тик
  Then ему не уходит ничего lifecycle; в отправленных письмах присутствуют
  футер-ссылка и заголовок `List-Unsubscribe`.
- [ ] **AC6 — G2.** `make ci` зелёный (вкл. openapi-drift); живой прогон на стенде:
  тик против реальной БД + mailpit показывает digest/win-back/welcome с рабочей
  unsubscribe-ссылкой.

## Plan

1. RED: unit-тесты pure-логики (`is_digest_due`/`is_winback_due` — окна, opt-out,
  is_verified, re-arm; токен round-trip + tampering) — падают.
2. Миграция `00NN_users_lifecycle_emails` + колонки в `storage/models/users.py`.
3. `notifications/lifecycle.py` (pure-ядро) → GREEN unit.
4. `notifications/email.py` — параметр `headers` (аддитивно, unit `test_email.py`).
5. Welcome: `on_after_verify` в `api/auth/users.py` + integration-тест
   (паттерн `test_auth_verify.py`).
6. Unsubscribe-роут + монтаж в v1 + rate-limit + integration-тест; `make
   gen-openapi gen-types`.
7. Шаблоны `lifecycle/weekly-digest`, `lifecycle/win-back` + реестр + footer-prop;
   проверка рендера через templates-сервис (паттерн `test_email_delivery.py`).
8. `notifications/tasks.py` + beat-entry в `scheduler.py` (+`test_scheduler.py`);
   integration-тик по образцу `test_renewal_notifications.py`.
9. Verify (G2): полный прогон + ручная проверка писем в mailpit.

## Invariants

- Lifecycle-письма НИКОГДА не уходят: неверифицированным, opted-out, чаще лимитов
  (digest 7д / win-back 30д+цикл). Welcome — максимум один раз за жизнь юзера.
- Транзакционные письма (verify/reset/renewal) не зависят от opt-out и этим
  диффом не затрагиваются.
- Сбой отправки одному юзеру не прерывает тик для остальных; `*_last_sent_at`
  проставляется ТОЛЬКО при успешной отправке (идемпотентность через состояние —
  паттерн `last_reminder_window` TASK-027).
- PII (email/токены/URL) не логируются — только user_id (паттерн
  `_send_email_best_effort`).
- Compliance §7: в digest — только санитизированные topic-метки и агрегаты;
  никакого сырого текста постов (48h retention) и channel-хэндлов.
- Celery-таски принимают JSON-сериализуемые аргументы (ids, не ORM) — CONVENTIONS.
- Все интервалы/пороги — pydantic-settings/именованные константы, не magic literals.

## Edge cases

- Юзер отписался между due-отбором и отправкой → проверка opt-out непосредственно
  перед send в обработке юзера (одна транзакция чтения состояния).
- Юзер верифицировался, но удалил все watchlists → digest skip (нет контента),
  win-back skip (нечего возвращать — нет паков; шлём только при ≥1 watchlist).
- `GET /email/unsubscribe` дёргают сканеры/префетчеры почты по чужим ссылкам →
  токен подписан (audience+secret), идемпотентен, rate-limited; GET без
  side-effect-сюрпризов кроме целевого флага. Prefetch-«самоотписка» владельцем
  ссылки — известный компромисс one-click; фиксируем как accepted risk в Details.
- Удалённый юзер (GDPR, TASK-033) к моменту тика → due-запрос джойнит живых
  юзеров; отправка по несуществующему id невозможна.
- Письмо digest при выключенном templates-сервисе → `EmailRenderError` →
  лог + юзер пропущен, `digest_last_sent_at` НЕ проставлен → ретрай следующим тиком.
- Часовой дрейф beat-интервала (рестарты) → лимиты считаются от `*_last_sent_at`
  в БД, не от расписания — дублей нет.
- Миграционный номер занят параллельной задачей (066 → 0020) → взять следующий
  свободный, `down_revision` от фактического head.

## Test plan

- unit: `tests/unit/notifications/test_lifecycle.py` — due-логика (все ветки:
  верификация, opt-out, окна 7/14/30д, re-arm, пустой digest), токен
  (round-trip, чужая audience, истёкший, мусор); `test_email.py` — headers
  аддитивен; `test_scheduler.py` — beat-entry присутствует с интервалом из настроек.
- integration: unsubscribe-роут (200 идемпотентно / 400 мусор / rate-limit);
  welcome на verify-флоу (`test_auth_verify.py`-паттерн); тик: сид юзеров
  (due-digest / due-winback / unverified / opted-out) → отправки и
  `*_last_sent_at` точечно (monkeypatch SMTP, паттерн
  `test_renewal_notifications.py`); рендер новых шаблонов через живой
  templates-сервис (паттерн `test_email_delivery.py`).
- e2e: не требуется (нет UI-фронта в scope; ручная проверка писем в mailpit на G2).
- security (стадия 5.5 ОБЯЗАТЕЛЬНА): unauth-эндпоинт — подпись токена, отсутствие
  user enumeration (единый 400), rate-limit, отсутствие PII в логах/ответах.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 6
baseline_commit: "650663d"
branch: "task/069-email-lifecycle"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — findings none blocking; cluster.topic↔watchlist.topic match подтверждён by construction, scorer/tasks.py:435)
- [x] 5.5 security (unauth unsubscribe: подпись+audience+exp, uniform 400, no enumeration (deleted user → 200), rate-limit 30/min, PII-free логи, статический HTML без reflected input, stdlib отбивает header-injection в List-Unsubscribe)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(do/verify 2026-06-11, Fable-5: миграция получила номер **0022** (head на момент do =
0021 из TASK-048, не 0019 из плана). Решения do-стадии: welcome CTA → `/onboarding`
(страница подключения паков SPA, выделенного `/packs` роута нет); win-back CTA →
`/watchlists`; база unsubscribe-URL = `public_base_url or frontend_base_url` +
`/api/v1/email/unsubscribe` (паттерн feedback-кнопок TASK-042; фронтовый базовый URL
указывает на тот же nginx-edge, что проксирует `/api/`); семантика повторного win-back —
консервативное **AND** (новый цикл = re-arm по `delivered_at > winback_last_sent_at`
И прошло ≥30д cooldown; без новой активности юзер получает ровно одно win-back);
welcome subject оставлен TrendPulse-брендом в тон существующему шаблону (ребренд —
долг TASK-072), новые lifecycle-шаблоны — «Foresignal»; `unsubscribeUrl` добавлен
опциональным prop в реестр welcome (обязательный — в двух новых шаблонах);
дополнительный gate тика: `User.is_active IS TRUE` (отключённые аккаунты не получают
lifecycle). Accepted risk: GET-unsubscribe может сработать от почтового префетчера —
один таргетный идемпотентный side effect, компромисс one-click (см. Edge cases).
Verify: unit 687 passed; integration 252 passed/10 skipped (skip = Redis/templates/ML
недоступны локально — как на baseline) на одноразовом pgvector:pg16 (порт 15437);
живой рендер всех 3 шаблонов через `npx tsx server/main.ts` + POST /render (subject,
unsubscribe-ссылка, топики/score/pack в HTML; транзакционный verify-email рендерится
без unsubscribe — не задет); mailpit-прогон на стенде — owner-шаг.)

(planned 2026-06-11: инфраструктура писем полностью готова (TASK-025/026/027) —
задача складывает из неё активационный контур. Шаблон `auth/welcome` найден готовым,
но неподключённым. Ключевые решения: welcome на верификацию (не на регистрацию),
digest только при непустом контенте, win-back по суррогату `MAX(delivered_at)`
(открытий не трекаем), unsubscribe-токен на штатном fastapi-users JWT без новых
зависимостей, состояние — 3 аддитивные колонки users. deps: TASK-025 (email-сервис),
TASK-027 (beat-паттерн + идемпотентность через состояние), TASK-050 (воронка —
семантика активации согласована).)
