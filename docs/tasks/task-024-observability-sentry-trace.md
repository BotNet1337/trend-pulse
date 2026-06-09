---
id: TASK-024
title: Observability — Sentry + correlation/trace-id (FastAPI + Celery, сквозной trace)
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "3689476030a985e227e35a125c752b0dd3dd4de1"
branch: "gsd/phase-024-observability-sentry-trace"
tags: [epic-d, backend, observability, ops]
---

# TASK-024 — Observability: Sentry + correlation/trace-id (Epic D)

> Подключить `sentry_sdk` к FastAPI И к Celery (`SENTRY_DSN` из env — off если пусто; теги `environment`/`release`). Ввести `request_id` (uuid4) в request-middleware → отдавать в response-header `X-Request-ID` и класть в structured-log context на КАЖДОМ событии; пробросить тот же id в Celery-задачу (через task headers/args) чтобы трейс «scorer → dispatch_alert → notifier» был сквозным. Unhandled exception в API и в Celery попадает в Sentry (в тесте — mock/in-memory transport). Никаких magic literals (DSN/sample-rate — из settings). Security 5.5: scrub секретов/PII перед отправкой в Sentry.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md), [`../architecture/high-level-architecture.md`](../architecture/high-level-architecture.md)) — асинхронный пайплайн: API принимает запрос, Celery Beat тикает scorer (`score_tick`), scorer находит вирусный кластер и через `alerts.tasks.dispatch_alert` (task-009) доставляет alert в `alerts/notifier.py` (Telegram). Сейчас наблюдаемость — только structured JSON logging: `backend/src/observability/logging.py` (configure_logging), `middleware.py` (`log_requests` — агрегатно method/path/status/duration), `celery_logging.py` (register_celery_logging). **НЕТ trace/correlation-id** (нечем связать API-запрос с фоновой задачей и логи между процессами), **НЕТ Sentry** (unhandled-исключения не агрегируются).

Это типовая hardening-добавка: error-tracking + сквозной идентификатор запроса. Все настройки — через `config.py` (pydantic-settings), env приходит из `development/env/{deploy,sensitive}.env` (Ansible source of truth). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, no magic literals (DSN/sample-rate/env-name из settings), никаких секретов/PII в логах и в Sentry (hygiene-helper в logging.py уже гарантирует отсутствие raw-content в логах — расширяем тем же принципом на Sentry).

## Goal

После задачи: (1) при заданном `SENTRY_DSN` unhandled exception в FastAPI-эндпоинте и в Celery-задаче автоматически попадает в Sentry с тегами `environment`/`release`; при пустом `SENTRY_DSN` инициализация — no-op (off, без падений). (2) Каждый HTTP-запрос получает `request_id` (uuid4), который виден в response-header `X-Request-ID` и присутствует в каждой строке structured-лога этого запроса. (3) Тот же `request_id` пробрасывается в Celery-задачи, порождённые в рамках запроса (через task headers), и в Beat-инициированную цепочку (scorer → dispatch_alert → notifier генерит/наследует trace-id), так что логи всех процессов одной логической операции связаны единым id. (4) Секреты/PII не утекают в Sentry (scrubbing). DoD ниже.

## Discussion
<!-- durable record of clarifications. Обратимы. -->
- Q: Где инициализировать Sentry? → A: два процесса (api, worker/beat) → Decision: общий хелпер `observability/sentry.py::init_sentry(component)` с `FastApiIntegration`+`StarletteIntegration` (api) и `CeleryIntegration` (worker); вызывается из `api/main.py` (рядом с `configure_logging()`) и из `celery_app.py` (рядом с `register_celery_logging()`). `SENTRY_DSN` пустой → ранний return (off). Sample-rate/`traces_sample_rate`/`environment`/`release` — из settings, не inline.
- Q: Откуда `environment`/`release`? → A: уже есть env-инфраструктура → Decision: `environment` = `settings.environment` (dev/prod), `release` = версия из settings (или `version.env`/git sha, прокинутый build-arg как env). Не magic literal.
- Q: Как генерится `request_id`? → A: на границе → Decision: в `observability/middleware.py` (`log_requests`) — взять входящий `X-Request-ID` если валиден (доверять только за nginx-edge — иначе игнорировать и генерить свой uuid4), иначе сгенерировать uuid4. Положить в contextvar → structured-logger подмешивает его в каждое событие; вернуть в response-header.
- Q: Как связать с Celery? → A: задачи запускаются и из API, и из Beat → Decision: использовать contextvar + Celery `before_task_publish`/`task_prerun` сигналы (или передачу через task headers/kwargs): publisher кладёт текущий `request_id` в headers, worker на `task_prerun` читает его в свой contextvar (если headers нет — генерит новый trace-id для Beat-инициированной цепочки). Цепочка scorer→dispatch_alert→notifier наследует id, т.к. dispatch_alert публикуется из scorer-задачи (уже в trace-контексте).
- Q: contextvar и async? → A: structlog/std logging + contextvar → Decision: contextvar безопасен в async и в Celery prefork (устанавливается per-task в `task_prerun`, очищается в `task_postrun`). Logger-processor читает contextvar и добавляет `request_id`/`trace_id` в каждый event-dict.
- Q: Тестирование Sentry без сети? → A: не дёргать sentry.io → Decision: в тесте — `sentry_sdk` с in-memory/mock transport (capture events в список) ИЛИ мок `sentry_sdk.capture_exception`; ассертить, что unhandled exception захвачен и scrubbed.

## Scope
> **backend** observability-добавка: новый `observability/sentry.py`, расширение `middleware.py`/`logging.py`/`celery_logging.py` контекстом `request_id`/`trace_id`, инициализация в `api/main.py`+`celery_app.py`, новые settings. Бизнес-логику (scorer/notifier/billing) НЕ меняем — только инструментируем.

- **Touch ONLY (создать/изменить):**
  - `backend/src/observability/sentry.py` — **новый**: `init_sentry(component: Literal["api","worker"]) -> None` (off если DSN пуст; integrations по компоненту; `before_send` scrubbing-хук).
  - `backend/src/observability/context.py` — **новый** (или в `logging.py`): contextvar `request_id_var`/`trace_id_var` + helpers `get_request_id()`/`bind_request_id()`.
  - `backend/src/observability/middleware.py` — расширить `log_requests`: принять/сгенерировать `request_id` (uuid4), bind в contextvar, добавить `X-Request-ID` в response.
  - `backend/src/observability/logging.py` — log-processor подмешивает `request_id`/`trace_id` из contextvar в каждый event (hygiene-helper не трогаем кроме интеграции).
  - `backend/src/observability/celery_logging.py` — Celery-сигналы (`before_task_publish` кладёт id в headers; `task_prerun`/`task_postrun` bind/clear contextvar); register в `register_celery_logging`.
  - `backend/src/api/main.py` — вызвать `init_sentry("api")` рядом с `configure_logging()`.
  - `backend/src/celery_app.py` — вызвать `init_sentry("worker")` рядом с `register_celery_logging()`.
  - `backend/src/config.py` — settings `sentry_dsn` (default `""`), `sentry_traces_sample_rate` (default 0.0), `environment`, `release` (если ещё нет).
  - `development/env/deploy.env`, `development/env/sensitive.env` — дефолты/плейсхолдеры (`SENTRY_DSN=""`, sample-rate; DSN — в sensitive).
  - `backend/tests/unit/test_request_id.py` — request_id генерация/наследование + header + log-context.
  - `backend/tests/integration/test_observability.py` — AC: unhandled→Sentry mock (api+celery), `X-Request-ID` в ответе, trace сквозной.
  - `docs/tasks/tasks-index.md` — на ship (НЕ в этой задаче-планировании).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, бизнес-логика `backend/src/{scorer,pipeline,collector,billing}/**` (только инструментируем через сигналы/contextvar, не меняем поведение), `alerts/notifier.py` доставка (только наследует trace-id, не переписываем доставку). Не добавлять APM/трейсинг-бэкенды кроме Sentry. Не логировать тело запросов/PII.
- **Blast radius:** middleware (`log_requests`) теперь устанавливает contextvar + header на КАЖДОМ запросе — затрагивает все ответы (добавляется header). Celery-сигналы навешиваются глобально → все задачи получают trace-context (no-op для задач без входящего id). Sentry init при пустом DSN — полностью off (dev по умолчанию off). Новые settings — обратносовместимые дефолты.

## Acceptance Criteria
- [ ] **AC1 — request_id в header + логах (failing-test anchor).** Given любой HTTP-запрос, When он обрабатывается, Then ответ содержит `X-Request-ID` (uuid4 или проброшенный валидный входящий), и каждая строка structured-лога этого запроса содержит тот же `request_id`. Тест пишется ПЕРВЫМ (RED).
- [ ] **AC2 — Sentry off при пустом DSN.** Given `SENTRY_DSN=""`, When процессы (api/worker) стартуют, Then `init_sentry` — no-op (Sentry не инициализирован), приложение работает без ошибок; никаких сетевых вызовов.
- [ ] **AC3 — unhandled exception в FastAPI → Sentry.** Given `SENTRY_DSN` задан (mock-transport), When эндпоинт бросает необработанное исключение, Then событие захвачено Sentry с тегами `environment`/`release`.
- [ ] **AC4 — unhandled exception в Celery → Sentry.** Given `SENTRY_DSN` задан (mock-transport), When Celery-задача бросает необработанное исключение, Then событие захвачено Sentry (CeleryIntegration).
- [ ] **AC5 — сквозной trace API→Celery.** Given запрос с `request_id`, When он публикует Celery-задачу, Then в логах задачи присутствует тот же id (через task headers → contextvar); для Beat-инициированной цепочки scorer→dispatch_alert→notifier — единый trace_id во всех трёх шагах.
- [ ] **AC6 — scrubbing (security 5.5).** Given событие в Sentry, When оно формируется (`before_send`), Then секреты/PII (Authorization/cookie headers, токены доставки, email/пароли в payload) удалены/замаскированы; raw-content постов не уходит.
- [ ] **AC7 — поведенческая (G2) через стек.** Given `make up`, When сделать запрос за nginx и инициировать фоновую задачу, Then `X-Request-ID` виден в ответе и в логах api+worker один и тот же id (grep по логам контейнеров); при заданном DSN — exception доходит до Sentry-приёмника (или mock).

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-024-observability-sentry-trace`.
1. **RED:** `test_request_id.py` — header `X-Request-ID` + `request_id` в log-context. Падает (нет contextvar/header). AC1-якорь.
2. `observability/context.py` (contextvar) + расширить `middleware.py` (gen/inherit id, header) + `logging.py` (processor подмешивает id). `make ci-fast` зелёный по AC1.
3. `observability/sentry.py` (`init_sentry`, off при пустом DSN, integrations, `before_send` scrub) + settings в `config.py`; init в `api/main.py` и `celery_app.py`.
4. Celery-сигналы в `celery_logging.py` (publish→headers, prerun→contextvar) для сквозного trace.
5. `test_observability.py` — Sentry mock-transport (api+celery unhandled), trace API→Celery, scrub. **GREEN** локально.
6. env-дефолты (`deploy.env`/`sensitive.env`).
7. **G2:** `make up`; запрос за nginx → `X-Request-ID` + общий id в логах api/worker; (опц.) DSN-приёмник получает exception. Security 5.5: scrub проверен.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Sentry off без DSN** — пустой `SENTRY_DSN` ⇒ полная инициализация-no-op, ноль сетевых вызовов (dev по умолчанию off).
- **request_id на каждом запросе** — contextvar устанавливается в middleware, очищается по завершении; logger-processor добавляет его в КАЖДОЕ событие; header `X-Request-ID` всегда в ответе.
- **Доверять входящему id только за edge** — входящий `X-Request-ID` принимается лишь как валидный uuid; иначе генерится свой (no header-injection).
- **Сквозной trace через headers/contextvar** — Celery publisher кладёт id в task headers, worker читает в `task_prerun`; Beat-цепочка наследует единый trace_id; никаких ORM-объектов в task args (CONVENTIONS).
- **No secrets/PII в Sentry и логах** — `before_send` scrubbing (auth headers/cookies/токены/email/raw-content); hygiene-helper logging.py остаётся источником истины для логов.
- **No magic literals** — DSN/sample-rate/environment/release — из settings; full type hints; immutable event-dict (новый dict, не мутация).

## Edge cases
- Пустой/невалидный входящий `X-Request-ID` (или попытка инъекции) → игнор, генерим свой uuid4.
- Celery-задача запущена из Beat (без входящего запроса) → генерим новый trace_id в `task_prerun`, цепочка наследует его.
- Sentry init вызван дважды (api перезагрузка/тест) → идемпотентность (не падать на повторной инициализации).
- DSN задан, но Sentry недоступен (сеть) → не блокировать запрос/задачу (Sentry асинхронный/best-effort), ошибку Sentry не эскалировать в пользователя.
- contextvar в Celery prefork — установка per-task, чтобы id не «протёк» между задачами одного воркера (clear в `task_postrun`).
- Очень длинный/большой payload исключения → Sentry усечёт; убедиться, что scrub применяется до отправки.
- Health-эндпоинт (`/health`) — header можно ставить, но не зашумлять Sentry/трейсами (sample 0 или skip — health не должен генерить трафик).

## Test plan
- **unit:** `test_request_id.py` — gen/inherit uuid4, валидация входящего id, header в ответе, `request_id` в log-event (capture processor output); `before_send` scrub-юнит (auth header/токен/email вычищены).
- **integration:** `test_observability.py` — AC2 (off при пустом DSN), AC3 (FastAPI unhandled→mock Sentry с тегами), AC4 (Celery unhandled→mock Sentry), AC5 (trace API→Celery: общий id в логах задачи; Beat-цепочка единый id).
- **runtime/behavioral (G2):** `make up` → запрос за nginx → `X-Request-ID` в ответе; grep логов api+worker на общий id одной операции; (опц.) DSN-приёмник/Sentry-локальный релей получает тестовый exception.
- **security (5.5):** инспекция Sentry-события — нет Authorization/cookie/токенов/email/raw-content; логи без секретов (hygiene-helper).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "3689476030a985e227e35a125c752b0dd3dd4de1"
branch: "gsd/phase-024-observability-sentry-trace"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior через стек)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (opus — обязательна; scrub PII/секретов + stacktrace-vars)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs:
  - "loop-024 verify#1: AC5/AC7 — worker-логи не JSON и без request_id. ROOT: `configure_logging()` вызывался только в api/main.py; Celery при старте worker перехватывает root logger (`worker_hijack_root_logger`), import-time configure_logging не выживает. FIX: receiver на сигнал `setup_logging` (Celery отдаёт логирование нам) в celery_logging.register_celery_logging → configure_logging применяет JSON + RequestIdFilter в worker. Verify: worker-лог `celery.task` теперь JSON с `request_id` (Beat-trace). + заодно ansible `sensitive.env.j2` `{{ vault_sentry_dsn | default('') }}` (иначе `make ansible-unpack` падал на undefined, т.к. SENTRY_DSN опционален) + убран `# type: ignore[arg-type]` на токене (типизирован `dict[str, Token[str|None]]`)."

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-016/017 и контексту Epic D: error-tracking (Sentry FastAPI+Celery, off при пустом DSN) + сквозной correlation/trace-id (uuid4 в middleware → `X-Request-ID` + log-context → проброс в Celery через headers/contextvar; trace scorer→dispatch_alert→notifier). Бизнес-логику не трогаем — только инструментируем `observability/*`, `api/main.py`, `celery_app.py`. deps: 011 (structured logging/rate-limit/compliance — база observability). no magic literals (DSN/sample-rate/env/release из settings). Security 5.5: scrub секретов/PII перед Sentry. locate+plan выполнены этим планированием — executor стартует с «3 do».)

### do+verify+review+security (loop-024, 2026-06-09)
**do:** созданы `observability/{context,sentry}.py`; `RequestIdFilter` в logging (request_id в КАЖДУЮ запись); middleware gen/inherit uuid + `X-Request-ID`; Celery trace через `before_task_publish`→headers / `task_prerun`→contextvar / `task_postrun`→reset (Beat генерит свой); `init_sentry(api/worker)` (off при пустом DSN); settings sentry_dsn/sentry_traces_sample_rate/environment/release; env в ansible-источник. unit 277, ci-fast, test-cov, import-OK.
**verify (G2 за стеком):** X-Request-ID за nginx (gen/inherit-valid/reject-invalid дословно), request_id в api-логах; **2 блокера в debug_runs исправлены** (worker JSON-логи через `setup_logging`-сигнал; ansible `| default('')`). Worker-лог `celery.task` теперь JSON с Beat-trace request_id.
**review (opus): 0 CRITICAL, 2 HIGH — исправлены:**
- HIGH (middleware `response` unbound в finally → UnboundLocalError маскирует исходное исключение + утечка токена) → реструктурирован: success-path (log+header+return) внутри try, `reset_request_id` в finally; при исключении call_next оригинал пробрасывается нетронутым.
- HIGH (`release` объявлен, но не прокинут → всегда "dev" в проде) → `RELEASE={{ app_version }}` в `deploy.env.j2`.
- MEDIUM: убран дублирующий `traces_sample_rate` из init (sampler и так выигрывает); `_HEALTH_PATH` константа; scrub-рекурсия в списки.
**security (opus, обязательна): 0 CRITICAL, 1 HIGH + 3 MEDIUM — исправлены:**
- HIGH (utечка секретов через stacktrace frame locals — sentry дефолт `include_local_variables=True` собирает repr локалов: Telegram session/api_hash, пароли, Settings-креды; before_send их не чистит) → **`include_local_variables=False`** в init.
- MEDIUM M1 (scrub-паттерны неполны) → расширены: exact +api_hash/api_key/session/dsn/secret/token; суффиксы +`_api_key`(nowpayments_api_key)/`_api_hash`/`_password`(postgres_password)/`_session(s)`/`_dsn` (узко — без bare `_key`/`_hash`, чтобы не скрабить sort_key/media_hash).
- MEDIUM M2 (non-dict request.data не скрабился) → не-dict body → `"[scrubbed]"` целиком.
- MEDIUM M3 (raw-content дропался только в request.data) → `_DROP_CONTENT_KEYS` дропаются в extra/contexts/breadcrumbs тоже (общий `_scrub_dict`).
- + breadcrumbs scrub, depth-limit (M4), убран `# type: ignore` на токене. Добавлено 6 security-тестов (api_hash/`_key`/session/dsn маскируются; content в extra дропается; non-dict data; list-рекурсия; breadcrumbs; include_local_variables=False).
Перепроверка: ci-fast 283 passed, test-cov 82.22%, import-OK.
**Follow-up (не блокер):** SENTRY_DSN-значение требует записи `vault_sentry_dsn` в `ops/ansible/vault/sensitive.vault.yml` перед prod (дефолт "" = off, безопасно).

### Подсказки исполнителю (initial)
- **Sentry SDK:** `sentry-sdk[fastapi]` + Celery integration. `init_sentry`:
  - api: `FastApiIntegration()`, `StarletteIntegration()`; worker: `CeleryIntegration()`.
  - параметры: `dsn=settings.sentry_dsn or None` (None ⇒ disabled), `environment=settings.environment`, `release=settings.release`, `traces_sample_rate=settings.sentry_traces_sample_rate`, `send_default_pii=False`, `before_send=_scrub`.
  - пустой DSN ⇒ ранний `return` ДО `sentry_sdk.init` (явный off, не полагаться на «None молча off»).
- **contextvar:** `ContextVar[str | None]("request_id", default=None)`; logger-processor (structlog/std-logging adapter) добавляет `event_dict["request_id"] = get_request_id()` если задан. Не мутировать существующий dict в structlog (вернуть обновлённый).
- **middleware:** валидировать входящий `X-Request-ID` через `uuid.UUID(value)` (иначе генерить); `token = request_id_var.set(rid)` → в `finally` `request_id_var.reset(token)`; `response.headers["X-Request-ID"] = rid`.
- **Celery проброс:** `before_task_publish` сигнал — `headers["X-Request-ID"] = get_request_id()`; `task_prerun` — прочитать из `task.request.headers` (или kwargs) и `request_id_var.set(...)`; `task_postrun` — reset. Для Beat-задач без header — сгенерить trace_id в prerun. dispatch_alert публикуется из scorer-задачи ⇒ наследует тот же header автоматически.
- **scrub `before_send(event, hint)`:** убрать `event["request"]["headers"]` ключи `authorization`/`cookie`; маскировать в `extra`/`request.data` поля `telegram_bot_token`/`password`/`email`/`*_token`/`*_secret`; вернуть новый event (immutable). Если scrub не уверен — дропнуть поле, не отправлять «как есть».
- **release/version:** прокинуть как build-arg/env из `development/version.env` или git sha; settings `release` дефолт `"dev"`.
- **/health:** исключить из трейс-сэмплинга (low-value шум) — `traces_sampler` возвращает 0 для `/health`.
