---
id: TASK-063
title: Admin-экран бизнес-метрик — /admin/metrics поверх GET /ops/business-metrics
status: review             # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [frontend, admin, analytics, ops, spa]
---

# TASK-063 — Admin-экран бизнес-метрик (money dashboard UI)

> SPA-витрина для готового backend'а TASK-051: superuser-only страница `/admin/metrics`
> с карточками MRR / подписки по планам / средний чек, воронкой активации за 30 дней
> и retention (repeat_payment_rate). Обычный юзер видит 404, сервер в любом случае
> отвечает 403.

## Context

Backend полностью готов (TASK-051): `GET /api/v1/ops/business-metrics` —
`backend/src/api/routes/ops_business.py:96-135`, гейт `Depends(current_superuser)`
(`ops_business.py:102`, fastapi-users `is_superuser`, ADR-003): 401 без сессии,
403 не-superuser'у. Схема ответа `BusinessMetricsResponse` (`ops_business.py:68-88`):
`mrr: Decimal`, `active_subscriptions_by_plan: dict[str,int]`,
`avg_check_30d: Decimal`, `funnel_last_30d: FunnelSummary` (daily-строки
`FunnelDayRow` `ops_business.py:43-55`: registrations / packs_attached /
first_alerts_delivered / first_feedback / new_paid / churned / active_paid +
`conversion_free_to_paid`), `repeat_payment_rate: float | null` (null = нет
дозревших юзеров, не 0%).

Эндпоинт **уже в OpenAPI-дампе** (`frontend/src/shared/api/openapi.json:2344`),
тип `BusinessMetricsResponse` **уже сгенерирован** (`frontend/src/shared/api/gen.types.ts:874`)
— регенерация клиента не требуется для самого эндпоинта.

SPA-паттерны (свежие эталоны — features/packs, TASK-038): feature-модуль =
`api.ts` (axios `apiClient`, типы из `gen.types.ts`) + `queries.ts`
(react-query хуки, stable query key) — `frontend/src/features/packs/api.ts`,
`frontend/src/features/packs/queries.ts`. Роуты: `frontend/src/app/router/path.ts`
(объект `paths`) + `frontend/src/app/router/router.ts` (createRoute под
`protectedContentRoute`, `router.ts:68-72`). Текущий юзер:
`useCurrentUser` (`frontend/src/entities/viewer/model.ts`) поверх
`GET /users/me` → `UserMeResponse`.

**Гэп:** `UserMeResponse` (`backend/src/api/auth/me.py:24-32`) отдаёт только
`email/id/is_verified/plan` — **без `is_superuser`** (`gen.types.ts:1259-1271`).
Клиентскому guard'у нечего читать → нужно микрорасширение backend.

## Goal

Superuser открывает `/admin/metrics` и видит актуальные MRR, подписки по планам,
средний чек 30д, воронку активации (дневные ряды + конверсия Free→Paid) и
retention (repeat_payment_rate). Обычный авторизованный юзер на том же URL видит
состояние «Not found» (no existence leak); неавторизованный — редирект на sign-in
(существующий AuthGuard). DoD = AC зелёные + vitest/eslint/tsc + e2e.

## Discussion

- Q: 404 или redirect для не-superuser'а? → A: 404-состояние → Decision: рендерим
  тот же «not found»-паттерн, что `AlertDetailPage` при 404
  (`frontend/src/pages/alerts/detail.tsx:84-97`) — не раскрываем существование
  admin-маршрута (паттерн backend'а: foreign id → 404, ADR-002). Redirect на `/`
  был бы сигналом «страница есть, но не для тебя».
- Q: клиентский guard по `is_superuser` — откуда брать флаг? → A: расширить
  `UserMeResponse` → Decision: добавить `is_superuser: bool` в
  `backend/src/api/auth/me.py` (поле уже есть на модели `User` — fastapi-users)
  + `make gen-openapi gen-types`. Это НЕ секрет и НЕ замена серверного гейта:
  настоящая защита — `current_superuser` на роуте (403). Клиентский флаг — только UX.
- Q: рисовать графики (chart-библиотека)? → A: нет → Decision: воронка = простая
  таблица/список дневных рядов + summary-числа. Аудитория экрана — один owner;
  новая зависимость (recharts и т.п.) — неоправданный вес бандла. График — отдельной
  задачей, если заболит.
- Q: прятать ли роут из бандла обычного юзера (code-splitting)? → A: не требуется →
  Decision: роут регистрируется статически как остальные (`router.ts` не использует
  lazy-роуты нигде); сам компонент не содержит секретов — все данные приходят
  только с сервера после 200. Инвариант «защита на сервере» покрывает риск.
- Q: deps 051 — backend смержен? → A: да, код TASK-051 в main (волна E,
  PR #52-63), `ops_business.py` и дамп OpenAPI на baseline `c390c4c` уже содержат
  эндпоинт. Блокеров нет.

## Scope

> Чисто frontend + 1 поле в `UserMeResponse` (backend, 3 строки + regen).

- **Touch ONLY:**
  - `backend/src/api/auth/me.py` — поле `is_superuser: bool` в `UserMeResponse`
    (`me.py:24`) + проброс в конструкторе ответа (`me.py:44`).
  - `frontend/src/shared/api/openapi.json` + `frontend/src/shared/api/gen.types.ts`
    — регенерация (`make gen-openapi gen-types`; CI держит drift-check,
    `Makefile:242`).
  - `frontend/src/app/router/path.ts` — `admin: { metrics: '/admin/metrics' }`.
  - `frontend/src/app/router/router.ts` — `adminMetricsRoute` под
    `protectedContentRoute` (по образцу `accountSettingsRoute`, `router.ts:84-88`)
    + в `routeTree`.
  - `frontend/src/features/admin-metrics/` (новый, по образцу `features/packs/`):
    `api.ts` (`getBusinessMetrics()` → `apiClient.get('/ops/business-metrics')`,
    тип `components['schemas']['BusinessMetricsResponse']`), `queries.ts`
    (`useBusinessMetrics`, query key `['admin','business-metrics']`,
    `retry: false` — 403 терминален), `index.ts`.
  - `frontend/src/pages/admin/` (новый): `metrics.tsx` (страница: guard по
    `useCurrentUser().is_superuser` → not-found-состояние; карточки MRR /
    active-by-plan / avg check; таблица воронки + conversion; retention c
    обработкой `null` → «no matured users yet»), `index.ts`.
  - `frontend/src/pages/index.ts` — реэкспорт `AdminMetricsPage`.
  - `frontend/tests/unit/admin/admin-metrics.spec.ts(x)` — новый.
  - `frontend/tests/e2e/admin-metrics.spec.ts` — новый.
- **Do NOT touch:** `backend/src/api/routes/ops_business.py` и `analytics/*`
  (контракт готов, TASK-051); `current_superuser`-backend
  (`api/auth/backend.py`); `AuthGuard` (`app/router/auth-guard.tsx`) — admin-гейт
  живёт в странице, не в общем guard'е; SSR-prefetch (`server/ssr/*`) — admin-страница
  рендерится client-side как остальные protected-страницы; навигация/меню — ссылку
  в общий header НЕ добавляем (страница по прямому URL, обычным юзерам её не видно).
- **Blast radius:** `UserMeResponse` — additive-поле (потребители `useCurrentUser`:
  guards, settings — не ломаются; `extra="forbid"` относится к входу, не к ответу);
  регенерация `gen.types.ts` затрагивает общий файл (additive); новый роут в
  `routeTree` — изолированный лист. Backend-роут не меняется вовсе.

## Acceptance Criteria

- [ ] **AC1 — superuser видит метрики.** Given юзер с `is_superuser=true` и активной
  сессией When открывает `/admin/metrics` Then рендерятся карточки MRR,
  подписки по планам, avg check 30d, таблица воронки за 30 дней с
  `conversion_free_to_paid` и retention; значения соответствуют ответу API.
- [ ] **AC2 — обычный юзер получает 404-состояние.** Given авторизованный юзер с
  `is_superuser=false` When открывает `/admin/metrics` Then видит «Page not found»
  (без упоминания admin/прав), And сетевой запрос к
  `/api/v1/ops/business-metrics` либо не уходит (клиентский guard), либо получает
  403 и UI всё равно показывает not-found (не «ошибка доступа»).
- [ ] **AC3 — неавторизованный → sign-in.** Given нет сессии When открывает
  `/admin/metrics` Then существующий AuthGuard редиректит на
  `/auth/sign-in?redirect=/admin/metrics`.
- [ ] **AC4 — пустые/null-данные.** Given `repeat_payment_rate=null` и пустой
  `funnel_last_30d.daily` When страница рендерится Then retention показывает
  «no data yet» (не 0%), воронка — empty-state, краш отсутствует.
- [ ] **AC5 — G2.** `make ci` зелёный (включая openapi-drift-check), vitest unit
  + e2e зелёные; ручная проверка на стеке: superuser-логин → страница с живыми
  числами.

## Plan

1. `backend/src/api/auth/me.py` — RED: backend-unit на наличие `is_superuser` в
   `/users/me` → добавить поле в `UserMeResponse` + проброс → GREEN.
2. `make gen-openapi gen-types` — обновить дамп и `gen.types.ts`, закоммитить
   (иначе CI drift-check красный). `BusinessMetricsResponse` уже в типах —
   проверить, что diff затронул только `UserMeResponse`.
3. `frontend/src/features/admin-metrics/api.ts` + `queries.ts` — клиент и хук по
   образцу `features/packs` (типы ТОЛЬКО из `gen.types.ts`, C1-инвариант).
4. `frontend/src/pages/admin/metrics.tsx` — страница: superuser-guard →
   not-found-ветка (копия паттерна `pages/alerts/detail.tsx:84-97`), loading/error
   состояния, карточки + таблица воронки (Tailwind, без новых зависимостей).
5. `path.ts` + `router.ts` + `pages/index.ts` — регистрация роута.
6. Тесты: unit (рендер карточек по мок-данным; null-retention; not-found для
   обычного юзера) + e2e (обычный юзер → not found; прямой 403 от API).
7. Verify (G2): `make ci`, прогон vitest/eslint/tsc, e2e, ручной заход superuser'ом.

## Invariants

- **Серверный гейт — единственная настоящая защита**: `current_superuser` на
  роуте (`ops_business.py:102`) остаётся нетронутым; клиентский `is_superuser` —
  только UX-оптимизация. Никаких данных метрик в бандле/SSR-стейте нет — всё
  приходит после 200 от API.
- Ответ — только агрегаты (инвариант TASK-051, `extra="forbid"`): UI не ждёт и не
  рендерит per-user поля.
- Типы фронта — ТОЛЬКО из `gen.types.ts` (C1, TASK-019); ручных дублей схемы нет.
- `repeat_payment_rate=null` ≠ 0% — UI обязан различать «нет данных» и «0».
- Существующие потребители `useCurrentUser` не меняют поведения (additive-поле).

## Edge cases

- 403 от API при гонке (флаг в кэше устарел: superuser снят) → not-found-состояние,
  не «retry»-спиннер (`retry: false` в хуке).
- `mrr`/`avg_check_30d` приходят строками (Decimal сериализуется в JSON как
  string в FastAPI) → парс через `Number(...)` с фиксированным форматированием
  `$X.XX`; NaN → «—».
- `active_subscriptions_by_plan` — пустой dict (нет подписок) → карточка «0 active».
- Дни без строки в `daily` (gap в business_metrics_daily) → таблица рендерит
  только присутствующие ряды, без интерполяции.
- Mobile: карточки в одну колонку (`grid-cols-1 md:grid-cols-3`), таблица воронки
  со скроллом по X (`overflow-x-auto`).
- `/admin/metrics` с trailing-slash или `/admin` без листа → notFoundComponent
  rootRoute (`router.ts:35-38`) — уже работает.

## Test plan

- unit (vitest, `frontend/tests/unit/admin/`): рендер метрик по мок-`BusinessMetricsResponse`
  (MRR/avg check formatting, by-plan карточка); `repeat_payment_rate: null` →
  «no data»; не-superuser → not-found-разметка; пустой `daily` → empty-state.
- backend unit: `/users/me` содержит `is_superuser` (true/false), дополнение к
  существующим me-тестам.
- e2e (Playwright, паттерн `frontend/tests/e2e/alerts.spec.ts` —
  `registerAndLogin` + `seedWatchlist`): обычный юзер → `/admin/metrics` → «Page
  not found»; прямой `page.request.get('/api/v1/ops/business-metrics')` → 403.
  Superuser-сценарий — best-effort: если в e2e-окружении нет superuser-сидинга,
  фиксируем как ручную проверку G2 (psql `UPDATE users SET is_superuser`).
- security: клиентский guard не считается защитой — отдельного security-этапа не
  требуется, серверный гейт не трогаем (подтвердить на review).

## Checkpoints

current_step: 7
baseline_commit: "c390c4c"
branch: "task/063-admin-money-dashboard-ui"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (if touches auth/input/secrets/OAuth)
- [x] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11: SPA-витрина к money-dashboard TASK-051; backend-контракт
заморожен, фронт — новый изолированный feature-модуль + 1 additive-поле в
`/users/me`. Без chart-библиотек, без ссылки в общей навигации.)

(executed 2026-06-11, Fable-pipeline:
- do (TDD): RED backend — `test_users_me.py` упал на отсутствии `is_superuser`
  (одноразовый pgvector:pg16 на :15436) → GREEN после 3-строчного additive-поля
  в `me.py`; `make gen-openapi gen-types` — diff типов затронул ТОЛЬКО
  `UserMeResponse` (+2 строки). RED frontend — 17 unit-ассертов на несуществующий
  модуль → GREEN: `features/admin-metrics/{api,queries,lib,index}.ts` +
  `pages/admin/metrics.tsx` + роут.
- Решение: вместо копии not-found-разметки страница рендерит САМ `NotFoundPage`
  (`pages/error/not-found.tsx`) — байт-в-байт идентичный реальному 404, нулевой
  existence leak. Pure-хелперы вынесены в `lib.ts` (vitest env=node, без
  @testing-library — конвенция проекта).
- verify (G2): backend ruff/mypy ✓, unit 629 ✓, `test_users_me` 3/3 ✓ на live pg;
  frontend eslint/tsc ✓, vitest 255 (24 файла) ✓; regen идемпотентна. Runtime:
  uvicorn на :8073 + curl — unauth 401, regular `is_superuser:false`+403,
  superuser `is_superuser:true`+200 с агрегатами (`mrr:"0"` строкой,
  `repeat_payment_rate:null` — оба edge-кейса покрыты UI-хелперами).
  Известный флак: полный `pytest` (unit+integration в одном процессе) локально
  даёт 19 падений в analytics/embed_cache/log_hygiene/signal_latency — ИДЕНТИЧНО
  на чистом baseline 77d3427 (проверено stash-прогоном), в изоляции (`--lf`)
  19/19 зелёные; к диффу отношения не имеет, в CI проходит.
- review/security: блокирующих находок нет; серверный гейт `current_superuser`
  не тронут, клиентский флаг — UX-only (подтверждено e2e-ассертом прямого 403).
- e2e superuser happy-path не автоматизирован (нет superuser-сидинга в e2e-среде)
  → ручная G2-проверка owner'ом на стенде, как и было зафиксировано в Test plan.)
