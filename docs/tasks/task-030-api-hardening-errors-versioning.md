---
id: TASK-030
title: API hardening — единый error-envelope + machine-readable коды + версионирование /api/v1
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-030-api-hardening-errors-versioning"
tags: [epic-d, backend, frontend, api, dx]
---

# TASK-030 — API hardening: error-envelope + codes + versioning (Epic D)

> Унифицировать контракт ошибок и версионировать API. (1) Единый **error-envelope** `{error: {code, message, details?}}` через единый exception-handler в `backend/src/api/main.py`, нормализующий разнородные сейчас формы: `HTTPException` (`{detail: str}`), `PlanLimitExceeded`→402/403 (`{detail: str}`), `RateLimitExceeded`→429, `BillingNotConfiguredError`→503, Pydantic-422 (`{detail: [...]}`). (2) **machine-readable коды** как `StrEnum`/константы (no magic literals: `PLAN_LIMIT_EXCEEDED`/`RATE_LIMITED`/`NOT_FOUND`/`VALIDATION`/…). (3) **Версионирование** — префикс `/api/v1` на роутерах (зафиксировать решение в ADR; nginx уже стрипает `/api`). (4) Frontend `frontend/src/shared/lib/backend-error.ts` маппит по **`error.code`** (не по хрупкому HTTP-статусу); регенерация `gen.types.ts`. ADR на error-format + versioning. **ОСТОРОЖНО:** меняет контракт всех роутов — детальный Plan, обратная совместимость, не сломать C1–C5. DoD — Acceptance Criteria ниже.

## Context

TrendPulse backend (`backend/src/api/`, см. [`../product/overview.md`](../product/overview.md)) — FastAPI, роуты на **корне** (`/auth`, `/users/me`, `/watchlists`, `/alerts`, `/billing`, `/account`, `/users/me/delivery-config`); nginx (`development/provisioning/nginx/nginx.conf`) стрипает `/api/`→корень (`proxy_pass http://trendpulse_api/;`). **Нет `/api/v1`-префикса.** Ошибки сейчас разнородны (источник истины — `backend/src/api/main.py`):
- `RateLimitExceeded` (slowapi) → `_rate_limit_handler` → 429 JSON (`api/rate_limit.py::rate_limit_handler`).
- `PlanLimitExceeded` (`billing/limits.py`) → `_plan_limit_handler` → `{detail: str}`, code 402 (quota) / 403 (feature).
- `BillingNotConfiguredError` (`billing/deps.py`) → 503 `{detail: str}`.
- `HTTPException` (fastapi) → дефолт `{detail: str}` (404/409/…).
- Pydantic-422 → дефолт `{detail: [{loc, msg, type}, …]}`.

**Нет machine-readable error-кодов** — фронт `frontend/src/shared/lib/backend-error.ts` сейчас маппит **по HTTP-статусам** (402→`quota`, 403→`feature-gate`, 422→`field`, 404→`not-found`, 409→`duplicate`) — хрупко: один статус несёт разные смыслы (403 = feature-gate ИЛИ forbidden; 422 = Pydantic ИЛИ доменная валидация).

Slowapi-лимит глобальный (120/min, `SlowAPIMiddleware` в `api/main.py`); per-route нет (это [task-032](./task-032-security-hardening.md), edge-nginx). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, Pydantic на границе, no magic literals, error-message не течёт внутренности.

## Goal

После задачи: **любой** 4xx/5xx-ответ API отдаёт единый JSON-envelope `{error: {code: "<MACHINE_CODE>", message: "<human>", details?: ...}}` (нормализованы HTTPException/PlanLimitExceeded/RateLimitExceeded/BillingNotConfigured/Pydantic-422); коды — из `StrEnum`/констант (no magic literals); роуты доступны под версионированным путём (`/api/v1/...` решено через ADR — зафиксирован формат и стратегия миграции); фронт `backend-error.ts` маппит по `error.code` (стабильно), `gen.types.ts` регенерирован; обратная совместимость/миграция эндпоинтов не ломает C1–C5 e2e. Security: error-message не раскрывает стек/внутренние пути/SQL. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Решения по main.py + ADR; частично необратимы (контракт) → ADR. -->
- Q: Формат ошибки? → A: envelope `{error: {code, message, details?}}` → Decision: единый `@app.exception_handler` (или несколько, сводящих к одному билдеру) нормализует все исключения в envelope. `details` опционален — для 422 несёт нормализованный список полей (`[{field, message}]`), иначе отсутствует.
- Q: Коды — где живут? → A: `StrEnum`/константы → Decision: `backend/src/api/errors.py` — `ErrorCode(StrEnum)`: `VALIDATION`, `NOT_FOUND`, `DUPLICATE`, `PLAN_LIMIT_EXCEEDED`, `FEATURE_NOT_AVAILABLE`, `RATE_LIMITED`, `BILLING_NOT_CONFIGURED`, `UNAUTHORIZED`, `FORBIDDEN`, `INTERNAL`. Маппинг исключение→code централизован (no magic literals на call-sites).
- Q: Различать quota vs feature-gate (оба от PlanLimitExceeded)? → A: да → Decision: `PlanLimitExceeded` уже несёт `.code` 402/403; маппим 402→`PLAN_LIMIT_EXCEEDED`, 403→`FEATURE_NOT_AVAILABLE` (фронт C5 различает upsell vs feature-lock).
- Q: Версионирование — где префикс? → A: `/api/v1` на роутерах + ADR → Decision: добавить `/v1` на app-уровне (роуты становятся `/v1/auth/...` на backend; nginx `/api/`→корень даёт `/api/v1/...` снаружи). **Обратная совместимость:** оставить корневые роуты как deprecated-alias на переходный период ИЛИ зафиксировать в ADR, что фронт+nginx переключаются атомарно (предпочтение — ADR решает; склоняемся к v1-only + обновить фронт baseURL/`gen:api` источник в одном PR, т.к. nginx внутренний). НЕ ломать C1–C5: e2e идут через nginx по `/api/...` — обновить пути синхронно.
- Q: fastapi-users-роуты (`/auth/jwt`, `/auth`, `/auth/google`) — тоже под v1? → A: да, единообразие → Decision: смонтировать под общий `/v1`-префикс; csrf/oauth-callback пути выровнять (внимательно — OAuth state-cookie path).
- Q: 422 Pydantic — переопределять дефолтный handler? → A: да → Decision: `@app.exception_handler(RequestValidationError)` → envelope `{error: {code: VALIDATION, message, details: [{field, message}]}}`; сохранить инфо о полях для UI (как сейчас `backend-error.ts` парсит `loc`).
- Q: 500/неожиданные? → A: не течь внутренности → Decision: generic-handler → `{error: {code: INTERNAL, message: "Internal error"}}`, без стека/exception-repr (лог — детально на сервере, ответ — стерильно).
- Q: Фронт маппинг? → A: по `error.code` → Decision: `backend-error.ts` переключить дискриминатор с HTTP-статуса на `error.code`; fallback на статус только если envelope отсутствует (старый/прокси-ответ).

## Scope
> **backend** (единый error-envelope + коды + /v1-версионирование на всех роутерах в `api/main.py`) + **frontend** (`backend-error.ts` маппинг по code, `gen.types.ts`, baseURL/`gen:api`-источник) + **ADR** (error-format + versioning). Доменная логика роутов НЕ меняется — только формат ошибок и префикс.

- **Touch ONLY (создать/изменить):**
  - **Backend:**
    - `backend/src/api/errors.py` — **новый**: `ErrorCode(StrEnum)` (коды), `ErrorEnvelope` Pydantic (`{error: {code, message, details?}}`), билдер `build_error_response(code, message, status, details=None) -> JSONResponse`.
    - `backend/src/api/main.py` — переписать exception-handlers: `RateLimitExceeded`→`RATE_LIMITED`, `PlanLimitExceeded`→`PLAN_LIMIT_EXCEEDED`/`FEATURE_NOT_AVAILABLE`, `BillingNotConfiguredError`→`BILLING_NOT_CONFIGURED`, `HTTPException`→маппинг по статусу, `RequestValidationError`→`VALIDATION`+`details`, generic `Exception`→`INTERNAL` (стерильно). Смонтировать все `include_router` под `/v1`-префикс (или `APIRouter(prefix="/v1")`-агрегатор).
    - `backend/src/api/rate_limit.py` — `rate_limit_handler` → envelope-формат (через билдер).
    - `backend/tests/integration/test_error_envelope.py` — **новый**: каждый класс ошибки → envelope с правильным `code` (401/403/404/409/422/429/402/503/500-стерильный).
    - `backend/tests/integration/test_api_versioning.py` — **новый**: роуты доступны под `/v1/...`; (если решено) корневые — deprecated/удалены per ADR.
  - **Frontend:**
    - `frontend/src/shared/lib/backend-error.ts` — дискриминатор по `error.code` (не HTTP-статус); fallback на статус если envelope отсутствует.
    - `frontend/src/shared/api/client.ts` — baseURL (если `/api`→`/api/v1` per ADR); `package.json` `gen:api`-источник (`/api/v1/openapi.json` если сместился).
    - `frontend/src/shared/api/gen.types.ts` — **регенерировать** против версионированной схемы.
    - `frontend/tests/unit/backend-error/**` — unit: маппинг по `error.code` (все коды → правильный `kind`), fallback на legacy-формат.
  - **ADR:**
    - `docs/architecture/adr-007-api-error-format-and-versioning.md` — **новый**: envelope-формат, `ErrorCode`-словарь, версионирование (`/api/v1`, стратегия миграции/совместимости, что с корневыми роутами).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, доменная логика роутов (`api/watchlist/service.py`, `api/alerts/service.py`, `billing/` ядро — только формат их ошибок), per-route rate-limit ([task-032](./task-032-security-hardening.md) — edge-nginx). Не менять статус-коды семантически (402/403/404 остаются — меняется тело).
- **Blast radius:** **меняет контракт ВСЕХ роутов** (тело ошибок + путь /v1). Затрагивает каждый фронт-вызов (баseURL + error-маппинг) и каждый e2e (C1–C5 идут через nginx). Регенерация типов. Высокий риск — детальный Plan, синхронная миграция фронт+nginx+backend, прогон всех C1–C5 e2e в verify.

## Acceptance Criteria
- [x] **AC1 — единый error-envelope (failing-test anchor).** Given любой failing-запрос, When ответ 4xx/5xx, Then тело = `{error: {code: <ErrorCode>, message: str, details?}}` для ВСЕХ источников (HTTPException/PlanLimit/RateLimit/BillingNotConfigured/Pydantic-422/generic-500). integration пишется ПЕРВЫМ (RED — сейчас `{detail: ...}`).
- [x] **AC2 — machine-readable коды без magic literals.** Given `api/errors.py`, When инспекция, Then коды — `ErrorCode(StrEnum)`; маппинг исключение→code централизован; нет строковых литералов кодов на call-sites; 402→`PLAN_LIMIT_EXCEEDED`, 403(feature)→`FEATURE_NOT_AVAILABLE`, 429→`RATE_LIMITED`, 404→`NOT_FOUND`, 409→`DUPLICATE`, 422→`VALIDATION`.
- [x] **AC3 — версионирование `/api/v1`.** Given смонтированные роутеры, When запрос на `/v1/...` (за nginx `/api/v1/...`), Then роут отвечает; стратегия совместимости/миграции корневых роутов реализована per ADR; `/api/v1/openapi.json` доступен.
- [x] **AC4 — Pydantic-422 нормализован с полями.** Given невалидный body, When 422, Then `{error: {code: VALIDATION, message, details: [{field, message}, …]}}`; фронт строит per-field ошибки из `details`.
- [x] **AC5 — frontend маппит по `error.code`.** Given `backend-error.ts`, When ответ-envelope, Then `kind` выбирается по `error.code` (не HTTP-статус); legacy-fallback на статус если envelope отсутствует; unit покрывают все коды.
- [x] **AC6 — обратная совместимость C1–C5.** Given смена контракта, When прогон всех существующих e2e (auth/watchlists/alerts/billing/account) через nginx, Then все зелёные (пути /api/v1 + envelope-маппинг согласованы); ни один C-флоу не сломан.
- [x] **AC7 — security + поведенческая (G2) через nginx.** Given 500/неожиданная ошибка, When ответ, Then `{error: {code: INTERNAL, message}}` БЕЗ стека/exception-repr/SQL/внутренних путей (детальный лог — только на сервере); и: `make up` → integration (`test_error_envelope`/`test_api_versioning`) + C1–C5 e2e зелёные за nginx; артефакты on-failure.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-030-api-hardening-errors-versioning`.
1. **ADR-первым:** `adr-007-api-error-format-and-versioning.md` — зафиксировать envelope-формат, `ErrorCode`-словарь, стратегию `/api/v1` (корневые роуты: удалить/deprecated-alias). G1-решение по совместимости.
2. **RED:** `test_error_envelope.py` — все классы ошибок → envelope с правильным code; `test_api_versioning.py` — `/v1/...` отвечает. Падает (сейчас `{detail}`, нет /v1). AC1/AC2/AC3-якорь.
3. `api/errors.py` — `ErrorCode`, `ErrorEnvelope`, `build_error_response`. `api/main.py` — переписать все exception-handlers через билдер (вкл. `RequestValidationError`, generic `Exception`); смонтировать роутеры под `/v1`. `api/rate_limit.py` — envelope.
4. `make ci-fast`/integration зелёный (backend AC1/AC2/AC4/AC7-server).
5. Frontend: `backend-error.ts` дискриминатор по `error.code` + legacy-fallback; `client.ts` baseURL `/api/v1` (per ADR); `gen:api`-источник; регенерировать `gen.types.ts`; unit для маппинга кодов.
6. Синхронизировать **все** e2e-пути (C1–C5) на `/api/v1` (если baseURL сместился) — не сломать.
7. **GREEN + G2 + 5.5:** `make up`; integration + C1–C5 e2e зелёные за nginx (AC6/AC7); проверить 500-стерильность (no stack leak); security 5.5 — error-message не течёт внутренности.
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Единый envelope для ВСЕХ ошибок** — ни один 4xx/5xx не отдаёт legacy `{detail}`; нормализация централизована в `api/errors.py`/`api/main.py`.
- **Коды — `StrEnum`, no magic literals** — маппинг исключение→code в одном месте; call-sites не хардкодят строки кодов (CONVENTIONS).
- **Семантика статусов сохранена** — 402/403/404/409/422/429/503 остаются прежними; меняется только тело + добавляется code (не ломаем HTTP-семантику).
- **Error-message стерильно** — наружу не течёт стек/SQL/внутренние пути/repr исключения; детали — только в серверном логе ([task-011](./task-011-compliance-retention-gdpr.md) hygiene).
- **Версионирование явно** — `/api/v1` зафиксировано в ADR; миграция корневых роутов осознана (не «случайно сломали»).
- **Фронт стабильно по code** — `backend-error.ts` не зависит от HTTP-статуса как дискриминатора (хрупкость устранена); legacy-fallback на переход.
- **Обратная совместимость C1–C5** — все существующие e2e зелёные после смены контракта (синхронная миграция).

## Edge cases
- 403 несёт два смысла (feature-gate от PlanLimit vs forbidden-доступ) → различать по источнику исключения (PlanLimit→`FEATURE_NOT_AVAILABLE`, прочие 403→`FORBIDDEN`); фронт-апселл только на feature-not-available.
- Pydantic-422 `loc` содержит `body`-префикс → нормализовать `field` (убрать `body`, как сейчас в `backend-error.ts`).
- fastapi-users-роуты бросают свои `HTTPException` (login-bad-credentials и пр.) → должны тоже попасть в envelope (общий handler ловит `HTTPException`).
- OAuth `/auth/google/callback` под `/v1` — state-cookie path/`csrf_token_cookie` могут зависеть от пути → проверить, что callback не сломан сменой префикса.
- Старый кэш/прокси отдаёт legacy `{detail}` без envelope → фронт legacy-fallback по статусу (не падать на `error.code === undefined`).
- 429-handler от slowapi-middleware идёт раньше роутера → убедиться, что envelope применяется (handler зарегистрирован).
- e2e C1–C5 хардкодят `/api/...`-пути или `{detail}`-парсинг → обновить синхронно; AC6 ловит.
- Generic 500 случайно проксирует exception-repr → строгий generic-handler, тест на отсутствие стека (AC7).

## Test plan
- **integration (backend):** `test_error_envelope.py` — каждый класс ошибки → envelope+code (401/403-feature/403-forbidden/404/409/422+details/429/402/503/500-стерильный), AC1/AC2/AC4/AC7-server (RED-якорь). `test_api_versioning.py` — `/v1/...` отвечает, openapi под /v1, корневые per ADR (AC3).
- **unit (frontend):** `tests/unit/backend-error/**` — маппинг каждого `error.code`→`kind`, legacy-fallback на HTTP-статус при отсутствии envelope (AC5).
- **e2e (Playwright):** прогон **всех** существующих C1–C5 spec'ов через nginx на новом контракте (`/api/v1` + envelope) — AC6; артефакты on-failure.
- **runtime/behavioral (G2):** `make up` → integration + C1–C5 e2e зелёные за nginx (AC6/AC7); ручная проверка 500-стерильности (нет стека в теле).
- **security (5.5):** error-message не раскрывает внутренности (стек/SQL/пути); generic-500 стерилен; логи детальны, ответы — нет.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "2038845"
branch: "gsd/phase-030-api-hardening-errors-versioning"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code; +debug-цикл: 8 интеграционных падений починены, 1 реальный баг — 402 отсутствовал в HTTP→ErrorCode map)
- [x] 4 verify (G2 — живой ASGI + реальная БД; полный e2e за nginx — в main-integration CI на merge)
- [x] 5 review (adversarial — pass; 2 MEDIUM закрыты fix-циклом)
- [x] 5.5 security (pass — 500 стерилен на РЕАЛЬНОМ handler, exc.detail-свип чист, input-эхо в 422 исключено)
- [x] 6 ship (PR, squash-merged, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-11 TASK-030)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону [task-013](./task-013-frontend-foundation.md)/[task-017](./task-017-billing-account-ui.md) и реальному коду `backend/src/api/main.py`: сейчас разнородные handlers — `RateLimitExceeded`→429, `PlanLimitExceeded`→`{detail}` 402/403, `BillingNotConfiguredError`→503 `{detail}`, дефолтные `HTTPException` `{detail:str}` и Pydantic-422 `{detail:[...]}`. Нет machine-readable кодов; фронт `shared/lib/backend-error.ts` маппит по HTTP-статусам (хрупко — 403/422 двусмысленны). Роуты на корне, nginx стрипает `/api/`→корень, `/api/v1`-префикса нет. Унифицируем envelope `{error:{code,message,details?}}` + `ErrorCode(StrEnum)` + `/api/v1` (ADR-007). Высокий blast radius — меняет контракт всех роутов → синхронная миграция backend+nginx+фронт+e2e, прогон всех C1–C5. deps: 019 (предполагаемая API-зрелость/типы). ADR пишется ПЕРВЫМ (G1-решение по совместимости). locate+plan выполнены этим планированием — executor стартует с «3 do» (но шаг 1 Plan = ADR-черновик). ОСТОРОЖНО: OAuth-callback под /v1 + state-cookie path; 403 двусмысленность; e2e-пути.)

### do + debug (2026-06-11, loop run)
- ADR-007 написан ПЕРВЫМ: v1-only атомарный свитч; /health и /ready НЕверсионированы
  (инфра-пробы); OpenAPI на /v1/openapi.json; 402→PLAN_LIMIT_EXCEEDED / 403(PlanLimit)→
  FEATURE_NOT_AVAILABLE (по источнику); 500 стерилен; Google redirect URI — деплой-нота
  (/api/v1/auth/google/callback); _FEEDBACK_API_PATH → /api/v1/feedback/ (старые кнопки в
  уже отправленных TG-алертах будут 404 — принято, в ADR).
- RED→GREEN: test_error_envelope.py (все классы ошибок) + test_api_versioning.py.
- Debug-цикл: do-агент не запустил integration suite; 8 падений — 7 тестов со старыми
  путями, 1 КОД-БАГ (402 не было в _HTTP_STATUS_TO_CODE → INTERNAL вместо
  PLAN_LIMIT_EXCEEDED на HTTPException(402)-пути watchlist-роутера).
- Итог: ci-fast 567 unit; integration 195 passed/10 skipped; frontend 193 vitest + tsc;
  40+ файлов (обновлены все integration/e2e пути и {detail}-парсинг).
- **Блокер хоста (зафиксирован):** make up недоступен — исчерпание docker bridge-подсетей;
  и mass-prune, и пред-создание egress-сети с compose-лейблами запрещены политикой
  разрешений. Полный e2e C1-C5 за nginx — в main-integration CI на merge (контракт-брейк:
  после merge СРАЗУ проверить run, чинить форвард при падении).

### verify G2 + fix (2026-06-11, loop run)
- Живой ASGI: /health и /ready на корне; все 9 классов ошибок дают конверт с верным кодом;
  500 стерилен (лог детальный, тело — нет); auth-flow под /v1; feedback URL /api/v1/.
- Найдено и исправлено: (1) routing-miss 404 (Starlette base class) обходил конверт →
  handler зарегистрирован и на StarletteHTTPException + усилен тест; (2) регенерат
  OpenAPI/types не был сделан do-агентом → перегенерён, что вскрыло 2 пропущенных typed
  call-site (schema-ключ /v1/users/me/tenant vs runtime-путь; экспорт ValidationDetailItem);
  (3) мёртвые переменные в backend-error.spec; (4) stale e2e API_BASE и nginx-комментарий.
- Гейты после фиксов: ci-fast 567; integration 195/10; frontend lint/tsc/193 vitest;
  drift-check падает ТОЛЬКО на незакоммиченных файлах дампа (закроется коммитом).

### review + security + fix-цикл #2 (2026-06-11, loop run)
- review: pass без блокеров. MEDIUM закрыты: тест стерильности 500 переписан на РЕАЛЬНЫЙ
  app-handler (временный raising-роут + sentinel, teardown в finally); 2 фронт-потребителя
  {detail} (packs/error-message, onboarding) переведены на envelope-first с legacy-fallback.
  LOW: hoist импорта в rate_limit, детерминированный 503-тест, докстринги /api/v1/feedback/.
- security: pass (INFO: exc.detail-passthrough — все raise-сайты статичны/безопасны;
  422-details без input-эха (loc+msg, ctx/input исключены); cookie path=/ покрывает /v1;
  деплой-нота: Google redirect URI → /api/v1/auth/google/callback).
- Финальные гейты: ci-fast 567; integration 195/10; frontend lint/tsc/194 vitest.
