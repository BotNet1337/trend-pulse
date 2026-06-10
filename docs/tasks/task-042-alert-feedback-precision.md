---
id: TASK-042
title: Фидбек 👍/👎 на алерт (inline-кнопки) + alert_feedback + precision per user
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e2-alert-feedback-precision"
tags: [epic-e2, backend, alerts, api, telegram]
---

# TASK-042 — Фидбек 👍/👎 + precision per user (Epic E2)

> Система не знает, полезны ли её сигналы. Один тап в Telegram-алерте → строка в
> `alert_feedback` → метрика precision per user. Это данные для TASK-043 (адаптивный порог)
> и для E6-дашборда. Критический путь до первого доллара проходит через эту задачу.

## Context

Доставка: `alerts/backends.py::TelegramBotBackend.send` шлёт `sendMessage` с `{chat_id, text}`
на `{telegram_api_base_url}/bot{token}` — reply_markup НЕ передаётся. Сообщение строится в
`alerts/formatting.py::format_alert_message(view)`. Бот-токен — **per-user**
(`user.telegram_bot_token`), значит callback придёт на бота юзера → нужен наш webhook-endpoint,
на который юзер (или мы при сохранении delivery-config) ставит setWebhook, ЛИБО лёгкий путь:
**callback_data не нужен серверу Telegram** — кнопки с `callback_data="fb:<alert_id>:up|down"`
требуют webhook/getUpdates. Альтернатива без webhook: **deep-link кнопки** (`url=`) на наш
API `GET /feedback/{token}` — работает с любым ботом без setWebhook. API-роутеры включаются
в `api/main.py`; существующих telegram-webhook-роутов нет. Миграции: последняя 0012.

## Goal

В каждом Telegram-алерте — две inline-кнопки 👍/👎; тап записывает вердикт в `alert_feedback`
(alert_id, verdict, created_at) идемпотентно (повторный тап = update); observability получает
`log_event("alert_precision", user_id, precision, rated, total)` периодически (расширение
существующего beat `emit-signal-latency` или отдельный tick). DoD = AC.

## Discussion
- Q: callback_query (webhook) или deep-link URL-кнопки? → Decision: **URL-кнопки** на
  `GET /feedback/{signed_token}` (HMAC-подписанный token: alert_id+verdict+exp). Причины:
  (1) per-user боты — мы не управляем их webhook'ами; (2) zero-конфигурация для юзера;
  (3) не открываем публичный telegram-webhook-endpoint (меньше attack surface). Минус —
  открывается браузер: приемлемо для MVP, фиксируем как known-tradeoff. Ответ —
  минимальная HTML-страница «спасибо» (или редирект на app).
- Q: Подпись token? → Decision: `itsdangerous`-стиль HMAC c `jwt_secret` не переиспользовать —
  отдельный derive (`feedback` salt), exp = 7d (константа). Без auth-cookie — кнопка должна
  работать из любого браузера; token = bearer сам по себе (scope: один alert, один verdict).
- Q: Идемпотентность/смена мнения? → Decision: UNIQUE(alert_id) + UPSERT verdict —
  последний тап выигрывает. (alert уже per-user, user_id денормализуем для метрики.)
- Q: precision формула? → Decision: `up / (up + down)` за окно 7d per user; алерты без
  оценки в precision не входят (отдельно `rated_share = rated / total`).

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/0013_alert_feedback.py` — **новая**: `alert_feedback`
    (id, alert_id FK UNIQUE, user_id FK, verdict smallint/enum, created_at, updated_at).
  - `backend/src/storage/models/alert_feedback.py` — **новый** + экспорт в models/__init__.
  - `backend/src/api/feedback/` — **новый** роутер: `GET /feedback/{token}` (verify → upsert →
    200 HTML-минимум), без auth, со своим rate-limit.
  - `backend/src/alerts/feedback_tokens.py` — **новый**: sign/verify (HMAC, exp, salt).
  - `backend/src/alerts/formatting.py` — `build_reply_markup(view, settings) -> dict` (две
    URL-кнопки; base_url из настроек `public_base_url`).
  - `backend/src/alerts/backends.py` — `TelegramBotBackend.send`: + `reply_markup` в payload.
  - `backend/src/observability/signal_latency.py` (или tasks.py) — emit `alert_precision`
    per user в существующем latency-тике.
  - `backend/src/config.py` — `public_base_url`, `feedback_token_ttl_seconds` (604800).
  - `backend/src/api/main.py` — include feedback router.
  - tests: `backend/tests/unit/alerts/test_feedback_tokens.py`,
    `backend/tests/integration/test_feedback_api.py` (**новые**).
  - OpenAPI: `make gen-openapi gen-types` (контракт меняется) + коммит дампа.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** webhook-backend (фидбек только в TG MVP), scorer (это TASK-043),
  frontend (страница фидбека — server-side HTML-минимум, без SPA-работ).
- **Blast radius:** payload sendMessage (+reply_markup — backward-safe), новый публичный
  endpoint (rate-limit + HMAC обязательны), миграция (новая таблица — безопасно).

## Acceptance Criteria
- [x] **AC1 — кнопки в сообщении (failing-test anchor).** Given алерт доставляется в TG,
  Then payload содержит reply_markup c двумя url-кнопками 👍/👎 с валидными signed-token. RED.
- [x] **AC2 — тап пишет вердикт.** GET /feedback/{token(up)} → 200, строка alert_feedback
  c verdict=up; повторный тап down → та же строка, verdict=down (upsert, не дубль).
- [x] **AC3 — токен защищён.** Истёкший/подделанный/чужой token → 4xx, БД не тронута;
  endpoint под rate-limit.
- [x] **AC4 — precision метрика.** Given 3 up + 1 down за окно, Then log_event
  alert_precision: precision=0.75, rated=4 для юзера.
- [x] **AC5 — G2.** Живой стек: реальный алерт в TG (или мок Bot API при отсутствии кред) с
  кнопками; curl по ссылке из кнопки → строка в БД; `make ci-fast` + openapi-drift зелёные.

## Plan
1. **RED:** test_feedback_tokens (sign/verify/exp/tamper) + test_feedback_api (AC2/AC3).
2. Миграция 0013 + модель.
3. feedback_tokens + роутер (rate-limit, HTML-ответ).
4. formatting.build_reply_markup + backends reply_markup.
5. precision-emit в observability-тике.
6. GREEN + gen-openapi/types + G2; tasks-index на ship.

## Invariants
- Доставка алерта НЕ ломается, если public_base_url пуст → кнопки просто не добавляются
  (graceful degradation, log warning once).
- Идемпотентность доставки (delivered-no-op) не затронута.
- Никакого raw content в log_event (гейт logging.py).
- Token одноцелевой: один alert_id+verdict, exp; нет enumerable id в URL.

## Edge cases
- Алерт удалён ретенцией к моменту тапа → 410/404, дружелюбный HTML.
- Юзер удалил аккаунт (GDPR-каскад) → FK каскадом убирает feedback; тап после — 404.
- Двойной клик/гонка двух тапов → UPSERT, last-write-wins.
- TG обрезает длинные url → держать token коротким (HMAC-trunc 16b + payload компактный).

## Test plan
- **unit:** tokens (подпись/exp/tamper), formatting (reply_markup структура), precision-расчёт.
- **integration:** test_feedback_api — AC2/AC3 полный цикл через ASGI.
- **G2:** живой сценарий AC5.
- **security (5.5):** ОБЯЗАТЕЛЬНО — новый публичный unauthenticated endpoint: HMAC, exp,
  rate-limit, отсутствие user enumeration, no open redirect.

## Checkpoints
current_step: done
baseline_commit: "c6be7bcd4d5ded2e6e8d566954b7a4b4ac214173"
branch: "gsd/phase-e2-alert-feedback-precision"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior)
- [x] 5 review (auto, adversarial — 2 HIGH найдены и исправлены)
- [x] 5.5 security (pass; MEDIUM https-валидатор public_base_url — исправлен)
- [x] 6 ship (PR #54, squash-merge, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-10 TASK-042)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E2, 042 питает 043 данными. Ключевое решение: URL-кнопки вместо
callback_query — per-user боты делают setWebhook неуправляемым; deep-link на наш API работает
с любым ботом без конфигурации. public_base_url — новая обязательная prod-настройка
(добавить в deploy.env шаблон/group_vars при ship).)

### locate (2026-06-10, loop run)
- `backends.py:84-105` TelegramBotBackend.send: body={chat_id,text} через httpx.post,
  timeout 10s, _raise_for_http_status (transient 429/5xx vs permanent 4xx); токен repr=False.
- `formatting.py:22-39`: AlertView — frozen dataclass (topic,title,score,channels_count,
  first_seen,velocity); format_alert_message — pure. build_reply_markup(view, public_base_url)
  -> dict|None; None при пустом base_url (graceful degradation).
- Rate-limit: slowapi (Redis, in-memory fallback), ключ apikey:hash|user:id|ip:addr,
  default 120/min из Settings; per-route override через @limiter.limit().
- Signing-прецедент: fastapi-users JWT HS256 c jwt_secret; HMAC-утилит нет — пишем
  feedback_tokens.py (HMAC-SHA256, отдельный salt "feedback", exp 7d, компактный token).
- Модели: UserOwnedBase (id PK + user_id FK CASCADE), utcnow() для timestamps,
  UniqueConstraint-прецедент uq_alerts_user_cluster; UPSERT-прецедент
  on_conflict_do_update(constraint=...) в scorer/tasks.py.
- Миграции: последняя 0012 → новая 0013_alert_feedback.py.
- Precision-emit: расширить observability/signal_latency.py (+emit_alert_precision),
  вызов из emit_signal_latency_task (beat 300s), best-effort (warning, не raise).
- Config: public_base_url ("" default) + feedback_token_ttl_seconds (604800) — оба несекретные;
  при ship добавить PUBLIC_BASE_URL в ops/ansible/roles/env/templates/deploy.env.j2.
- Роутер-паттерн: api/<name>/{router,schemas,service}.py, include_router в api/main.py;
  OpenAPI: make gen-openapi gen-types + коммит дампа (контракт меняется!).

### do (2026-06-10, loop run)
- TDD RED→GREEN: 22 новых unit (tokens 10, reply_markup 7, precision 5) + 5 integration
  (feedback API: tap/upsert/4xx/410). Итог: ci-fast 455 unit, integration 130 passed.
- Токен: base64url(payload).base64url(HMAC-SHA256-trunc16), ~72 символа (< лимита TG url).
- DeliveryBackend.send получил `alert_id: int | None = None` (нужен для токенов в момент
  отправки; webhook игнорирует) — лёгкое расширение протокола, notifier.py затронут.
- precision_window_seconds — отдельная настройка (не привязана к feedback_token_ttl_seconds).
- Graceful degradation подтверждён: пустой public_base_url → reply_markup не добавляется.
- Миграция 0013 применена локально (alembic upgrade head через socat-форвард).
- OpenAPI дамп+типы перегенерированы (новый GET /feedback/{token}).

### verify G2 (2026-06-10, loop run)
- ci-fast 455 unit зелёный; integration 130 passed/10 skipped; поведенчески на живом ASGI+
  реальном Postgres: tap up → 200 + строка verdict=up; down-token → та же строка verdict=down
  (1 строка, UPSERT); expired/tampered/garbage → 400, БД не тронута; reply_markup URL
  end-to-end работает; emit_alert_precision: precision=0.75 rated=4 total=4 (3up/1down).
- slowapi при недоступном Redis деградирует в in-memory fallback — boot не падает.
- openapi-drift-check «падал» только из-за незакоммиченных перегенерённых файлов — закрывается
  коммитом дампа+типов на ship (файлы на диске корректны).
- Гочча dev: build_reply_markup даёт /api/feedback/ (nginx-префикс прода); на голом ASGI
  роут живёт на /feedback/ — 404 без nginx ожидаем.

### review + security + fix-цикл (2026-06-10, loop run)
- review HIGH-1: precision `total` == `rated` (выпал подзапрос по alerts; unit-моки маскировали).
  FIX: коррелированный подзапрос COUNT(alerts за окно по delivered_at); RED-тест
  (5 алертов / 4 оценённых → total=5) падал до фикса, зелёный после.
- review HIGH-2: `async def` хэндлер с блокирующей sync-сессией → plain `def` (threadpool),
  как в packs/router.py.
- review MEDIUM: мёртвые _COL_*-константы задействованы; добавлен реальный 429-тест
  rate-limit (mini-app, memory:// limiter).
- security MEDIUM: field_validator public_base_url — пусто=выключено, https:// обязателен,
  http:// только для localhost (dev); 9 unit-тестов. PUBLIC_BASE_URL прокинут:
  deploy.env.j2 + group_vars/all.yml ('' default) + group_vars/prod.yml (https://foresignal.biz).
- Гейты после фиксов: ci-fast 465 unit, integration 132 passed/10 skipped.
