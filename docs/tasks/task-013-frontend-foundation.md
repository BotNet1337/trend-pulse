---
id: TASK-013
title: Frontend foundation — SPA scaffold (дизайн-система, API-клиент к TrendPulse, типы, e2e-харнесс, Docker)
status: review           # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "155eb923ff51ba8b75b5672c79a92f50403548ed"
branch: "gsd/phase-013-frontend-foundation"
tags: [frontend, scaffold, design-system, api-client, e2e]
---

# TASK-013 — Frontend foundation (Epic C · C1)

> Превратить скопированный реф-проект (зрелый FSD React+Vite+TS SPA) в фундамент SPA **TrendPulse**: дизайн-токены/тема/layout/роутинг, API-клиент к ЭТОМУ backend (cookie-auth, baseURL `/api`, `withCredentials: true`), env-конфиг (`VITE_BRAND_NAME=TrendPulse` и пр.), **регенерация типов API против TrendPulse `/openapi.json`** с вычисткой чужих фич реф-проекта (channels/publications/moderation/analytics/OAuth-refresh — не относятся к TrendPulse), Playwright-харнесс (config + первый smoke e2e: приложение грузится, роутинг, 401→`/login`), и Dockerfile + compose-сервис `frontend` по [network-design](../architecture/network-design.md) (статика за edge-nginx). Это база для C2–C5; реальный UI-флоу дёргает этот backend через nginx.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md)) — multi-tenant SaaS; backend (Epic A, task-001..012) **полностью done**. Теперь стартует Epic C (frontend SPA) по [roadmap](../architecture/roadmap.md) §«Epic C». В `apps/trendPulse/frontend/` уже лежит **скопированный проект-эталон** — зрелый FSD-SPA (`app/`, `pages/`, `features/`, `entities/`, `shared/`) с auth-страницами, account/delete, Tailwind, vitest и Playwright-конфигом. Но он от ДРУГОГО продукта: бренд `PostBolt`, фичи channels/publications/moderation/analytics, сгенерённые типы (`shared/api/gen.types.ts`) от чужого OpenAPI (channels/publications/OAuth-refresh). Эта задача делает реф-проект фундаментом именно TrendPulse — без переписывания зрелой инфраструктуры, но с вычисткой чужого домена и перенацеливанием на наш API.

Backend-контракт (источник истины — реальные роуты): cookie-auth через `fastapi-users` (httpOnly-cookie, [task-003](./task-003-auth.md)); baseURL за nginx — `/api`; `GET /users/me/tenant` → `{user_id}` (пока единственный protected-пример; `GET /users/me` добавит [task-014](./task-014-auth-flow-ui.md)). Сеть: наружу торчит только nginx (edge), `frontend` — статика за ним ([network-design](../architecture/network-design.md)).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — `make` единая точка входа; версии образов из `development/version.env`; секреты только из env; no magic literals. Frontend-конвенции вводятся этим эпиком (FSD-раскладка реф-проекта сохраняется).

## Goal

После задачи: `make up` поднимает SPA за nginx по baseURL `/api`; приложение грузится, роутинг работает, неавторизованный запрос к protected-роуту/странице → редирект на `/login` (cookie-auth, `withCredentials: true`); бренд = TrendPulse (env `VITE_BRAND_NAME`); типы API сгенерены из TrendPulse `/openapi.json`, чужие домены реф-проекта (channels/publications/moderation/analytics) удалены, билд и typecheck зелёные без ссылок на удалённое; первый Playwright smoke-e2e зелёный (загрузка, роутинг, 401-redirect через nginx); `frontend` собирается Dockerfile'ом и встаёт compose-сервисом за edge. DoD — Acceptance Criteria ниже.

## Discussion
<!-- durable record of clarifications. Решения по реф-проекту + network-design; обратимы. -->
- Q: Писать SPA с нуля или адаптировать реф-проект? → A: **адаптировать** скопированный реф-проект → Decision: сохраняем зрелую FSD-инфраструктуру (роутинг, providers, shared/api, тема, тесты), меняем бренд/копи и вычищаем чужой домен. Не катаем свой scaffold (паттерн «adopt proven structure», как auth=fastapi-users в backend).
- Q: Откуда брать типы API? → A: из TrendPulse `/openapi.json` → Decision: регенерим `shared/api/gen.types.ts` против `http://<nginx>/api/openapi.json` (FastAPI отдаёт схему); чужие операции (channels/publications/moderation/analytics/OAuth-refresh) исчезают, остаются auth/watchlists/billing/account/users. Генератор — тот же, что использовал реф-проект (зафиксировать в `package.json` script).
- Q: baseURL и транспорт auth? → A: `/api` + cookie → Decision: `shared/api/client.ts` — `baseURL: '/api'`, `withCredentials: true` (httpOnly-cookie ставит backend, JS её не читает); никаких Bearer-токенов в localStorage. nginx проксирует `/api` → `api:8000`.
- Q: Чужие фичи реф-проекта (channels/publications/moderation/analytics)? → A: к TrendPulse не относятся → Decision: удалить их код/тесты/типы в C1 (фундамент должен быть чистым); auth-страницы и account/delete оставляем (адаптация — task-014/017).
- Q: Где живёт `frontend` в сети? → A: статика за edge-nginx ([network-design](../architecture/network-design.md)) → Decision: multi-stage Dockerfile (build → статика), compose-сервис `frontend` в `internal`; nginx отдаёт статику/проксирует. Версии из `development/version.env` (Node-образ), без `latest`.
- Q: env-конфиг? → A: Vite env → Decision: `VITE_BRAND_NAME=TrendPulse`, `VITE_HELP_URL` и пр. — через `development/env/deploy.env` (non-secret) → передаются в билд; секретов на фронте нет (CONVENTIONS).

## Scope
> Затрагивает **только `frontend/`** (+ `development/compose/frontend.yml`, nginx-конфиг для статики, `development/env/deploy.env` фронт-переменные). Backend НЕ трогаем (C1 ничего не добавляет в API — тонкие read-эндпоинты идут в C2/C4/C5).

- **Touch ONLY (создать/изменить):**
  - `frontend/src/shared/config/brand.ts` — дефолт бренда → TrendPulse (env `VITE_BRAND_NAME` остаётся источником, дефолт-fallback меняем с `PostBolt`).
  - `frontend/src/shared/api/client.ts` — подтвердить/выставить `baseURL: '/api'`, `withCredentials: true`; убрать чужую OAuth-refresh-логику (TrendPulse cookie-auth не использует refresh-эндпоинт реф-проекта).
  - `frontend/src/shared/api/gen.types.ts` — **регенерировать** из TrendPulse `/openapi.json`; `package.json` — script генерации (`gen:api`) с источником схемы.
  - `frontend/src/shared/api/types.ts`, `frontend/src/shared/api/index.ts` — выровнять ре-экспорты под новые типы; удалить ссылки на channels/publications/moderation/analytics.
  - `frontend/src/app/router/**`, `frontend/src/app/providers/**` — оставить базовый layout/роутинг/тему; удалить роуты чужих фич; guard-заглушка под `/login`-redirect (полноценный guard — task-014).
  - `frontend/src/shared/config/**`, `frontend/src/shared/components/**`, `frontend/tailwind.config.ts` — дизайн-токены/тема/базовые компоненты под бренд TrendPulse (цвета/типографика — единая система).
  - **Удалить чужой домен:** `frontend/tests/unit/{moderation,publications,analytics,pat,compatibility}/**` и соответствующие `frontend/src/**` модули channels/publications/moderation/analytics (по факту наличия).
  - `frontend/playwright.config.ts` — нацелить на стек за nginx (`baseURL` edge), артефакты (trace/screenshot/video on-failure).
  - `frontend/tests/e2e/smoke.spec.ts` — **новый** первый e2e: приложение грузится, роутинг работает, заход на protected без cookie → редирект на `/login`.
  - `frontend/Dockerfile` — multi-stage (Node build из `version.env` → статика); адаптировать под TrendPulse.
  - `development/compose/frontend.yml` — **новый** compose-сервис `frontend` (сеть `internal`, без публикации портов); подключение к nginx (edge отдаёт статику/проксирует `/api`).
  - `development/provisioning/nginx/nginx.conf` (или его include) — location для статики SPA + проксирование `/api` → `api:8000` (если ещё не покрыто).
  - `development/env/deploy.env` — фронт-переменные (`VITE_BRAND_NAME=TrendPulse`, `VITE_HELP_URL`, …), `development/version.env` — `NODE_VERSION` для билда (если отсутствует).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `backend/**` (C1 не добавляет API), `landing/**` (Epic B — task-018), `docs/**` (кроме `tasks-index.md` на ship). Не реализовывать auth-флоу/watchlists/alerts/billing-экраны (C2–C5). Не вводить секреты на фронт.
- **Blast radius:** задаёт фундамент для всех C-задач (C2 auth, C3 watchlists, C4 alerts, C5 billing): дизайн-система, API-клиент (cookie-auth, baseURL `/api`), типы из TrendPulse OpenAPI, Playwright-харнесс, compose-сервис `frontend` за nginx. Меняет топологию compose (добавляет сервис в edge-отдачу). Тип-регенерация — контракт типов для всех downstream-фич.

## Acceptance Criteria
- [ ] **AC1 — приложение грузится за nginx (failing-test anchor).** Given `make up` (стек за nginx, `frontend` за edge), When Playwright открывает корень приложения через edge-`baseURL`, Then страница рендерится (виден бренд **TrendPulse**, не PostBolt), консоль без фатальных ошибок. Smoke-e2e пишется ПЕРВЫМ (RED — пока бренд/сервис не настроены).
- [ ] **AC2 — роутинг работает.** Given загруженный SPA, When навигация по публичным роутам (`/login`, корень), Then соответствующие страницы рендерятся, 404-роут даёт not-found-страницу.
- [ ] **AC3 — 401 → редирект на `/login`.** Given пользователь без auth-cookie, When заход на protected-страницу (или API `GET /users/me/tenant` → `401`), Then SPA редиректит на `/login` (cookie-auth, `withCredentials: true`); raw-401 пользователю не показывается.
- [ ] **AC4 — типы сгенерены из TrendPulse OpenAPI, чужой домен удалён.** Given `pnpm/npm run gen:api` против `/api/openapi.json`, When typecheck/build, Then `gen.types.ts` содержит TrendPulse-операции (auth/watchlists/billing/account/users), НЕ содержит channels/publications/moderation/analytics; нигде в `src/` нет импортов удалённых модулей; `tsc`/build зелёные.
- [ ] **AC5 — API-клиент cookie-auth, baseURL `/api`.** Given `shared/api/client.ts`, When инспекция конфигурации, Then `baseURL === '/api'` и `withCredentials === true`; нет Bearer-токенов в localStorage; нет чужой OAuth-refresh-логики реф-проекта.
- [ ] **AC6 — Dockerfile + compose-сервис за edge.** Given `make build && make up`, When стек поднят, Then сервис `frontend` собран (multi-stage, Node-версия из `version.env`), стоит в `internal`, портов наружу не публикует; статика отдаётся через nginx (edge), `/api` проксируется на `api`.
- [ ] **AC7 — поведенческая (G2) проверка через nginx.** Given `make up`, When Playwright e2e (`smoke.spec.ts`) гоняется против реального стека за nginx, Then AC1–AC3 наблюдаемы; артефакты (trace/screenshot/video on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit` от текущего HEAD; ветка `gsd/phase-013-frontend-foundation`.
1. **RED:** `frontend/tests/e2e/smoke.spec.ts` — открыть приложение через edge-`baseURL`, ожидать бренд `TrendPulse` + рендер + 401→`/login`. Запустить — падает (бренд PostBolt, сервиса нет). AC1-якорь.
2. `shared/config/brand.ts` — дефолт → TrendPulse; `development/env/deploy.env` — `VITE_BRAND_NAME=TrendPulse`, `VITE_HELP_URL`; тема/токены (`tailwind.config.ts`, `shared/config`) под бренд.
3. `shared/api/client.ts` — `baseURL: '/api'`, `withCredentials: true`; убрать чужую OAuth-refresh-цепочку; guard-redirect на `401` → `/login` (interceptor/router).
4. `package.json` — script `gen:api` (генератор типов из `/api/openapi.json`); регенерировать `shared/api/gen.types.ts`; выровнять `types.ts`/`index.ts`.
5. Вычистить чужой домен: удалить `src/**` и `tests/unit/**` модули channels/publications/moderation/analytics/pat/compatibility; убрать их роуты из `app/router`; `tsc` зелёный (нет битых импортов).
6. `Dockerfile` (multi-stage, Node из `version.env`) + `development/compose/frontend.yml` (сеть `internal`, без портов) + nginx location (статика + proxy `/api`).
7. **GREEN:** `make build && make up`; Playwright smoke зелёный через nginx (AC1–AC3, AC7); typecheck/build зелёные (AC4–AC5); проверить compose-топологию (AC6).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Cookie-auth, baseURL `/api`, `withCredentials: true`** — httpOnly-cookie ставит backend, JS её не читает; никаких Bearer/refresh-токенов в localStorage (контракт task-003).
- **Никаких секретов в бандле** — на фронте только non-secret `VITE_*` (бренд, help-url); секреты не попадают в сборку/логи (CONVENTIONS).
- **Единая дизайн-система** — токены/тема/компоненты реф-проекта переиспользуются под бренд TrendPulse; responsive + базовая a11y задаются здесь для всех C-задач.
- **Реальные данные из backend** — типы сгенерены из TrendPulse `/openapi.json`; никаких ручных «фейковых» типов чужого домена; в проде — реальный API за nginx, не моки.
- **`make` — единая точка входа** — билд/запуск через `make build`/`make up`; версии (Node) из `development/version.env`, без `latest` (CONVENTIONS).
- **FSD-раскладка сохраняется** — `app/`/`pages/`/`features/`/`entities/`/`shared/`; чужой домен удаляется, инфраструктура реф-проекта не переписывается.

## Edge cases
- Реф-проект ссылается на удалённый чужой модуль из общего места (`app/router`, `shared/api/index`) → удалить ссылку, иначе `tsc`/build падает; AC4 это ловит.
- `/openapi.json` за nginx по `/api/openapi.json` (FastAPI mount) — убедиться, что путь доступен через edge; иначе генерация типов читает не ту схему.
- Чужая OAuth-refresh-логика в `client.ts` дёргает несуществующий у TrendPulse эндпоинт → удалить, иначе скрытые 404/циклы на refresh.
- Бренд-fallback `PostBolt` где-то захардкожен помимо `brand.ts` → grep по `PostBolt`, заменить через env/константу (no magic literals).
- `frontend` ошибочно публикует порт наружу → нарушение network-design (только nginx в edge); AC6 проверяет отсутствие published-портов.
- Smoke-e2e гоняется не против nginx, а против dev-сервера Vite → не та поведенческая проверка; `playwright.config.ts` `baseURL` = edge.

## Test plan
- **e2e (Playwright):** `tests/e2e/smoke.spec.ts` — AC1 (загрузка + бренд TrendPulse, RED-якорь), AC2 (роутинг + 404-страница), AC3 (protected без cookie → редирект `/login`). Артефакты on-failure: trace/screenshot/video.
- **build/typecheck:** `make build` + `tsc` — AC4 (типы из TrendPulse OpenAPI, нет channels/publications/moderation/analytics, нет битых импортов), AC5 (клиент cookie-auth/baseURL/withCredentials).
- **runtime/behavioral (G2):** `make up` → Playwright против реального стека за nginx — AC7; ручная проверка compose-топологии (`frontend` в `internal`, без портов, статика через nginx, `/api` проксируется) — AC6.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 6
baseline_commit: "155eb923ff51ba8b75b5672c79a92f50403548ed"
branch: "gsd/phase-013-frontend-foundation"
lock: "loop-013"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — build + Playwright e2e + real behavior через nginx)
- [x] 5 review (auto, adversarial — PASS, 0 blocking; 5 MED/LOW residue-чистка применена)
- [x] 5.5 security (PASS, 0 blocking — cookie-auth/no-secrets verified; open-redirect MED захардненен)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: ["cycle-1: verify G2 fail → SSR-слой реф-проекта (Bearer/refresh/API_URL/COOKIE_SECRET) ронял контейнер → fix: статик-путь (frontend=nginx+Vite dist, без SSR node-сервера) + createRoot вместо hydrateRoot + eslint argsIgnorePattern + удаление visual-спеков чужого домена → re-verify PASS (5/5 smoke e2e зелёные за nginx)"]

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по эталону task-003/004 и контексту: реф-проект в `frontend/` адаптируется под TrendPulse (бренд, cookie-auth `/api`, типы из TrendPulse OpenAPI, вычистка чужого домена), Playwright-харнесс + первый smoke, Dockerfile + compose-сервис за edge-nginx по network-design. Фундамент для C2–C5; deps: 001 (dev env/compose/make), 003 (cookie-auth контракт). locate+plan выполнены этим планированием — executor стартует с шага «3 do».)

### Step 3 do · 4 verify (G2 + debug cycle 1) · loop-013
- **do (TDD):** RED `tests/e2e/smoke.spec.ts` (бренд/роутинг/401→redirect) → бренд PostBolt→TrendPulse (brand.ts/index.html/package.json, env `VITE_BRAND_NAME`); `shared/api/client.ts` подтверждён cookie-auth (`baseURL:/api`, `withCredentials`, без Bearer/refresh, 401→`/auth/sign-in`); `gen.types.ts` регенерирован из дампа TrendPulse `app.openapi()` (14 путей, 0 чужих); удалён чужой домен (channels/publications/moderation/analytics/pat/compatibility/workspaces — src + tests/unit); `Dockerfile`+`development/compose/frontend.yml`+nginx location+`version.env NODE_VERSION`+`deploy.env`. build/tsc зелёные, unit 25/25, AC1 e2e зелёный (preview). Коммит e88aa14.
- **verify G2 FAIL → debug cycle 1:** `make up` падал — do почистил браузерный клиент, но НЕ SSR-серверный слой `frontend/server/**` реф-проекта (Bearer-auth, `refresh.plugin.ts`→`/auth/token/refresh`, env `API_URL`/`COOKIE_SECRET` Zod-required) → ZodError/crashloop. **FIX (решение — упрощение):** статик-путь — frontend-контейнер = `nginx:alpine` + Vite `dist/` (SPA-fallback `try_files`), без node-SSR-сервера → устранены Bearer/refresh/COOKIE_SECRET/API_URL разом (соответствует «статика за edge»). Bonus: `src/app/root.tsx` `hydrateRoot+RouterClient`→`createRoot+RouterProvider` (SSR-гидрация требовала `window.$_TSR`, ронялась в статике); eslint `argsIgnorePattern:'^_'`; удалены visual-спеки чужого домена. Коммиты c458c2d, 94cdbd4.
- **re-verify PASS:** `make build && make up` — стек поднялся (api startup complete, nginx :80, frontend healthy без host-портов); curl за nginx: `/`→200 TrendPulse, `/api/health`→200, `/api/users/me/tenant` без cookie→401, `/api/openapi.json`→200; Playwright smoke **5/5 зелёные** (AC1-AC3, AC7); build/tsc/lint exit 0 (AC4-AC6).

### Step 5 review · 5.5 security · loop-013 (оба PASS, 0 blocking)
- **review (opus, code-reviewer) PASS:** блокирующих нет. Подтверждены инварианты (cookie-auth без Bearer/refresh/localStorage, baseURL `/api`+withCredentials, gen.types только TrendPulse, nginx-static без host-портов, Node из version.env, createRoot, бренд через env; SSR `server/**` изолирован от bundle/typecheck/образа — rollup external, prod-stage копирует только `dist/`). 5 MED/LOW — остаточная грязь чужого домена.
- **security (opus, security-reviewer) PASS:** блокеров/секретов нет (`secrets_found:false`, ротация не нужна). httpOnly-cookie pass-through, security-заголовки наследуются, нет XSS/path-traversal. MED: open-redirect defense-in-depth на sign-in (`?redirect=`).
- **applied (polish, не блокировало merge, но закрыто до ship):** export `isSafeRedirect` + валидация `?redirect=` в sign-in (A01 hardening); нейтрализованы чужие prefetch-реэкспорты → один `fetchPlaceholder`; удалён весь чужой `tests/visual/**` (mailpit/minio/workspace-инфра реф-проекта) + foreign dashboard-spec; `gen:api`→`http://localhost/api/openapi.json`; `test:visual`→`test:e2e`; tsconfig.node include `tests/e2e`; gitignore+untrack `playwright-report`/`test-results`. Re-run: build/tsc/lint зелёные, vitest 17/17, **smoke e2e 5/5 за nginx** (повторно после polish).
- **Технический долг (→ C2/task-014):** мёртвый SSR-слой `frontend/server/**` + fastify-deps + `dev`/`start` SSR-скрипты (не в bundle/образе, но dead code) — удалить целиком в C2; `shared/lib/error-codes.ts` содержит чужие PostBolt-коды (baseline, вне диффа) — выровнять под реальные коды TrendPulse backend; `manualChunks` для 729kB-бандла.
