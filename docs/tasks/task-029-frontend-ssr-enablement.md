---
id: TASK-029
title: Frontend SSR enablement — TanStack-гидрация (откат статик-решения C1) + cookie-auth SSR-прокси + manualChunks
status: planned             # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-029-frontend-ssr-enablement"
tags: [epic-d, frontend, ssr, perf]
---

# TASK-029 — Frontend SSR enablement (Epic D)

> **Включить реальный SSR** (откат статик-решения C1/[task-013](./task-013-frontend-foundation.md)) на паттерне гидрации TanStack Router. `src/app/root.tsx` возвращается на `hydrateRoot` + дегидратированное состояние (`window.$_TSR`), серверный рендер идёт через `frontend/server/ssr/render.tsx`. Чинится SSR-прокси под **cookie-auth** ([C1-verify finding](./task-013-frontend-foundation.md)): `server/client.ts`/`server.factory.ts` форвардят исходный `Cookie`-заголовок к backend (НЕ `Authorization: Bearer`), `server/plugins/refresh.plugin.ts` удаляется (cookie-auth без refresh-эндпоинта). Env `API_URL`/`COOKIE_SECRET` для SSR-сервера прокидываются в `development/compose/frontend.yml` + provisioning (на их отсутствии C1 ронялся). prod-Dockerfile запускает node-SSR-сервер за edge-nginx (`/`→frontend SSR). SSR-prefetch с cookie-forward отдаёт реальные данные guarded-страниц (current_user/watchlists). `vite.config.ts` получает `manualChunks` (react/tanstack/ui split — убрать 729kB-warning). DoD — Acceptance Criteria ниже.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md)) — зрелый FSD React+Vite+TS SPA в `apps/trendPulse/frontend/`. SSR-слой реф-проекта уже на месте: `frontend/server/main.ts` (entry, `tsx server/main.ts` = `dev`/`start`), `server/server.factory.ts` (Fastify-фабрика), `server/ssr/render.tsx` (серверный рендер), `server/ssr/prefetch/` (route-map + fetchers + runner), `server/plugins/{auth,refresh}.plugin.ts`, `server/config.ts` (Zod: `API_URL` url, `COOKIE_SECRET` min(16)), `server/client.ts`.

**История (почему SSR выключен):** [TASK-013 (C1)](./task-013-frontend-foundation.md) при verify-G2 уронился на SSR-слое — он был от другого продукта (Bearer-auth, `refresh.plugin.ts`→`/auth/token/refresh`, env `API_URL`/`COOKIE_SECRET` Zod-required → ZodError/crashloop), несовместимом с TrendPulse cookie-auth. **Решение C1 (упрощение):** статик-путь — `src/app/root.tsx` переведён `hydrateRoot+RouterClient` → `createRoot+RouterProvider`; prod = `nginx:alpine` + Vite `dist/` (`development/compose/frontend.yml` — pure static, без `API_URL`/`COOKIE_SECRET`); `vite.config.ts` помечает `server/**` как rollup/ssr external (не в бандле). SSR-слой остался как **мёртвый код** — C1-review явно зафиксировал долг: «удалить целиком в C2 ИЛИ включить». Epic D выбирает **включить** (SSR нужен для SEO/TTFB лендинг-флоу и быстрых guarded-страниц).

`server/client.ts` сейчас (C1-baseline) тащит `Authorization: Bearer <access_token>` из cookie `access_token` — это контракт реф-проекта (passport-jwt). TrendPulse backend — fastapi-users **httpOnly cookie** (`fastapiusersauth`), Bearer не использует; нет `/auth/token/refresh`. nginx (`development/provisioning/nginx/nginx.conf`) уже описывает `/`→`frontend_spa` как «SSR server» в комментариях, но `frontend` upstream сейчас = static nginx :80.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — `make` единая точка входа; версии из `development/version.env`; секреты только из env; no magic literals.

## Goal

После задачи: страница рендерится **server-side** (view-source содержит реальный контент, не пустой `<div id="root">`); клиент гидрирует без ошибок mismatch (дегидратированное состояние через `window.$_TSR`); cookie-auth работает сквозь SSR — серверный prefetch `current_user`/watchlists форвардит исходный `Cookie` к backend и встраивает данные в HTML; неавторизованный SSR-запрос на guarded-страницу → `401`-prefetch → redirect на `/login`; `manualChunks` разбил бандл (нет 729kB chunk-warning); prod-стек = node-SSR-сервер `frontend` за edge-nginx (`/`→SSR); e2e за nginx проверяет SSR-HTML и гидрацию. Security: cookie-forward (не Bearer), `COOKIE_SECRET`/`API_URL` из env, ноль токенов в JS-бандле. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Решения по C1-истории + ADR-002/network-design; обратимы. -->
- Q: SSR или оставить статику? → A: **включить SSR** (Epic D goal) → Decision: откатываем C1-упрощение; `root.tsx` `createRoot`→`hydrateRoot`, prod-`frontend` = node-SSR за nginx. Мотив: SEO/TTFB + быстрые guarded-страницы; SSR-слой уже написан (адаптировать, не катать с нуля — паттерн C1 «adopt proven structure»).
- Q: Транспорт auth в SSR-прокси (C1-finding)? → A: cookie-forward → Decision: `server/client.ts` форвардит **исходный `Cookie`-заголовок** запроса к backend (httpOnly `fastapiusersauth`), НЕ лифтит `access_token`→`Authorization: Bearer` (реф-логика, у TrendPulse нет Bearer). `withCredentials` нерелевантен в Node — явный `headers.Cookie`.
- Q: refresh.plugin? → A: удалить → Decision: TrendPulse cookie-auth не имеет `/auth/token/refresh`; `refresh.plugin.ts` дёргает несуществующий эндпоинт → удалить файл + снять регистрацию в `server.factory.ts`; axios-interceptor реф-проекта на `POST /__auth/refresh` тоже убрать (если остался).
- Q: env для SSR-сервера (C1 ронялся)? → A: `API_URL`/`COOKIE_SECRET` из env → Decision: `development/compose/frontend.yml` передаёт `API_URL=http://api:8000` (internal) + `COOKIE_SECRET` (из secret/env, не хардкод); `server/config.ts` Zod остаётся источником валидации (fail-fast на старте).
- Q: prod-топология frontend? → A: node-SSR за edge → Decision: prod-Dockerfile запускает `node server/main.ts` (через build) на :4000 на `internal`; edge-nginx `/`→`http://frontend:4000`. nginx комментарий уже это предполагает — выровнять upstream-порт.
- Q: 729kB-бандл? → A: `manualChunks` → Decision: `vite.config.ts build.rollupOptions.output.manualChunks` — vendor-split (`react`/`react-dom`, `@tanstack/*`, ui-deps) → убрать chunk-size-warning; SSR external-конфиг `server/**` сохраняется только если бандл всё ещё его исключает (теперь SSR-сервер использует исходники — пересмотреть external).

## Scope
> Затрагивает **`frontend/` (SSR-слой + root.tsx + vite.config)** + `development/compose/frontend.yml` + `development/provisioning/nginx/nginx.conf` (upstream-порт SSR) + `development/env/*` (API_URL/COOKIE_SECRET для frontend). Backend НЕ трогаем (SSR только потребляет существующие cookie-auth-роуты).

- **Touch ONLY (создать/изменить):**
  - `frontend/src/app/root.tsx` — `createRoot+RouterProvider` → `hydrateRoot` + TanStack дегидрация (`window.$_TSR`); снять dev-only `__DEV_STORES__`-хак, если мешает гидрации (или оставить за `import.meta.env.DEV`).
  - `frontend/server/client.ts` — **переписать**: форвард исходного `Cookie`-заголовка (НЕ Bearer); убрать `accessToken`/`Authorization`-лифтинг; `validateStatus`/`AbortSignal` сохранить; 401 → drop-hydration сигнал (но по cookie, не по токену).
  - `frontend/server/server.factory.ts` — снять регистрацию `refresh.plugin`; убедиться, что `auth.plugin` совместим с cookie-forward (или упростить); прокинуть исходный `Cookie` в per-request клиент.
  - `frontend/server/plugins/refresh.plugin.ts` — **удалить** (cookie-auth без refresh).
  - `frontend/server/ssr/render.tsx`, `server/ssr/ssr.factory.ts`, `server/ssr/html.ts` — выровнять под `hydrateRoot`-контракт (дегидратированное состояние в HTML, `window.$_TSR`).
  - `frontend/server/ssr/prefetch/{route-map.ts,fetchers.ts,run.ts}` — реальные fetchers для guarded-страниц (`current_user` через `GET /users/me`, watchlists через `GET /watchlists`) с cookie-forward; 401 → drop hydration → клиентский guard редиректит `/login`.
  - `frontend/server/config.ts` — подтвердить Zod (`API_URL`/`COOKIE_SECRET`); fail-fast на старте сохранить.
  - `frontend/Dockerfile` — prod-stage: запуск **node-SSR-сервера** (build server+client, `node`/`tsx` entry на :4000), НЕ `nginx:alpine`-static; пересмотреть rollup/ssr external (`server/**` теперь исполняется).
  - `frontend/vite.config.ts` — `build.rollupOptions.output.manualChunks` (vendor-split); пересмотр `build.rollupOptions.external`/`ssr.external` для `server/**` (SSR-сервер использует исходники).
  - `development/compose/frontend.yml` — SSR-сервис: `API_URL=http://api:8000`, `COOKIE_SECRET` (env/secret), порт :4000 на `internal` (без host-портов); healthcheck на SSR-эндпоинт; обновить header-комментарий (был «pure static»).
  - `development/provisioning/nginx/nginx.conf` — `upstream frontend_spa` → `server frontend:4000` (SSR-порт вместо :80); комментарий уже говорит «SSR server».
  - `development/env/deploy.env` (или соответствующий) — `API_URL` (non-secret internal), `COOKIE_SECRET` — через secret-механику (не plaintext в repo).
  - `frontend/tests/e2e/ssr.spec.ts` — **новый** e2e: view-source содержит SSR-контент; гидрация без console-error; cookie-auth current_user на сервере; 401→`/login`.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `backend/**` (SSR только потребляет cookie-auth-роуты), `landing/**`, `docs/**` (кроме `tasks-index.md` на ship). Не вводить Bearer/localStorage-токены. Не реализовывать refresh-эндпоинт.
- **Blast radius:** меняет render-режим всего фронта (static→SSR), prod-топологию `frontend` (nginx-static→node-SSR за edge), upstream-порт в edge-nginx, env-контракт сервиса (`API_URL`/`COOKIE_SECRET`). `manualChunks` меняет раскладку бандла (asset-имена). Риск гидрационных mismatch на всех страницах. Откат C1 — обратим (вернуть static при провале).

## Acceptance Criteria
- [ ] **AC1 — server-side render (failing-test anchor).** Given `make up` (стек за nginx), When `curl`/Playwright берёт view-source корня и guarded-страницы, Then HTML содержит **реальный контент** (бренд, разметка страницы), а не пустой `<div id="root"></div>`. e2e пишется ПЕРВЫМ (RED — пока static `createRoot`).
- [ ] **AC2 — гидрация без ошибок.** Given SSR-HTML, When клиент гидрирует (`hydrateRoot`), Then дегидратированное состояние присутствует (`window.$_TSR`), консоль без hydration-mismatch/фатальных ошибок, интерактив работает.
- [ ] **AC3 — cookie-auth сквозь SSR.** Given залогиненный пользователь (httpOnly `fastapiusersauth`), When SSR рендерит guarded-страницу, Then серверный prefetch форвардит **исходный `Cookie`** к backend (`GET /users/me`/`GET /watchlists`), данные встроены в SSR-HTML; **нет** `Authorization: Bearer`.
- [ ] **AC4 — 401 SSR → redirect `/login`.** Given пользователь без cookie, When SSR-prefetch guarded-страницы → `401`, Then hydration дропается и клиентский guard редиректит на `/login`; raw-401 не показывается.
- [ ] **AC5 — refresh.plugin удалён, нет Bearer.** Given `frontend/server/**`, When инспекция, Then `refresh.plugin.ts` отсутствует и не зарегистрирован; нигде нет `Authorization: Bearer`/лифтинга `access_token`; нет вызова `/__auth/refresh`/`/auth/token/refresh`.
- [ ] **AC6 — manualChunks разбил бандл.** Given `make build`, When сборка, Then `output.manualChunks` даёт vendor-split (react/tanstack/ui), нет 729kB-warning (chunk-size в пределах лимита); typecheck/build зелёные.
- [ ] **AC7 — prod-топология SSR за edge + поведенческая (G2) через nginx.** Given `make build && make up`, When стек поднят, Then `frontend` = node-SSR на `internal` :4000 без host-портов, edge-nginx `/`→`frontend:4000`; `API_URL`/`COOKIE_SECRET` из env (контейнер не падает); Playwright `ssr.spec.ts` против реального стека за nginx наблюдает AC1–AC4; артефакты on-failure сохранены.

## Plan
0. Executor фиксирует `baseline_commit` от текущего HEAD; ветка `gsd/phase-029-frontend-ssr-enablement`.
1. **RED:** `frontend/tests/e2e/ssr.spec.ts` — view-source содержит SSR-контент + `window.$_TSR` + cookie-auth current_user + 401→`/login`. Запустить — падает (static `createRoot`, пустой root). AC1-якорь.
2. SSR-прокси под cookie-auth: переписать `server/client.ts` (cookie-forward, без Bearer); снять `refresh.plugin` (удалить файл + регистрацию в `server.factory.ts`); выровнять `auth.plugin`/per-request клиент на `Cookie`-форвард.
3. `server/ssr/prefetch/{route-map,fetchers,run}` — реальные fetchers guarded-страниц (current_user/watchlists) с cookie-forward; 401 → drop hydration.
4. `src/app/root.tsx` `createRoot+RouterProvider` → `hydrateRoot` + дегидрация (`window.$_TSR`); `render.tsx`/`html.ts`/`ssr.factory.ts` под hydrate-контракт.
5. `vite.config.ts` — `manualChunks` vendor-split; пересмотр rollup/ssr `external` для `server/**` (теперь исполняется SSR-сервером).
6. prod-`Dockerfile` — node-SSR entry (:4000), build server+client; `development/compose/frontend.yml` — `API_URL`/`COOKIE_SECRET` + порт :4000 + SSR-healthcheck; `nginx.conf` upstream `frontend:4000`; env-файлы.
7. **GREEN:** `make build && make up`; Playwright `ssr.spec.ts` зелёный через nginx (AC1–AC4, AC7); build/tsc/lint зелёные, нет chunk-warning (AC5–AC6).
8. **5.5 security**: cookie-forward (не Bearer), `COOKIE_SECRET` из env, нет токенов в JS-бандле.
9. Обновить `tasks-index.md` на ship.

## Invariants
- **Cookie-auth сквозной** — SSR форвардит исходный httpOnly `Cookie` к backend; никаких Bearer/`access_token`-лифтингов/localStorage-токенов (контракт [task-003](./task-003-auth.md)/C1).
- **Никаких секретов в JS-бандле** — `COOKIE_SECRET` живёт только на сервере (env); клиентский бандл несёт лишь non-secret `VITE_*` (CONVENTIONS).
- **Fail-fast env** — `server/config.ts` Zod валидирует `API_URL`/`COOKIE_SECRET` на старте; отсутствие → краш на старте, не в рантайме (это и ронял C1 — теперь env поставлен).
- **Гидрация = серверный HTML** — дегидратированное состояние в `window.$_TSR` совпадает с серверным рендером; никаких mismatch (одинаковые данные prefetch на сервере и в клиентской гидрации).
- **`frontend` только за edge** — node-SSR на `internal`, без host-портов; наружу — только nginx ([network-design](../architecture/network-design.md)).
- **`make` — единая точка входа** — версии (Node) из `development/version.env`, без `latest`.
- **SSR-слой адаптируется, не переписывается** — переиспользуем `server/**` реф-проекта (Fastify/render/prefetch), правим только auth-транспорт + env + entry.

## Edge cases
- Hydration mismatch (серверный HTML ≠ клиентский первый рендер) → React-варнинг/перерисовка; prefetch-данные должны быть идентичны на сервере и в клиентской гидрации; AC2 это ловит.
- `Cookie`-заголовок не форвардится (потерян в Fastify per-request) → server-prefetch 401 на залогиненном → пустая hydration; AC3 ловит.
- `COOKIE_SECRET`/`API_URL` отсутствуют в env → Zod краш на старте (как в C1) → контейнер не встаёт; AC7 проверяет наличие env.
- nginx `frontend_spa` всё ещё указывает на :80 (static-порт) → 502 на SSR :4000; обновить upstream-порт.
- `manualChunks` сломал порядок загрузки/circular vendor → рантайм-ошибка; проверить, что split не разрывает react-singleton.
- `dev`-хак `__DEV_STORES__` в `root.tsx` ломает гидрацию (мутирует window до hydrate) → за `import.meta.env.DEV` и не влияет на prod-SSR.
- Остаточный axios-interceptor реф-проекта на `/__auth/refresh` → циклы/404 после удаления плагина; вычистить.
- `server/**` помечен external в бандле, но теперь исполняется SSR-сервером → пересмотреть, иначе server-код не соберётся в образ.

## Test plan
- **e2e (Playwright):** `tests/e2e/ssr.spec.ts` — AC1 (view-source = SSR-контент, RED-якорь), AC2 (`window.$_TSR` + нет hydration-error), AC3 (cookie-auth current_user на сервере), AC4 (401→`/login`). Артефакты on-failure: trace/screenshot/video.
- **build/typecheck:** `make build` + `tsc` — AC5 (нет Bearer/refresh.plugin), AC6 (manualChunks, нет chunk-warning, билд зелёный).
- **runtime/behavioral (G2):** `make up` → Playwright против реального стека за nginx — AC7; ручная проверка топологии (`frontend` node-SSR :4000 на `internal`, без host-портов, edge `/`→:4000, env `API_URL`/`COOKIE_SECRET` присутствуют).
- **security (5.5):** grep бандла на `Bearer`/токены/`COOKIE_SECRET`; cookie-forward (не Bearer) в server-prefetch; нет секретов в JS/логах.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-029-frontend-ssr-enablement"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через nginx/стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по эталону [task-013](./task-013-frontend-foundation.md)/[task-017](./task-017-billing-account-ui.md) и реальному коду: включаем SSR откатом C1-статик-решения. Ключевые факты из baseline: `src/app/root.tsx` сейчас `createRoot+RouterProvider` (C1 перевёл с `hydrateRoot`); `server/client.ts` лифтит `access_token`→`Authorization: Bearer` (реф-логика, несовместима с TrendPulse cookie-auth — это и есть C1-finding); `server/config.ts` Zod-required `API_URL`/`COOKIE_SECRET`; `development/compose/frontend.yml` = pure-static nginx:80 без этих env; `nginx.conf` `upstream frontend_spa` = `frontend:80` но комментарий уже говорит «SSR server»; `vite.config.ts` без `manualChunks`, помечает `server/**` external; `refresh.plugin.ts` дёргает несуществующий `/auth/token/refresh`. Backend cookie-auth неизменен — SSR только потребляет `GET /users/me`/`GET /watchlists` с cookie-forward. deps: 013 (frontend foundation), 014 (guard/current_user). locate+plan выполнены этим планированием — executor стартует с шага «3 do». Откат обратим: при провале гидрации/верификации — вернуть static-путь C1.)
