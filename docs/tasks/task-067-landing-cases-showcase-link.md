---
id: TASK-067
title: Landing proof-of-speed — живые кейсы из GET /cases, ссылка на showcase-канал, фикс robots.txt
status: review              # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: "task/067-landing-cases-showcase-link"
tags: [landing, ssr, showcase, proof-of-speed, seo]
---

# TASK-067 — Proof of Speed на лендинге: живые кейсы + showcase-канал + robots-фикс

> Лендинг продаёт скорость, но не ПОКАЗЫВАЕТ её. Backend-сырьё готово (TASK-045:
> публичный `GET /api/v1/cases`) — выводим живые кейсы «обнаружено в 14:02 →
> мейнстрим в 14:45» секцией на home, даём ссылку на showcase TG-канал
> (footer + hero) и чиним дрейф `robots.txt` (ai-port.me → foresignal.biz).

## Context

Backend полностью готов: публичный эндпоинт без auth `GET /api/v1/cases`
(`backend/src/api/main.py:351`, роутер `backend/src/api/cases/router.py:31`) возвращает
`CasesResponse{items: CaseItem[]}` (`backend/src/api/cases/schemas.py:14-49`) с полями
`title` (sanitized), `viral_score`, `first_seen` (момент обнаружения), `mainstream_at`
(операторская отметка «стало вирусным», всегда NOT NULL в ответе), `lead_time_seconds`,
`channels_count`. Сортировка по lead-time DESC, cap = `settings.cases_top_n_max`
(`backend/src/config.py:499`, default 20). `channels_count` пока MVP=1
(`backend/src/showcase/cases.py:43`).

Лендинг — React+Vite, SSR через собственный Fastify-сервер (`landing/server/main.ts`,
`landing/server/ssr/ssr.factory.ts:107` `handleRequest` → `render()` →
`buildHtml` инжектит `window.__INITIAL_STATE__`, `landing/server/ssr/html.ts:10`).
Контент config-driven из `landing/public/config.json` (импорт в
`landing/src/shared/site/constants.ts:1`). **Сейчас лендинг не делает ни одного
запроса к API** (grep fetch/axios по `landing/src` + `landing/server` = 0 совпадений).

Топология (релизный nginx `release/provisioning/nginx/templates/nginx.conf.template`):
apex `${DOMAIN}` → landing SSR (`:93-110`), `app.${DOMAIN}` → SPA + `/api/v1/*`
(`:113+`). Т.е. лендинг (`foresignal.biz`) и API (`app.foresignal.biz`) — разные
origin'ы; **CORSMiddleware в backend отсутствует** (grep по `backend/src` = 0).

Showcase TG-канал ещё не создан — это TASK-070 (owner-шаг); здесь готовим витрину:
новое поле `showcaseTelegramUrl` в config.json, пустое значение = ссылки не рендерятся.

Дрейф доменов: `landing/public/robots.txt:4` указывает
`Sitemap: https://ai-port.me/sitemap.xml` (домен старого шаблона); `sitemap.xml`
проверен — чистый (`foresignal.biz`, генерируется `landing/scripts/generate-sitemap.ts`
из `SITE_ROUTES` + `SITE.siteUrl`).

## Goal

Home-страница показывает секцию «Proof of Speed» с ≥3 живыми кейсами (время
обнаружения → время мейнстрима → lead-time, score) из `GET /api/v1/cases` через
SSR-fetch с кэшем; при <3 кейсах / недоступном API секция молча скрывается и SSR
не деградирует. Ссылка на showcase-канал в footer и hero рендерится только при
непустом `showcaseTelegramUrl`. `robots.txt` указывает на `foresignal.biz`.
`npm run seo:validate` зелёный, landing e2e зелёные. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Как лендинг получает данные — SSR-fetch или client-side fetch? → A: лендинг и API
  на разных поддоменах (`foresignal.biz` vs `app.foresignal.biz`), в backend НЕТ
  CORSMiddleware → client-side fetch потребовал бы правки backend (CORS allowlist) и
  светил бы спайки публичного трафика прямо в API → Decision: **SSR-fetch на
  Fastify-сервере лендинга с in-memory кэшем** (TTL — env, default 300s). Плюсы:
  ноль изменений backend/nginx, кейсы попадают в SSR-HTML (SEO), API получает
  ~1 запрос / TTL вместо запроса на каждого посетителя, graceful fallback тривиален.
  Передача в React: `initialState` (механизм `window.__INITIAL_STATE__` уже есть,
  `landing/server/ssr/html.ts:10`, сейчас всегда `{}`) + React-context в `AppShell`
  для SSR-рендера.
- Q: Откуда сервер лендинга знает URL API? → A: внутри compose-сети у лендинга нет
  гарантированного маршрута до api (api в `internal`-сети, network-design) →
  Decision: env `CASES_API_URL` в zod-схеме `landing/server/config.ts` (по образцу
  `PORT`/`NODE_ENV`), **default `""` = фича выключена, секция скрыта**. В прод-деплое
  owner задаёт `https://app.foresignal.biz/api/v1/cases` (через edge — публичный
  эндпоинт, rate-limit 120/min его легко держит при 1 запросе/TTL). Никаких magic
  literals: TTL и timeout — env/константы (`CASES_CACHE_TTL_SECONDS=300`,
  `CASES_FETCH_TIMEOUT_MS=2000`).
- Q: Что показывать в карточке кейса? → A: схема даёт title/score/first_seen/
  mainstream_at/lead_time_seconds/channels_count → Decision: title + «detected HH:MM →
  mainstream HH:MM» (UTC) + lead-time («43 min ahead») + score. **`channels_count` НЕ
  показываем**: MVP=1 (`backend/src/showcase/cases.py:43`) — «1 channel» ослабляет
  proof, врать нельзя (урок task-018: не публиковать ложные раскрытия).
- Q: Порог fallback? → A: 1-2 кейса выглядят как пустая витрина → Decision: секция
  рендерится только при `items.length >= 3` (named const `MIN_CASES_TO_SHOW = 3`);
  иначе — секции нет в DOM вовсе (не «скелетон», не «coming soon»). Ошибка/таймаут
  fetch = пустой список (лог на сервере, SSR продолжает рендер без секции).
- Q: `showcaseTelegramUrl` — где рендерить? → A: → Decision: footer-блок «Product»
  (`root-layout.tsx:172-179`, рядом с Pricing/FAQ) + hero: третья ссылка-якорь под
  CTA-кнопками («See live detections in Telegram →»). Условный рендер: пустая
  строка/отсутствие поля → ни одного элемента в DOM. Заполняет owner после TASK-070.
- Q: robots.txt — только заменить строку или защититься от повторного дрейфа? → A:
  дрейф уже один раз случился (шаблонный домен пережил ребрендинг) → Decision:
  фикс строки + дешёвая проверка в `scripts/validate-seo.ts`: `robots.txt` должен
  содержать `Sitemap: ${SITE.siteUrl}/sitemap.xml` (siteUrl из config.json) — иначе
  exit 1. ~10 строк, защищает инвариант навсегда.

## Scope
> Только **landing** (src + server + public + tests). Backend, nginx, frontend SPA —
> не трогаем (эндпоинт публичный и готовый).

- **Touch ONLY:**
  - `landing/public/config.json` — новое поле `showcaseTelegramUrl: ""` (+ `_note`
    про TASK-070 по образцу `_signupUrlNote`, `config.json:10`).
  - `landing/server/config.ts` — zod-схема: `CASES_API_URL` (default `""`),
    `CASES_CACHE_TTL_SECONDS` (default 300), `CASES_FETCH_TIMEOUT_MS` (default 2000).
  - `landing/server/cases.ts` — **новый**: типизированный fetch `CasesResponse` +
    in-memory кэш (timestamp + TTL), таймаут через `AbortSignal.timeout`, ошибки →
    лог + `[]` (никогда не бросает в SSR-путь).
  - `landing/server/ssr/ssr.factory.ts` — `handleRequest` (`:128-133`): получить
    кейсы из кэша и передать в `RenderFnInput`.
  - `landing/server/ssr/ssr.types.ts` — расширить `RenderFnInput` полем `cases`.
  - `landing/server/ssr/render.tsx` — пробросить cases в `AppShell`-провайдер и в
    `initialState` (`:86-92`).
  - `landing/src/app/app.tsx` — `AppShell`: context-provider кейсов (SSR) + чтение
    `window.__INITIAL_STATE__` (client hydration).
  - `landing/src/pages/sections/proof-of-speed.tsx` — **новый**: секция (заголовок,
    карточки кейсов, скрытие при <3), стиль карточки — по образцу viral-alert в
    `hero.tsx:42-64`.
  - `landing/src/pages/home.tsx` — вставить `ProofOfSpeedSection` после
    `SocialProofSection` (`home.tsx:14-15`).
  - `landing/src/pages/sections/hero.tsx` — условная ссылка на showcase-канал под
    CTA-блоком (`:25-34`).
  - `landing/src/pages/layouts/root-layout.tsx` — условный пункт «Telegram showcase»
    в footer-списке Product (`:172-179`).
  - `landing/public/robots.txt` — `:4` `ai-port.me` → `foresignal.biz`.
  - `landing/scripts/validate-seo.ts` — проверка Sitemap-строки robots.txt против
    `SITE.siteUrl`.
  - `landing/.env.example` — задокументировать `CASES_API_URL` + TTL/timeout.
  - `landing/tests/e2e/proof-of-speed.spec.ts` — **новый** (см. Test plan).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `backend/**` (эндпоинт готов, CORS не нужен при SSR-fetch),
  `release/provisioning/**` и `development/provisioning/**` (nginx без изменений),
  `frontend/**`, `landing/public/sitemap.xml` (регенерируется build'ом),
  pricing-данные config.json (TASK-049), `_bmad/**`, `.claude/**`.
- **Blast radius:** SSR-путь лендинга (единственный рисковый участок — fetch внутри
  `handleRequest`; изолирован кэшем + таймаутом + catch→`[]`); `RenderFnInput`-контракт
  server↔render (оба конца в этом же diff); config.json-схема (новое опциональное
  поле — потребители читают через `SITE`, отсутствие поля безопасно); публичный API
  не меняется, нагрузка на него ≈ 1 req / TTL.

## Acceptance Criteria

- [ ] **AC1 — секция с кейсами.** Given `CASES_API_URL` задан и API вернул ≥3 кейса
  When открывается `/` Then в SSR-HTML есть секция Proof of Speed: для каждого кейса
  title, «detected HH:MM», «mainstream HH:MM», lead-time, score; `channels_count`
  нигде не выводится.
- [ ] **AC2 — graceful fallback.** Given `CASES_API_URL=""` (или API недоступен/
  таймаут, или вернул <3 кейсов) When открывается `/` Then секции нет в DOM, страница
  рендерится без ошибок, SSR-ответ 200, остальные секции на месте (smoke AC1-AC4
  из `tests/e2e/smoke.spec.ts` не ломаются).
- [ ] **AC3 — кэш.** Given TTL=300s When N посетителей за 5 минут Then к API уходит
  не более 1-2 запросов (unit на кэш-модуль: повторный вызов в пределах TTL не
  делает fetch).
- [ ] **AC4 — showcase-ссылка.** Given `showcaseTelegramUrl: "https://t.me/..."`
  When рендер `/` Then ссылка есть в footer (Product) и в hero, `href` равен значению
  из config; Given `showcaseTelegramUrl: ""` Then ни одного элемента ссылки в DOM.
- [ ] **AC5 — robots/SEO.** `robots.txt` содержит
  `Sitemap: https://foresignal.biz/sitemap.xml`; `npm run seo:validate` зелёный и
  падает (exit 1), если в robots.txt снова появится чужой домен.

## Plan

1. `landing/server/config.ts` + `.env.example` — env-поля (RED: unit на zod-дефолты,
   если тест-каркас сервера есть; иначе типы + ручная проверка).
2. `landing/server/cases.ts` — fetch+кэш+timeout (чистый модуль, unit-testable без
   Fastify); тип `CaseItem` зеркалит `backend/src/api/cases/schemas.py` (поля
   title/viral_score/first_seen/mainstream_at/lead_time_seconds/channels_count).
3. `ssr.types.ts` → `ssr.factory.ts` → `render.tsx` → `app.tsx` — проброс данных
   (context + initialState), упорядочено по зависимости контракта.
4. `proof-of-speed.tsx` + `home.tsx` — секция и её скрытие при <3.
5. `hero.tsx` + `root-layout.tsx` + `config.json` — `showcaseTelegramUrl` с условным
   рендером.
6. `robots.txt` фикс + проверка в `validate-seo.ts`.
7. e2e `proof-of-speed.spec.ts` + прогон существующего `smoke.spec.ts`;
   `npm run lint`, `tsc --noEmit`, `npm run seo:validate`, `npm run build`.

## Invariants

- Лендинг остаётся config-driven: вся вариативность (`showcaseTelegramUrl`) — в
  `public/config.json`; серверная вариативность (URL/TTL/timeout) — env через
  zod-схему `server/config.ts`. Никаких magic literals в коде.
- SSR никогда не падает и не ждёт API дольше `CASES_FETCH_TIMEOUT_MS`: любая ошибка
  fetch = секция скрыта, ответ 200.
- Backend-контракт `GET /api/v1/cases` не меняется; в карточках нет сырого контента
  (schemas.py уже гарантирует sanitized title — лендинг ничего не «дочищает»).
- `npm run seo:validate` зелёный; `sitemap.xml` руками не правится (генерация).

## Edge cases

- API вернул кейсы с одинаковыми title → key карточки = `title + first_seen`
  (уникальный constraint backend `uq_showcase_cases_title_first_seen`).
- `lead_time_seconds` < 60 → форматтер показывает «<1 min» (не «0 min»).
- Кэш истёк, а API упал → отдаём пустой список (секция скрыта), НЕ держим stale
  бесконечно; следующий запрос после TTL попробует снова. (Stale-while-revalidate —
  осознанно НЕ делаем, лишняя сложность для маркетинговой секции.)
- `showcaseTelegramUrl` задан, но не `https://t.me/…` → рендерим как есть (валидация
  формата — ответственность owner'а; config.json — доверенный файл репо).
- Dev-режим без env (`CASES_API_URL` пуст) → лендинг работает как сегодня, ничего
  не фетчится — поведение по умолчанию = текущее.
- Гидрация: client читает `__INITIAL_STATE__` → разметка client === SSR (нет
  hydration mismatch; client сам в API не ходит).

## Test plan

- unit (если в landing появится vitest-каркас — иначе проверка через e2e):
  `server/cases.ts` — кэш в пределах TTL, таймаут → `[]`, невалидный JSON → `[]`.
- e2e (`landing/tests/e2e/proof-of-speed.spec.ts`, playwright по образцу
  `smoke.spec.ts`): (1) без `CASES_API_URL` секция отсутствует, home рендерится;
  (2) с мок-API (playwright route / локальный стаб на `CASES_API_URL`) — секция
  видна, времена/lead-time отображаются; (3) showcase-ссылка: появляется при
  непустом config-поле, отсутствует при пустом (прогон с временным config или
  проверка обоих веток через текущее значение `""` = отсутствие).
- e2e existing: `smoke.spec.ts` AC1-AC4 без регрессий.
- SEO: `npm run seo:validate` (включая новую robots-проверку), `npm run build`
  (включает `sitemap:gen` + `tsc`).
- security: не требуется отдельной стадии — нет user input; единственная поверхность
  (рендер данных API) защищена server-side sanitize (TASK-045) + React-эскейпингом.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 7
baseline_commit: "c390c4c"
branch: "task/067-landing-cases-showcase-link"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — approve, 0 blocking, 4 LOW)
- [x] 5.5 security (n/a — нет user input/auth/secrets; рендер API-данных закрыт backend-sanitize + React-эскейпингом + html.ts `</`-эскейп; подтверждено review)
- [x] 6 ship (confirm plan done → PR(s))
- [x] 7 learnings (auto — docs/learnings.md, запись TASK-067)
debug_runs: []

## Details

(planned 2026-06-11. Зависимости: TASK-045 (done — эндпоинт), TASK-018 (done —
landing base). Owner-хвосты после merge: задать `CASES_API_URL` в прод-env лендинга;
заполнить `showcaseTelegramUrl` после создания канала в TASK-070.)

Исполнение 2026-06-11 (do/verify/review):
- Unit-каркас: vitest в landing нет — взят zero-dep `node:test` через `tsx --test`
  (новый скрипт `npm run test:unit`, package.json — обоснованное отклонение от
  Touch ONLY; 8 unit-тестов на cases-модуль: кэш/TTL/негативное кэширование/
  невалидная схема/non-2xx/non-JSON/abort-signal).
- Декомпозиция сверх Touch ONLY (lint-правило react-refresh/only-export-components
  запрещает не-компонентные экспорты в файлах с компонентами): context+hook в
  `src/shared/cases/cases-context.ts`, тип CaseItem в `src/shared/cases/types.ts`
  (type-only, без runtime-зависимостей — общий для server и src).
- Гидрация: client root.tsx НЕ оборачивает RouterProvider в AppShell → дефолт
  контекста читается из `window.__INITIAL_STATE__` на уровне модуля (inline-скрипт
  state идёт до module-бандла в index.html); client не фетчит → разметка == SSR.
- `channels_count` не рендерится в карточках, но присутствует в `__INITIAL_STATE__`
  JSON (нужен для паритета типов/гидрации; данные и так публичные).
- Кэш: и успех, и ошибка кэшируются на TTL (нет долбёжки API при падении);
  inflight-промис дедуплицирует конкурентные SSR-запросы.
- Review (adversarial, approve): 4 LOW — (1) TTL отсчитывается от завершения fetch
  (осознанно: свежесть данных); (2) `formatLeadTime` без guard на NaN/negative
  (backend-контракт доверенный, lead-time неотрицателен); (3) битая дата → «—» в
  карточке (timestamp'ы доверенные); (4) AC1-ветка e2e скипается без стаба
  (`E2E_CASES_MOCK=1` + сервер с CASES_API_URL-стабом; SSR-fetch нельзя перехватить
  page.route) — AC1 покрыт unit + живой проверкой verify. Фиксы не требуются.
