---
id: TASK-065
title: API-ключи в SPA — раздел в account settings (Trader/Team), выпуск/копия/revoke
status: planned            # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [frontend, api-keys, account, billing, spa]
---

# TASK-065 — Управление API-ключами в SPA (Trader/Team план)

> UI к готовому CRUD'у TASK-028: секция «API keys» в account settings — список
> ключей, выпуск (plaintext показывается РОВНО один раз — modal с copy), revoke
> с confirm. Планы без API-доступа видят upgrade-CTA на Trader.

## Context

Backend готов (TASK-028): `backend/src/api/api_keys/router.py` —
`POST /api/v1/api-keys` (выпуск, `router.py:28-50`; feature-gate
`assert_within_limit(..., Resource.API_ACCESS)` `router.py:40` → 403
`PlanLimitExceeded` для Free/Pro), `GET /api/v1/api-keys` (список, masked,
`router.py:53-60`), `DELETE /api/v1/api-keys/{key_id}` (soft-revoke, 204;
чужой/неизвестный id → 404, `router.py:63-79`). Схемы
(`api_keys/schemas.py`): `ApiKeyCreate` (только `name`, длина по
`_NAME_MIN_LEN/_NAME_MAX_LEN` из `api_keys/constants.py`), `ApiKeyCreated`
(**единственный носитель plaintext `key`** — `schemas.py:29-43`), `ApiKeyRead`
(id/name/prefix/created_at/last_used_at/revoked_at — `schemas.py:46-60`).

Эндпоинты **уже в OpenAPI-дампе** (`frontend/src/shared/api/openapi.json:1515,
1591`), типы `ApiKeyCreated`/`ApiKeyRead` **уже в `gen.types.ts:768,790`** —
регенерация клиента не нужна.

Витрина: `frontend/src/features/account/settings/ui/account-settings-view.tsx` —
секционная страница (Profile → Notification delivery → Help → Danger zone),
`currentPlan` уже доступен (`account-settings-view.tsx:21-22` через
`useCurrentUser`). Plan-гейтинг: `isPlanAtLeast` + `PLAN_TEAM` / `PLAN_DISPLAY_NAME`
(`frontend/src/entities/plan/constants.ts`; display-имя верхнего тарифа —
«Trader», TASK-049). Паттерн feature-модуля — `features/packs/{api,queries}.ts`;
модальный confirm — `ModalDialog` (используется в
`features/account/delete/ui/delete-account-dialog.tsx:58`); CTA на оплату —
роут `paths.billing` (`app/router/path.ts:25`).

## Goal

Юзер на Trader/Team видит в account settings секцию «API keys»: список своих
ключей (prefix, имя, даты, revoked-статус), кнопку «Create key» (имя → modal с
plaintext, copy-to-clipboard, предупреждение «показан один раз»), revoke с
confirm-диалогом. Free/Pro видят секцию с upgrade-CTA («API access is part of
Trader») → `/billing`. DoD = AC + vitest/e2e зелёные.

## Discussion

- Q: секция в settings или отдельная страница? → A: секция → Decision: новая
  `<section>` в `account-settings-view.tsx` между «Notification delivery» и
  «Help & support» — ключей у юзера единицы, отдельный роут не оправдан;
  settings уже секционная (паттерн делает diff минимальным). Отдельная страница
  — only if секция разрастётся (фильтры/usage-статистика — вне scope).
- Q: показывать ли секцию Free/Pro вообще? → A: да, с CTA → Decision: секция
  видна всем с замком и кнопкой «Upgrade to Trader» → `paths.billing` —
  это продажная витрина API-фичи (логика TASK-049: продаём ценность); клиентский
  гейт по `isPlanAtLeast(currentPlan, PLAN_TEAM)` — UX-слой, настоящий гейт на
  сервере (403 на POST).
- Q: как обращаться с plaintext-ключом на клиенте? → A: только в state модалки →
  Decision: `ApiKeyCreated.key` живёт в локальном React-state модального окна до
  его закрытия; НЕ кладём в react-query кэш (инвариант «plaintext один раз»:
  list-кэш содержит только `ApiKeyRead`), не пишем в localStorage/URL/логи.
  Закрыл модал — ключ недоступен навсегда (как в backend).
- Q: revoked-ключи показывать? → A: да → Decision: backend list отдаёт и
  отозванные (`revoked_at != null`) — рендерим их приглушённо с бейджем
  «Revoked» без кнопки revoke; это аудит-след, скрывать = врать о состоянии.
- Q: copy-to-clipboard — библиотека? → A: нет → Decision:
  `navigator.clipboard.writeText` + fallback-сообщение «copy manually» при
  reject (insecure context) — нулевые зависимости.
- Q: deps 028/049 — готовы? → A: да: CRUD в main с TASK-028, тарифная сетка и
  display «Trader» — TASK-049 (done). Блокеров нет.

## Scope

> Чисто frontend: новый feature-модуль + секция в существующей settings-вью.
> Backend и OpenAPI-дамп не трогаем (контракт уже в `gen.types.ts`).

- **Touch ONLY:**
  - `frontend/src/features/api-keys/` (новый, по образцу `features/packs/`):
    - `api.ts` — `listApiKeys()` / `createApiKey(name)` / `revokeApiKey(id)`
      поверх `apiClient` (`shared/api/client.ts`, baseURL `/api/v1`); типы
      `components['schemas']['ApiKeyRead' | 'ApiKeyCreated' | 'ApiKeyCreate']`.
    - `queries.ts` — `API_KEYS_QUERY_KEY = ['api-keys']`, `useApiKeys`,
      `useCreateApiKey` (onSuccess → invalidate list), `useRevokeApiKey`
      (onSuccess → invalidate list).
    - `error-message.ts` — маппинг 403 (`PLAN_LIMIT_EXCEEDED`/envelope TASK-030)
      → «API access is available on the Trader plan», 404 → «Key not found»
      (паттерн `features/packs/error-message.ts`).
    - `ui/api-keys-section.tsx` — секция: список / create-форма (имя) /
      created-modal (plaintext + copy + warning) / revoke-confirm
      (`ModalDialog`); ветка upgrade-CTA для `!isPlanAtLeast(plan, PLAN_TEAM)`.
    - `index.ts`.
  - `frontend/src/features/account/settings/ui/account-settings-view.tsx` —
    вставка `<ApiKeysSection currentPlan={currentPlan} />` после
    delivery-секции (`account-settings-view.tsx:~155`).
  - `frontend/tests/unit/api-keys/api-keys.spec.ts(x)` — новый.
  - `frontend/tests/e2e/billing-account.spec.ts` — сценарий секции (дополнение)
    или новый `api-keys.spec.ts`.
- **Do NOT touch:** `backend/src/api/api_keys/**` (контракт заморожен);
  `openapi.json`/`gen.types.ts` (типы уже есть — если diff их трогает, что-то
  пошло не так); `entities/plan/constants.ts` (значения TASK-049);
  `features/billing/**` (страница оплаты); auth по API-ключу
  (`api/security/**`); `_bmad/**`, `.claude/**`.
- **Blast radius:** одна вставка в `account-settings-view.tsx` (изолированная
  секция — соседние секции не перекомпонуются); новый feature-модуль — листовой;
  сетевые вызовы — только существующие эндпоинты. Регрессия возможна только в
  settings-странице → покрыта существующим e2e `billing-account.spec.ts`.

## Acceptance Criteria

- [ ] **AC1 — список ключей.** Given Trader-юзер с 2 ключами (1 отозван) When
  открывает `/account/settings` Then секция «API keys» показывает оба: prefix,
  имя, created/last used; отозванный — с бейджем «Revoked» и без кнопки revoke.
- [ ] **AC2 — выпуск ключа, секрет один раз.** Given Trader-юзер When создаёт
  ключ с именем Then открывается modal с plaintext и кнопкой Copy, And после
  закрытия модалки plaintext недоступен нигде в UI (в списке — только prefix),
  And список обновился новым ключом.
- [ ] **AC3 — revoke с confirm.** Given активный ключ When юзер жмёт Revoke
  Then появляется confirm-диалог; после подтверждения — DELETE → 204, ключ в
  списке становится «Revoked»; Cancel ничего не меняет.
- [ ] **AC4 — upgrade-CTA.** Given Free- или Pro-юзер When открывает settings
  Then секция показывает замок + «Upgrade to Trader» → переход на `/billing`;
  And прямой POST `/api/v1/api-keys` от такого юзера → 403 (серверный гейт,
  integration-тест существует с TASK-028).
- [ ] **AC5 — пустое состояние и ошибки.** Given Trader без ключей Then
  empty-state «No API keys yet» + Create; Given API вернул 5xx Then секция
  показывает error-сообщение, остальные секции settings живы.
- [ ] **AC6 — G2.** vitest + eslint + tsc + e2e зелёные; ручная проверка на
  стеке: выпуск → copy → curl с ключом (auth TASK-028) → revoke → curl 401.

## Plan

1. RED: unit-тесты feature-модуля (api/queries/error-message — мок apiClient) и
   рендера секции (upgrade-ветка, empty-state, list, modal «one time»).
2. `features/api-keys/api.ts` + `queries.ts` + `error-message.ts` — GREEN
   (минимальный клиентский слой, типы только из `gen.types.ts`).
3. `features/api-keys/ui/api-keys-section.tsx` — секция со state-машиной:
   list → create-form → created-modal; revoke-confirm через `ModalDialog`;
   plan-ветка через `isPlanAtLeast`.
4. `account-settings-view.tsx` — вставить секцию, прокинуть `currentPlan`.
5. e2e: Free-юзер видит CTA (регистрация даёт Free — без сидинга планов);
  Trader-сценарий выпуска/revoke — если в e2e-окружении нет paid-сидинга,
  зафиксировать ручной G2-проверкой (psql `UPDATE users SET plan='team'` +
  Subscription-строка — гочча TASK-049: `effective_plan` требует активную
  Subscription).
6. Verify (G2): vitest/eslint/tsc, e2e, живой цикл ключа на стеке (AC6).

## Invariants

- **Plaintext-ключ существует на клиенте только внутри открытой created-модалки**
  (React-state); не попадает в react-query кэш, localStorage, URL, console,
  test-снапшоты. Зеркало backend-инварианта «plaintext exactly once».
- Серверный гейт (`assert_within_limit`, 403) — единственная защита выпуска;
  клиентский plan-гейт — UX. Скрытие кнопки ≠ контроль доступа.
- Список рендерится только из `ApiKeyRead` (без key/key_hash — их и нет в типе).
- Типы — только из `gen.types.ts` (C1, TASK-019), ручных интерфейсов нет.
- Существующие секции settings не меняют разметку/test-id (e2e
  `billing-account.spec.ts` остаётся зелёным без правок селекторов).

## Edge cases

- 403 на POST при гонке (план истёк между рендером и кликом) → error-message
  «available on the Trader plan» + CTA, не краш.
- `navigator.clipboard` недоступен (http-контекст/старый браузер) → ключ
  остаётся выделяемым текстом + подсказка «copy manually»; кнопка Copy показывает
  ошибку, модал не закрывается.
- Закрытие модалки кликом мимо/Esc сразу после создания → ключ потерян осознанно:
  в модалке предупреждение «You won't see this key again»; подтверждающая кнопка
  «I've copied the key» (паттерн: закрытие = осознанное действие).
- Имя ключа: пустое/слишком длинное → клиентская валидация по границам схемы
  (min/max из OpenAPI), 422 от сервера — fallback-сообщение.
- Двойной клик Create → кнопка disabled на `isPending` (иначе два ключа).
- 404 на DELETE (ключ уже отозван в другой вкладке) → invalidate list, тост/текст
  «Key not found» — список сходится с сервером.
- Mobile: секция — те же `md:grid-cols-[1fr_320px]`-паттерны settings; таблица
  ключей схлопывается в карточки/однострочники (`flex-wrap`), touch-target ≥44px.

## Test plan

- unit (vitest, `frontend/tests/unit/api-keys/`): api-слой (пути/методы,
  unwrap data); error-message (403 envelope → Trader-CTA-текст, 404, generic);
  рендер секции — upgrade-ветка для free/pro, empty-state, список с revoked,
  created-modal показывает key и НЕ показывает после закрытия (повторный рендер).
- integration: не требуется на фронте (контрактные тесты CRUD живут в backend с
  TASK-028 и не меняются).
- e2e (Playwright, паттерн `tests/e2e/billing-account.spec.ts`): Free-юзер →
  settings → секция с CTA → клик → `/billing`; Trader-цикл (выпуск → modal →
  revoke) — при наличии paid-сидинга, иначе ручная G2.
- security: стадия 5.5 ОБЯЗАТЕЛЬНА (секрет в UI): проверить отсутствие plaintext
  в кэше/storage/логах, copy-flow, отсутствие ключа в e2e-артефактах
  (скриншоты/трейсы Playwright на шаге модалки — замаскировать или не снимать).

## Checkpoints

current_step: 7
baseline_commit: "c390c4c"
branch: "task/065-api-keys-ui"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — vitest 220/220, eslint, tsc -b, vite build зелёные; e2e + живой цикл ключа — CI/owner, см. Details)
- [x] 5 review (APPROVE — 0 CRITICAL/HIGH, 2 LOW-наблюдения без правок)
- [x] 5.5 security (APPROVE — plaintext-инвариант подтверждён; LOW: retain-on-failure video/trace — нота для будущих paid-plan e2e добавлена в спеку)
- [x] 6 ship (PR #90 → main, https://github.com/BotNet1337/trend-pulse/pull/90; merge — оркестратор)
- [x] 7 learnings (auto — docs/learnings.md)
debug_runs: []

## Details

(planned 2026-06-11: монетизационная витрина API-фичи Trader-плана ($99,
TASK-049). Backend-контракт TASK-028 заморожен и уже в типах; весь diff —
изолированный feature-модуль + одна секция в settings. Plaintext-дисциплина —
центральный инвариант ревью.)

(do/verify 2026-06-11, ветка `task/065-api-keys-ui`):
- @testing-library/react в проекте не установлен (паттерн: unit = чистые
  функции, node env) → «рендер-тесты секции» из Test plan реализованы как
  (а) unit на чистые хелперы (`lib.ts`: validateApiKeyName/isApiKeyRevoked,
  error-message) + мок apiClient для api-слоя, (б) e2e `api-keys.spec.ts`
  (CTA-ветка Free, серверный 403, изоляция 5xx). Консервативный дефолт —
  без новых dev-зависимостей.
- Plaintext-инвариант: `ApiKeyCreated` идёт из `mutateAsync` → локальный
  state модалки, сразу после — `createMutation.reset()` (секрет не живёт в
  mutation state); list-кэш — только `ApiKeyRead`.
- e2e Trader-цикла (выпуск→copy→revoke) нет в автотестах: e2e-окружение
  регистрирует только Free (нет paid-сидинга) — зафиксировано в спеке,
  ручная G2-проверка на стеке = owner-шаг (psql UPDATE plan='team' +
  активная Subscription, гочча TASK-049).
- verify: vitest 220/220, eslint чисто, `tsc -b` чисто, `vite build` ок;
  `make up`/локальный стек недоступны (bridge-подсети исчерпаны) → runtime
  e2e уйдёт в CI на PR.

(review/security 2026-06-11): оба APPROVE, 0 CRITICAL/HIGH. LOW-наблюдения:
двойной клик revoke (микроокно до isPending, паттерн соседа — без правки);
copied-индикатор не сбрасывается до закрытия модалки (сознательный UX);
глобальный Playwright `video/trace: retain-on-failure` — канал утечки
plaintext для БУДУЩИХ paid-plan e2e (текущие тесты модалку не открывают) →
профилактическая нота `test.use({video:'off',…})` добавлена в шапку
api-keys.spec.ts; тестовый литерал `tp_def67890_plaintext` — фиктивный.
