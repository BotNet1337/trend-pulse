---
id: TASK-015
title: Watchlists UI — список/создание/редактирование/удаление, alert-config, UX лимитов плана
status: done             # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "b55527ee46d9cf04f34c8cbb9d01e66882f9620f"
branch: "gsd/phase-015-watchlists-ui"
tags: [frontend, watchlists, crud, plan-limits, e2e]
---

# TASK-015 — Watchlists UI (Epic C · C3)

> UI управления watchlist'ами TrendPulse поверх готового API (task-004): список/создание/редактирование/удаление (один watchlist = **один канал + topic + alert_config**, адресуется числовым `id`), форма alert-config (пороги скоринга), и аккуратный **UX лимитов плана** — `402` quota / `403` feature превращаем в понятный апселл (а не сырой error), невалидный handle (`422`) подсвечиваем на поле. Все экраны — за guard (C2), реальные данные через nginx. e2e: CRUD happy + negative (чужой/несуществующий 404, bad handle 422, превышение лимита 402, без auth 401).

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §3) — watchlist = публичный канал + топик + alert-config. API реализован в [task-004](./task-004-watchlist-api.md) (USER DECISION: **один watchlist = одна junction-строка** — один канал + topic + alert_config, числовой `id`; несколько каналов = несколько watchlist'ов). Реальные роуты (источник истины, всё за cookie-auth `current_user`): `POST /watchlists` (201 `WatchlistRead`; **402** при превышении лимита плана; **422** bad handle; **409** dup), `GET /watchlists` (только свои), `GET /watchlists/{id}`, `PATCH /watchlists/{id}`, `DELETE /watchlists/{id}` (204). Лимиты плана централизованы в backend `billing/plans.py` (`PLAN_LIMITS`); превышение → `402` (quota) / `403` (feature).

База: [task-013](./task-013-frontend-foundation.md) (дизайн-система, API-клиент, типы), [task-014](./task-014-auth-flow-ui.md) (guard, `current_user`/`plan` из `GET /users/me`). Тарифы (overview §6): Free — 5 каналов/1 топик; Pro — 100 каналов/5 топиков; Team — 500/∞. UI читает текущий `plan` из `current_user`, но **источник истины по лимитам — backend** (402/403), фронт не дублирует числа как magic literals — показывает то, что вернул backend, и текущий план.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md). C3 — **frontend-only** (API уже есть, backend-добавок нет). Pydantic-контракты watchlist — из типов C1.

## Goal

После задачи: пользователь видит список своих watchlist'ов (`GET /watchlists`), создаёт новый (канал-handle + топик + alert-config: пороги скоринга) → `POST /watchlists`; редактирует (`PATCH`) и удаляет (`DELETE`); невалидный handle подсвечивается на поле (`422`); превышение лимита плана (`402` quota) показывает понятный апселл-баннер (а не сырой error), feature-gate (`403`) — соответствующее сообщение; `409` dup — понятное «уже есть»; чужой/несуществующий `id` → not-found-состояние (`404`); без auth (`401`) → guard-redirect. Все экраны responsive, базовая a11y, реальные данные через nginx. e2e покрывают CRUD happy + все negative. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по task-004 контракту; обратимы. -->
- Q: Модель watchlist в UI? → A: один watchlist = один канал + topic + alert_config (USER DECISION в task-004) → Decision: форма создания = один handle + topic + alert-config; список — карточки/строки по `id`; «добавить ещё канал» = создать новый watchlist. Без мульти-канальной формы.
- Q: Что в alert-config форме? → A: пороги скоринга (overview §4: `score_threshold`, `min_channels`, `notification_lang`) → Decision: форма — `score_threshold` (0..100), `min_channels` (≥1), `notification_lang` (ISO-639-1 select); диапазоны/опции из типов backend, не magic literals на фронте.
- Q: Как показывать лимит плана? → A: backend отдаёт `402`/`403`, фронт — апселл → Decision: `402` (quota: достигнут лимит каналов/топиков плана) → апселл-баннер «обновите план» + ссылка на биллинг (C5); `403` (feature недоступна на плане) → feature-gate сообщение. **Не** хардкодим числа лимитов — показываем текущий `plan` (из `current_user`) и сообщение backend; точные лимиты для копи берём из единого источника (типы/overview §6, не inline-магия).
- Q: Валидация handle на фронте? → A: backend = источник истины (`422`) → Decision: клиентская предвалидация формата `@handle` (UX, мгновенный фидбек) + серверный `422` подсвечивает поле с сообщением backend; не дублируем regex как magic literal — общая константа формата (shared).
- Q: Чужой/несуществующий id? → A: `404` (task-004: чужой неотличим от несуществующего) → Decision: not-found-состояние на странице деталей/редактирования; список показывает только свои (`GET /watchlists` уже tenant-scoped).
- Q: 409 duplicate? → A: backend `409` при дубле `(user_id, channel, topic)` → Decision: понятное «такой watchlist уже есть», без падения; форма остаётся заполненной.

## Scope
> **frontend-only.** API watchlist полностью готов (task-004) — backend НЕ трогаем.

- **Touch ONLY (создать/изменить):**
  - `frontend/src/pages/watchlists/**` — **новые** страницы: список (`/watchlists`), создание (`/watchlists/new`), детали/редактирование (`/watchlists/:id`).
  - `frontend/src/features/watchlists/**` — **новый** feature: queries/mutations (`list`, `get`, `create`, `update`, `delete`) на типах C1; маппинг ошибок 402/403/422/404/409 в UX-состояния.
  - `frontend/src/entities/watchlist/**` — **новая** entity: модель/типы watchlist (`WatchlistRead`, `ChannelRef`, `AlertConfig`) из gen.types; карточка/строка списка.
  - `frontend/src/features/watchlists/alert-config-form.tsx` — форма alert-config (`score_threshold`/`min_channels`/`notification_lang`), валидация диапазонов из типов.
  - `frontend/src/shared/components/**` — переиспользуемые UI (апселл-баннер, empty-state, поле с inline-ошибкой) если ещё нет.
  - `frontend/src/shared/lib/**` — общая константа формата handle + helper маппинга backend-ошибок (402→quota, 403→feature, 422→field, 404→not-found, 409→dup).
  - `frontend/src/app/router/**` — зарегистрировать watchlist-роуты за guard (C2).
  - `frontend/tests/e2e/watchlists.spec.ts` — **новый** e2e: CRUD happy + negative.
  - `frontend/tests/unit/watchlists/**` — **новые** unit: форма/валидация/маппинг ошибок.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, **весь `backend/**`** (API watchlist готов, лимиты в `billing/plans.py` — не дублировать на фронте), `collector/**`/`pipeline/**`/`scorer/**`/`alerts/**`/`billing/**`. Не реализовывать alerts/billing-экраны (C4/C5). Не вводить мульти-канальную форму (модель = один канал/watchlist).
- **Blast radius:** новые watchlist-экраны — первый «рабочий» CRUD-флоу SPA; задаёт паттерн маппинга backend-ошибок (402/403/422/404/409) в UX, переиспользуемый C4/C5. Апселл-баннер (`402`) ссылается на биллинг-экран C5 (мягкая связь). Только потребляет API task-004, контракт не меняет.

## Acceptance Criteria
- [ ] **AC1 — create watchlist → появляется в списке (failing-test anchor).** Given залогиненный пользователь, When заполняет форму (handle + topic + alert-config) и сабмитит, Then `POST /watchlists` → `201`, UI показывает новый watchlist в списке (`GET /watchlists`). e2e пишется ПЕРВЫМ (RED).
- [ ] **AC2 — list/get/update/delete свои.** Given существующие watchlist'ы пользователя, When список → детали → редактирование (`PATCH`) → удаление (`DELETE` 204), Then UI отражает каждое изменение; после удаления элемент исчезает из списка.
- [ ] **AC3 — bad handle → `422` подсвечивает поле.** Given невалидный `@handle` (формат), When сабмит, Then backend `422`, UI подсвечивает поле handle с понятным сообщением (не сырой JSON), watchlist не создаётся.
- [ ] **AC4 — превышение лимита плана → апселл, не raw-error.** Given план Free на лимите каналов/топиков, When создание сверх лимита, Then backend `402` (quota), UI показывает апселл-баннер «обновите план» + ссылку на биллинг (C5); `403` (feature) → feature-gate-сообщение; сырой error не показывается.
- [ ] **AC5 — duplicate → понятное сообщение.** Given watchlist с тем же `(канал, топик)` уже есть, When повторное создание, Then backend `409`, UI показывает «уже существует», форма не теряет данные, не падает.
- [ ] **AC6 — чужой/несуществующий id → not-found.** Given `id` чужого/несуществующего watchlist'а, When открытие деталей/редактирования, Then backend `404`, UI показывает not-found-состояние (не утечка существования).
- [ ] **AC7 — auth-guard + поведенческая (G2) через nginx.** Given неавторизованный пользователь, When заход на `/watchlists`, Then guard-redirect на `/login` (`401`); и: `make up` → Playwright `watchlists.spec.ts` гоняется против реального стека за nginx, AC1–AC6 наблюдаемы, артефакты (trace/screenshot/video on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-015-watchlists-ui`.
1. **RED:** `frontend/tests/e2e/watchlists.spec.ts::create_appears_in_list` — логин → создать watchlist → ожидать в списке. Падает (страниц нет). AC1-якорь.
2. `entities/watchlist` — модель/типы из gen.types; `features/watchlists` — queries/mutations (list/get/create/update/delete) на API task-004.
3. `pages/watchlists` — список (empty-state), создание (форма handle+topic+`alert-config-form`), детали/редактирование; роуты за guard (C2).
4. `shared/lib` — helper маппинга ошибок (402→quota-апселл, 403→feature, 422→field, 404→not-found, 409→dup); общая константа формата handle (клиентская предвалидация).
5. UX лимитов: апселл-баннер (`402`) + ссылка на биллинг (C5); feature-gate (`403`); inline-ошибки поля (`422`).
6. unit-тесты (форма/валидация/маппинг ошибок); **GREEN** локально.
7. **G2:** `make up`; Playwright `watchlists.spec.ts` зелёный через nginx (AC1–AC7).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Backend — источник истины по лимитам.** Фронт не дублирует числа лимитов как magic literals; реагирует на `402`/`403` от backend и показывает текущий `plan`. Точные числа для копи — из единого источника (типы/overview §6), не inline.
- **Cookie-auth, tenant-scoped** — все запросы `withCredentials: true`; список/детали — только свои (`404` на чужой id, не утечка).
- **Понятные ошибки, не raw.** 402/403/422/404/409 маппятся в UX-состояния (апселл/feature/field/not-found/dup); пользователю не показывается сырой JSON/стек.
- **Единая дизайн-система** (C1) — формы/карточки/баннеры на общих токенах/компонентах; responsive + базовая a11y (label/aria/focus, ошибки доступны скринридеру).
- **Реальные данные через nginx** — e2e и прод дёргают реальный API task-004 за edge; никаких моков в проде.
- **Модель = один канал/watchlist** (USER DECISION task-004) — без мульти-канальной формы.

## Edge cases
- Пустой список watchlist'ов → дружелюбный empty-state с CTA «создать первый», не пустой экран.
- `min_channels` > 1 при модели «один канал» — это параметр скоринга (cross-channel), не число каналов watchlist'а; форма поясняет (tooltip), не валидирует как противоречие.
- `score_threshold` вне 0..100 / `min_channels` < 1 → клиентская валидация + серверный `422`; поле подсвечено.
- Одновременное удаление в двух вкладках → второй `DELETE` на уже удалённый `id` → `404`, UI деградирует мягко (элемент уже исчез).
- `402` на грани лимита (TOCTOU на backend — known-limitation task-010) → UI просто показывает апселл, не пытается «обойти».
- Невалидный `notification_lang` → `422`, select ограничен валидными ISO-кодами (из типов), inline-ошибка как фолбэк.
- Длинный/юникодный topic → отображение без поломки layout (truncate + title).

## Test plan
- **unit:** `tests/unit/watchlists/**` — `alert-config-form` (валидация диапазонов/lang), helper маппинга ошибок (402/403/422/404/409 → корректные UX-состояния), клиентская предвалидация handle.
- **e2e (Playwright):** `tests/e2e/watchlists.spec.ts` — AC1 (create→в списке, RED-якорь), AC2 (list/get/update/delete), AC3 (bad handle 422 → поле), AC4 (лимит 402 → апселл; 403 → feature), AC5 (409 → dup-сообщение), AC6 (чужой/несущ. id → not-found), AC7 (no-auth → `/login`). Артефакты on-failure.
- **runtime/behavioral (G2):** `make up` → Playwright против реального стека за nginx (AC7); ручная проверка апселл-ссылки на биллинг (C5) и tenant-изоляции списка.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "b55527ee46d9cf04f34c8cbb9d01e66882f9620f"
branch: "gsd/phase-015-watchlists-ui"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — build + Playwright e2e + real behavior через nginx; 8/8 e2e за nginx, 61 unit)
- [x] 5 review (auto, adversarial — PASS, 0 blocking)
- [x] 5.5 security (PASS, 0 blocking — XSS-safe, tenant-isolation, no secrets)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-003/004 и контексту: watchlist-CRUD UI поверх готового API task-004 (модель «один канал/watchlist», числовой id), форма alert-config (пороги скоринга), UX лимитов плана (402 quota→апселл, 403 feature→gate, 422→field, 404→not-found, 409→dup). frontend-only, backend не трогаем. deps: 014 (guard/current_user), backend 004 (watchlist API). locate+plan выполнены этим планированием — executor стартует с «3 do».)

### Step 3 do · 4 verify · 5 review · 5.5 security · loop-015 (frontend-only)
- **do (TDD):** `entities/watchlist` (модель из gen.types `WatchlistRead`/`AlertConfig`/`ChannelRef`), `features/watchlists` (react-query list/get/create/update/delete + `alert-config-form` + `alert-config-validation`), `pages/watchlists/{list,create,detail}` за guard, `shared/lib/{backend-error,handle-format}`, `shared/components/{upsell-banner,empty-state}`. alert_config: `score_threshold` 0..100, `min_channels`≥1, `notification_lang` ISO-639-1 — из типов, не magic. Error-map: 402→quota-апселл, 403→feature-gate, 422→field (Pydantic detail[] устойчивый парс), 404→not-found, 409→dup. Коммиты dd0eeb8, 2d44cd9.
- **verify (G2):** build/tsc/lint зелёные, vitest 61 (44 новых unit), Playwright 8/8 за nginx — AC1 create→list, AC2 list/edit/delete, AC3 bad-handle→422, AC4 реальный 402 (лимит Free=5)→апселл, AC5 409→dup, AC6 404→not-found, AC7 no-auth→guard. 403 — unit.
- **review (opus) PASS + security (opus) PASS — 0 blocking.** Числа лимитов НЕ хардкожены; XSS-safe (JSX auto-escape); tenant-isolation (404=not-found); HANDLE_REGEX без ReDoS; типы из gen.types. LOW-фикс: `enabled:!Number.isNaN(id)`.
- **Долг (→ C5/017):** роут `/billing` не зарегистрирован — апселл-ссылка ведёт в NotFound (task санкционирует заглушку до C5). LOW: detail-форма без реинициализации на фоновый рефетч.
