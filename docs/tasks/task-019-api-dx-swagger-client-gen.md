---
id: TASK-019
title: API DX — Swagger gating + офлайн OpenAPI client-gen + удаление чужих error-codes
status: done             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "bcd419764b1e866251daa706d51a6a215af1119a"
branch: "gsd/phase-019-api-dx-swagger-client-gen"
tags: [epic-d, backend, frontend, dx, openapi]
---

# TASK-019 — API DX (Epic D)

> Три DX-улучшения вокруг OpenAPI-контракта. (1) Swagger/Redoc/`openapi.json` за флагом `SWAGGER_ENABLE` (dev on, prod off) — сейчас `FastAPI(title="TrendPulse API")` создаётся без настройки docs-путей, т.е. схема открыта в проде. (2) Офлайн-дамп OpenAPI (`make gen-openapi`) дампит `app.openapi()` в файл БЕЗ поднятия сервера; фронтовый `gen:api` берёт схему из дампа (не из живого `localhost`); drift-check в `make ci` (регенерь типы → `git diff` пусто, иначе fail). (3) Удалить `frontend/src/shared/lib/error-codes.ts` (чужие PostBolt-коды) и переписать `resolveErrorMessage` в `client.ts` inline (fallback на backend-message/generic). Бизнес-логику роутов НЕ трогаем.

## Context

Backend `backend/src/api/main.py:44` создаёт `app = FastAPI(title="TrendPulse API")` без `docs_url`/`redoc_url`/`openapi_url` — дефолтные `/docs`, `/redoc`, `/openapi.json` открыты всегда, включая prod (раскрытие полной схемы наружу за nginx). Конфиг — `backend/src/config.py` (`class Settings(BaseSettings)`, pydantic-settings), туда добавляется флаг.

Фронт сейчас регенерит типы из ЖИВОГО стека: `frontend` `gen:api` = openapi-typescript против `http://localhost/api/openapi.json` (см. task-013 learnings — `gen:api → http://localhost/api/openapi.json`). Это требует поднятого `make up` и не воспроизводимо в CI без стека. Нужен офлайн-дамп схемы из `app.openapi()` (FastAPI собирает её из роутов без сети) в коммитимый файл, и генерация типов из него.

`frontend/src/shared/lib/error-codes.ts` — чужие коды реф-проекта PostBolt (известный долг из task-013 learnings). `client.ts:83` зовёт `resolveErrorMessage(data?.code, extractMessage(data))`; `shared/lib/index.ts:3` реэкспортит `ERROR_CODE_MESSAGES, resolveErrorMessage`. TrendPulse backend свои коды так не отдаёт — карта мёртвая и вводит в заблуждение.

Конвенции (`../CONVENTIONS.md`): `make` — единая точка входа, no magic literals (пути docs/дампа — константы/settings), секреты только из env. mypy strict на backend.

## Goal

После задачи: при `SWAGGER_ENABLE=false` (prod-дефолт) `/docs`, `/redoc`, `/openapi.json` дают `404`; при `true` (dev) — `200`. `make gen-openapi` пишет дамп `app.openapi()` в файл без запуска uvicorn. `gen:api` читает дамп → `gen.types.ts`; в `make ci` есть drift-check, падающий при расхождении сгенерённых типов с коммитом. `frontend/src/shared/lib/error-codes.ts` удалён, `resolveErrorMessage` живёт inline в `client.ts` (или `backend-error.ts`) без карты кодов, реэкспорты в `shared/lib/index.ts` поправлены; нет импортов `error-codes` нигде в `src/`; `build`/`tsc`/`lint` зелёные.

## Discussion
<!-- durable record of clarifications; обратимы. -->
- Q: Где гейтить docs? → A: на уровне конструктора `FastAPI(...)` → Decision: `Settings.swagger_enable: bool = False`; в `main.py` `docs_url`/`redoc_url`/`openapi_url` = строковый путь если флаг включён, иначе `None` (FastAPI так отключает эндпоинт). `development/env/deploy.env` — `SWAGGER_ENABLE=true` для dev; prod-env флаг не ставит (дефолт `False`).
- Q: Дамп OpenAPI — как без сервера? → A: `app.openapi()` строит схему синхронно из роутов → Decision: маленький модуль/скрипт (напр. `backend/scripts/dump_openapi.py`) импортит `app`, пишет `json.dumps(app.openapi())` в файл (путь — константа, напр. `frontend/src/shared/api/openapi.json` или `docs/api/openapi.json`); `make gen-openapi` его зовёт. Дамп НЕ зависит от `SWAGGER_ENABLE` (это статический контракт, не runtime-эндпоинт).
- Q: Откуда `gen:api` берёт схему? → A: из коммитнутого дампа → Decision: `package.json` `gen:api` = openapi-typescript против файла-дампа, не `http://localhost`. Воспроизводимо в CI без `make up`.
- Q: Drift-check? → A: контракт не должен молча разъезжаться → Decision: `make` цель (или шаг в `ci`): `gen-openapi` + `gen:api`, затем `git diff --exit-code` по дампу и `gen.types.ts` — непусто ⇒ fail с подсказкой «перегенери и закоммить».
- Q: Чем заменить карту кодов? → A: backend отдаёт человекочитаемый `detail`/message → Decision: inline `resolveErrorMessage` берёт backend-сообщение, иначе generic-фразу; сигнатуру вызова можно упростить (`data?.code` больше не нужен) — поправить и call-site в `client.ts`.
- Q: Безопасность? → A: раскрытие схемы — security-relevant → Decision: шаг 5.5 применим; проверить, что prod реально отдаёт `404` на docs-путях через nginx.

## Scope
> Backend: гейт docs + дамп-скрипт + make-цели. Frontend: источник `gen:api` + удаление error-codes + inline `resolveErrorMessage`. Бизнес-логику роутов и контракт ответов НЕ меняем.

- **Touch ONLY (создать/изменить):**
  - `backend/src/config.py` — `swagger_enable: bool = False` в `Settings`.
  - `backend/src/api/main.py` — `FastAPI(..., docs_url=..., redoc_url=..., openapi_url=...)` вычисляются из `settings.swagger_enable` (пути-константы либо `None`).
  - `backend/scripts/dump_openapi.py` — **новый** скрипт: импорт `app`, дамп `app.openapi()` в файл-дамп (путь-константа).
  - `Makefile` — `gen-openapi` (дамп), drift-check шаг (в `ci`/`ci-fast` — без подъёма стека).
  - `development/env/deploy.env` — `SWAGGER_ENABLE=true` (dev).
  - `backend/tests/unit/test_swagger_gating.py` — **новый**: флаг off → docs/openapi-пути `None`/`404`; on → заданы. (через `TestClient` без сети).
  - `frontend/package.json` — `gen:api` источник = файл-дамп (не `http://localhost`).
  - `frontend/src/shared/api/openapi.json` (или `docs/api/openapi.json`) — **новый** коммитнутый дамп.
  - `frontend/src/shared/api/client.ts` — `resolveErrorMessage` inline (backend-message/generic), правка call-site `:83`.
  - `frontend/src/shared/lib/error-codes.ts` — **удалить**.
  - `frontend/src/shared/lib/index.ts` — убрать реэкспорт `ERROR_CODE_MESSAGES`/старого `resolveErrorMessage` (`:3`).
  - `frontend/src/shared/api/gen.types.ts` — **регенерировать** из дампа.
  - `docs/tasks/tasks-index.md` — на ship (оркестратор).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, бизнес-логику роутов (`api/alerts`, `api/watchlist`, `api/auth`, `api/billing`), контракт Pydantic-ответов, `landing/**`, scorer/pipeline/collector.
- **Blast radius:** изменение поведения docs-эндпоинтов (prod → `404`); смена источника `gen:api` затрагивает downstream-генерацию типов (контракт типов для всего фронта); удаление `error-codes` меняет текст ошибок в UI (fallback на backend-message). Дамп — новый коммитимый артефакт-контракт; drift-check добавляет gate в CI.

## Acceptance Criteria
- [ ] **AC1 — Swagger gating (failing-test anchor).** Given `SWAGGER_ENABLE=false`, When запрос `/docs`/`/redoc`/`/openapi.json`, Then `404`; Given `=true`, When те же запросы, Then `200`. `test_swagger_gating.py` пишется ПЕРВЫМ (RED).
- [ ] **AC2 — офлайн-дамп без сервера.** Given `make gen-openapi`, When выполнено без `make up`/uvicorn, Then файл-дамп записан и равен `app.openapi()`; процесс не открывает сокет.
- [ ] **AC3 — `gen:api` из дампа + drift-check.** Given `gen:api` берёт дамп (не `localhost`), When `make ci` запускает gen-openapi+gen:api+`git diff --exit-code`, Then при незакоммиченном дрейфе — fail; при согласованности — pass.
- [ ] **AC4 — error-codes удалён.** Given удалён `frontend/src/shared/lib/error-codes.ts`, When `grep -r "error-codes"` по `frontend/src`, Then 0 импортов; `resolveErrorMessage` inline (backend-message/generic); `shared/lib/index.ts` без мёртвых реэкспортов; `build`/`tsc`/`lint` зелёные.
- [ ] **AC5 — тесты + поведение.** Given юнит `test_swagger_gating.py` зелёный (AC1) и фронт build/tsc/lint зелёные (AC4), When прогон, Then оба проходят; покрытие нового backend-кода учтено.
- [ ] **AC6 — G2 через nginx.** Given `make up` с `SWAGGER_ENABLE` НЕ выставленным (prod-подобно), When `curl /api/docs` и `/api/openapi.json` через edge, Then `404`; с `SWAGGER_ENABLE=true` (dev) → `200`. Наблюдаемо за nginx.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-019-api-dx-swagger-client-gen`.
1. **RED:** `backend/tests/unit/test_swagger_gating.py` — off→404, on→200 (через `TestClient`, монкипатч settings). Падает (пути всегда открыты). AC1-якорь.
2. `config.py` `swagger_enable`; `main.py` — `docs_url/redoc_url/openapi_url` из флага (пути-константы или `None`). `make ci-fast` зелёный (AC1 GREEN).
3. `backend/scripts/dump_openapi.py` + `make gen-openapi`; прогнать — файл-дамп создан без сервера (AC2).
4. `frontend/package.json` `gen:api` → дамп; регенерить `gen.types.ts`; добавить drift-check в `make ci` (gen + `git diff --exit-code`). (AC3).
5. Удалить `error-codes.ts`; inline `resolveErrorMessage` в `client.ts` (правка call-site `:83`); поправить `shared/lib/index.ts`; `tsc`/`lint`/`build` зелёные, grep чисто (AC4).
6. **G2:** `make up` — `curl` docs/openapi за nginx: prod-подобно `404`, dev `200` (AC6).
7. 5.5 security: подтвердить, что prod не светит схему. Обновить `tasks-index.md` на ship.

## Invariants
- **Docs закрыты по умолчанию** — `swagger_enable` дефолт `False`; включение только явным env (dev). Никаких docs-путей наружу в проде.
- **Дамп офлайн и детерминирован** — `app.openapi()` без сети; дамп коммитится, drift-check держит его в синхроне с роутами.
- **Типы из дампа, не из живого стека** — `gen:api` воспроизводим в CI без `make up`.
- **No magic literals** — пути docs/дампа — именованные константы/settings; `SWAGGER_ENABLE` — env.
- **Контракт ответов не меняется** — удаление error-codes меняет только текст в UI (fallback), не форму ответа backend.
- **Бизнес-логика роутов нетронута** — только конфигурация app и DX-инструменты.

## Edge cases
- `app.openapi()` кэширует схему в `app.openapi_schema` — дамп-скрипт должен брать свежую (учесть кэш, чтобы не писать устаревшее).
- `openapi_url=None` отключает и `/docs` (Swagger UI грузит схему оттуда) — проверить, что и UI, и JSON оба `404`.
- nginx может кэшировать/проксировать docs-путь — AC6 проверяет реальный `404` за edge, не только в app.
- Drift-check может ложно падать из-за нестабильной сортировки ключей JSON — дампить с `sort_keys`/стабильным форматом, чтобы diff был детерминирован.
- `resolveErrorMessage` вызывается с `data?.code` на одном call-site — не оставить «висящий» аргумент после удаления карты (tsc поймает).
- Backend без `detail`/message в ошибке → generic-фраза, не пустая строка/`undefined`.

## Test plan
- **unit (backend):** `test_swagger_gating.py` — off→404 (docs/redoc/openapi), on→200; флаг управляет конструктором app.
- **offline-gen (backend):** `make gen-openapi` без стека — файл-дамп создан, равен `app.openapi()`, сокет не открыт (AC2).
- **build/typecheck (frontend):** `tsc`/`build`/`lint` после удаления error-codes + регенерации; grep `error-codes` = 0 (AC4).
- **ci drift:** `make ci` — gen+`git diff --exit-code` падает на искусственном дрейфе, проходит на согласованном (AC3).
- **runtime/behavioral (G2):** `make up` → `curl` docs/openapi за nginx (prod 404 / dev 200) (AC6).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "bcd419764b1e866251daa706d51a6a215af1119a"
branch: "gsd/phase-019-api-dx-swagger-client-gen"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior через nginx/стек)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (если применимо)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-013/016 и проверенным путям: `main.py:44` создаёт `FastAPI(title="TrendPulse API")` без docs-настроек → гейтим за `Settings.swagger_enable`; `gen:api` сейчас бьёт по `http://localhost/api/openapi.json` (task-013 learnings) → переводим на офлайн-дамп `app.openapi()` + drift-check в `make ci`; `frontend/src/shared/lib/error-codes.ts` — чужие PostBolt-коды (task-013 долг), `client.ts:83` зовёт `resolveErrorMessage(data?.code, ...)`, `index.ts:3` реэкспортит — удаляем карту, переписываем inline. deps: 013 (фронт-фундамент, gen:api, error-codes-долг). Security 5.5 применима (раскрытие схемы). locate+plan выполнены — executor стартует с «3 do».)

### do (loop-019, 2026-06-09)
RED→GREEN выполнен. Создано: `backend/tests/unit/test_swagger_gating.py` (RED-якорь AC1: off→404/on→200 через reload модуля + TestClient), `backend/scripts/dump_openapi.py` (офлайн-дамп `app.openapi()` с `app.openapi_schema=None`, детерминированный `json.dumps(sort_keys=True, indent=2)+\n`, путь от `__file__`), `frontend/src/shared/api/openapi.json` (коммитимый дамп 44 KB). Изменено: `config.py` (`swagger_enable: bool = False`), `api/main.py` (константы `_DOCS_URL/_REDOC_URL/_OPENAPI_URL` + `_DocsUrls` TypedDict + pure `_docs_urls()` + `FastAPI(..., **_docs_urls(get_settings().swagger_enable))`), `Makefile` (`gen-openapi`/`gen-types`/`openapi-drift-check` + шаг в `ci:` + PHONY/help), `frontend/package.json` (`gen:api` источник = дамп-файл, не localhost), `client.ts` (inline `resolveErrorMessage(fallback)` + `GENERIC_ERROR_MESSAGE`, убрано поле `ErrorBody.code`), `shared/lib/index.ts` (убран реэкспорт), `gen.types.ts` (перегенерён из дампа). Удалён `frontend/src/shared/lib/error-codes.ts`. Проверки: `make ci-fast` зелёный (244 unit passed); frontend lint+tsc+build зелёные; `grep error-codes frontend/src` чисто; gen идемпотентен.

**Отклонение (обоснованное):** Scope называл `development/env/deploy.env` для dev-флага, но этот файл gitignore'нут (ansible-rendered) — правка в нём эфемерна (теряется при `make ansible-unpack`). По CONVENTIONS (ansible = единый источник non-secret env) флаг заведён в КОММИТИМОМ источнике: `ops/ansible/roles/env/templates/deploy.env.j2` (`SWAGGER_ENABLE={{ swagger_enable }}`), `group_vars/all.yml` (`swagger_enable: "true"`, dev), `group_vars/prod.yml` (`swagger_enable: "false"`, prod override). Локальный рендер deploy.env тоже обновлён (для verify). Это закрывает invariant «docs закрыты в проде» на уровне IaC, а не только code-default.

### verify (G2, loop-019, 2026-06-09)
- Backend gates: `make ci-fast` зелёный — ruff format/check OK, mypy strict «no issues in 102 files», 244 unit passed (вкл. 2 `test_swagger_gating`).
- AC6 за nginx (после `make build` — образ надо пересобрать под новый код): **dev (SWAGGER_ENABLE=true) → docs/redoc/openapi = 200; prod-подобно (=false) → все 404** (подтверждено access-логами nginx, не кэш). Ключевое поведенческое доказательство.
- Frontend: lint+tsc+build зелёные; `grep error-codes src` = CLEAN; Playwright e2e **28 passed** за nginx (auth/alerts/watchlists/billing/smoke) — удаление error-codes/inline resolveErrorMessage не сломало флоу.
- AC2: `make gen-openapi` сервер не поднимает; генерация детерминирована (двойной прогон идентичен).
- AC3: drift-check корректно падает при дрейфе; станет зелёным после коммита `openapi.json`+`gen.types.ts` на ship (проверить `make openapi-drift-check` post-commit).
- Integration не применим: диф не трогает БД/репозитории/роуты/Celery (только config app, DX-скрипты, фронт error-handling).
- Gotcha: локальный Docker-образ кэшируется — без `make build` новый `swagger_enable` не виден в контейнере (`Settings extra=ignore` молча глотает env). CI пересобирает образ, локально нужен `make build` перед G2.

### review + security (loop-019, 2026-06-09)
**Security (opus): блокеров НЕТ — можно мержить.** Инвариант «docs закрыты в проде» защищён в глубину: code-default `swagger_enable=False` + IaC-оверрайд `prod.yml=false` + template-рендер; gating через `_docs_urls`→`docs_url=None` даёт реальный 404 (роуты не регистрируются). Dummy-секреты `=dump` — не реальные. Коммитимый `openapi.json` проверен на утечки: нет `servers`/хостов/секретов/traceback; `format:password` — write-only маркеры; `telegram_bot_token_masked` не светит полный токен; example-коды (`LOGIN_BAD_CREDENTIALS` и т.п.) — стандартные fastapi-users доки. Inline `resolveErrorMessage` — улучшение (убрана чужая карта кодов), fallback не светит стектрейсы. `dump_openapi.py` — без сетевого I/O и path-traversal (путь статичен от `__file__`).
**Review (opus): 0 CRITICAL, 2 HIGH — оба ИСПРАВЛЕНЫ.**
- HIGH#1 (mypy не покрывал `scripts/dump_openapi.py` в CI) → добавлен шаг `$(UV) mypy scripts/dump_openapi.py` в `ci` и `ci-fast` (mypy на скрипте зелёный).
- HIGH#2 (`git diff --exit-code` слеп к untracked `openapi.json` → drift-check мог молча пропустить дрейф дампа) → `openapi-drift-check` переписан на `git status --porcelain` (ловит и untracked, и modified).
- MEDIUM (gen-types в `make ci` требует node/npm в окружении) — non-blocking: это забота TASK-021 (CI foundation), CI-джоба должна ставить и uv, и `npm ci` для frontend. Зафиксировано в learnings.
- LOW (print в скрипте — намеренный stdout для make; дублирование dummy-env) — приняты как есть.
Non-blocking follow-up (предложение security): ansible-assert, что `prod.yml.swagger_enable == "false"`, чтобы будущая правка group_vars не открыла схему — кандидат в TASK-032 (security hardening).
