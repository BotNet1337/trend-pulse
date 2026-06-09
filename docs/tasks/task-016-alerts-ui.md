---
id: TASK-016
title: Alerts UI — лента/история алертов + детальный просмотр (+ тонкий backend GET /alerts)
status: in-progress      # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "68f48afd8f100b4adeb4f1a6cfabf11dcbf52520"
branch: "gsd/phase-016-alerts-ui"
tags: [frontend, alerts, backend-read-endpoint, e2e]
---

# TASK-016 — Alerts UI (Epic C · C4)

> Лента/история алертов TrendPulse + детальный просмотр (score, topic, канал, first_seen, кол-во каналов, delivery_status). Требует **тонкой backend-добавки `GET /alerts`** (read-only, tenant-scoped, пагинация, окно истории по плану) — такого роута НЕТ, добавляем поверх таблицы alerts (task-008/009). UI: лента + детально + UX **пустого состояния** и **лимита истории по плану** (Free — нет истории). Всё за guard (C2), реальные данные через nginx. e2e: лента, детально, пустое состояние, auth-guard.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §1, §4): итог для пользователя — viral alert (`🔥 Viral alert [crypto] — "Bitcoin ETF approval" · Score: 94 · 47 каналов за 23 мин · first seen 14:02`). Алерты генерит scorer ([task-008](./task-008-scorer.md)) и доставляет delivery ([task-009](./task-009-alert-delivery.md)) в таблицу `alerts` (score, topic, channel, first_seen, channels_count, delivery_status). **Read-роута `GET /alerts` для UI НЕТ** — C4 добавляет тонкий read-роут поверх существующей таблицы.

История по плану (overview §6): Free — **без истории** (только real-time доставка в Telegram); Pro — история 30 дней; Team — 90 дней. Окно истории — из `billing/plans.py` (`PLAN_LIMITS`), backend применяет его в `GET /alerts` (источник истины), UI показывает соответствующее состояние (Free → «история доступна на Pro+»).

База: [task-013](./task-013-frontend-foundation.md) (дизайн-система, клиент, типы — регенерить после добавления `GET /alerts` в OpenAPI), [task-014](./task-014-auth-flow-ui.md) (guard, `current_user`/`plan`). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — backend-добавка: read-only, tenant-scoped, full type hints, Pydantic на границе, no magic literals (окно истории/лимит пагинации — из plans/settings), SQLAlchemy bind-params.

## Goal

После задачи: пользователь видит ленту своих алертов (`GET /alerts`, пагинация), открывает детальный просмотр (score, topic, канал, first_seen, channels_count, delivery_status); при отсутствии алертов — дружелюбный empty-state; на плане Free (без истории) — состояние «история на Pro+» с апселлом; окно истории (30/90 дней) применяется backend по плану; неавторизованный — guard-redirect. e2e покрывают ленту, детально, пустое состояние, auth-guard через nginx. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по task-008/009 + overview §6; обратимы. -->
- Q: Откуда UI берёт алерты? → A: нового read-роута нет → Decision: **тонкая backend-добавка** `GET /alerts` (read-only, за `current_user`, tenant-scoped) поверх таблицы `alerts` (task-008/009): поля score, topic, channel, first_seen, channels_count, delivery_status; пагинация (limit/offset или cursor); окно истории по плану. Никаких мутаций.
- Q: Пагинация — какой контракт? → A: список может быть длинным → Decision: limit/offset (или cursor по `first_seen`); `limit` по умолчанию и максимум — named constant/settings (no magic literal); ответ — конверт `{items, total/next}` (паттерн API Response Format).
- Q: Окно истории по плану? → A: overview §6 (Free нет / Pro 30д / Team 90д) → Decision: backend применяет окно из `PLAN_LIMITS` (`billing/plans.py`) — Free возвращает пусто/`403`-feature для истории (выбрать: read-роут отдаёт только real-time-недоступную пустоту для Free → UI показывает апселл; либо `403` feature). **Решение:** `GET /alerts` для Free отдаёт пустой список + флаг «history_unavailable» (мягкий UX), не `403` (лента — базовая фича, ограничение — глубина истории). Окно/флаг — из плана, не magic literal.
- Q: Что в детальном просмотре? → A: §1/§4 + delivery → Decision: score, topic, канал, first_seen, channels_count (кол-во каналов), delivery_status (delivered/failed/pending из task-009). Детали — отдельный роут `GET /alerts/{id}` или элемент списка (решение исполнителя; tenant-scoped, `404` на чужой).
- Q: Регенерация типов? → A: новый роут меняет OpenAPI → Decision: после добавления `GET /alerts` — перегенерить `gen.types.ts` (script из C1); UI на сгенерённых типах, не ручных.

## Scope
> **frontend** (лента/детали/empty-state) + **тонкая backend-добавка `GET /alerts`** (read-only, tenant-scoped, пагинация, окно истории по плану) и её тесты. Scorer/delivery (task-008/009) НЕ трогаем — только читаем таблицу `alerts`.

- **Touch ONLY (создать/изменить):**
  - **Backend (тонкая additive read-добавка):**
    - `backend/src/trendpulse/api/alerts/__init__.py`, `backend/src/trendpulse/api/alerts/router.py` — **новый** `APIRouter(prefix="/alerts")`: `GET /alerts` (list, пагинация, окно истории по плану), опц. `GET /alerts/{id}` (detail); все за `Depends(current_user)`, tenant-scoped `(user_id)`.
    - `backend/src/trendpulse/api/alerts/schemas.py` — Pydantic `AlertRead` (score, topic, channel, first_seen, channels_count, delivery_status), `AlertListResponse` (items + пагинация-метаданные + `history_unavailable` флаг).
    - `backend/src/trendpulse/api/alerts/service.py` — read поверх таблицы `alerts` (репозиторий task-002/008/009), фильтр по `user_id` + окно истории из `PLAN_LIMITS` (`billing/plans.py`, seam); лимит пагинации из settings/named constant.
    - `backend/src/trendpulse/api/main.py` — `include_router(alerts.router)`.
    - `backend/tests/unit/test_alerts_read.py`, `backend/tests/integration/test_alerts_api.py` — AC: tenant-scope, пагинация, окно истории по плану, `401` без cookie.
  - **Frontend:**
    - `frontend/src/pages/alerts/**` — **новые** страницы: лента (`/alerts`), детальный просмотр (`/alerts/:id` или панель).
    - `frontend/src/features/alerts/**` — **новый** feature: query `useAlerts` (пагинация), `useAlert` (detail) на типах из gen.types (после регенерации).
    - `frontend/src/entities/alert/**` — **новая** entity: модель `AlertRead`, карточка ленты (score-бейдж, topic, канал, first_seen, channels_count, delivery_status).
    - `frontend/src/shared/api/gen.types.ts` — **регенерировать** после добавления `GET /alerts` (script C1).
    - `frontend/src/app/router/**` — alerts-роуты за guard (C2).
    - `frontend/tests/e2e/alerts.spec.ts` — **новый** e2e: лента, детально, пустое состояние, auth-guard.
    - `frontend/tests/unit/alerts/**` — **новые** unit: карточка/пагинация/empty + history-unavailable состояние.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `backend/src/trendpulse/{collector,pipeline,scorer,alerts}/**` ядро scorer/delivery (task-008/009 — только читаем таблицу `alerts` через репозиторий, не меняем генерацию/доставку), `billing/**` (только seam чтения `PLAN_LIMITS`). Не реализовывать watchlists/billing-экраны (C3/C5). Никаких мутаций алертов (read-only).
- **Blast radius:** новый read-роут `GET /alerts` + alerts-экраны; первый «потребитель данных pipeline» во фронте. Окно истории завязано на `PLAN_LIMITS` (seam в billing) — апселл связывает с C5. Backend-добавка аддитивна (read-only за `current_user`), scorer/delivery не меняются. Регенерация типов добавляет alerts-операции в gen.types.

## Acceptance Criteria
- [ ] **AC1 — лента показывает алерты пользователя (failing-test anchor).** Given пользователь с алертами в таблице `alerts`, When открывает `/alerts`, Then `GET /alerts` → `200`, UI рендерит ленту (score, topic, канал, first_seen, channels_count, delivery_status). e2e + integration пишутся ПЕРВЫМИ (RED).
- [ ] **AC2 — `GET /alerts` 401/200, tenant-scoped, пагинация (backend-добавка).** Given новый read-роут, When без cookie → `401`; с cookie → `200` только свои алерты (чужие не видны); пагинация (limit/offset или cursor) работает, `limit` ограничен named-константой.
- [ ] **AC3 — детальный просмотр.** Given алерт пользователя, When открывает детали, Then показаны score, topic, канал, first_seen, channels_count, delivery_status; чужой/несуществующий `id` → not-found (`404`).
- [ ] **AC4 — пустое состояние.** Given у пользователя нет алертов, When открывает `/alerts`, Then дружелюбный empty-state (объяснение + CTA на создание watchlist, C3), не пустой экран/ошибка.
- [ ] **AC5 — лимит истории по плану.** Given план Free (без истории), When открывает `/alerts`, Then backend применяет окно из `PLAN_LIMITS` (Free → пусто + `history_unavailable`), UI показывает «история доступна на Pro+» + апселл; Pro/Team — история в пределах 30/90 дней.
- [ ] **AC6 — auth-guard.** Given неавторизованный пользователь, When заход на `/alerts`, Then guard-redirect на `/login` (`401`), данные не запрашиваются.
- [ ] **AC7 — поведенческая (G2) через nginx.** Given `make up` (+ сид нескольких алертов в БД), When Playwright `alerts.spec.ts` гоняется против реального стека за nginx, Then AC1/AC3/AC4/AC6 наблюдаемы; артефакты (trace/screenshot/video on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-016-alerts-ui`.
1. **RED (backend):** `backend/tests/integration/test_alerts_api.py` — `GET /alerts` 401 без cookie / 200 только свои + пагинация. Падает (роута нет). AC2-якорь.
2. Backend-добавка: `api/alerts/{router,schemas,service}` — `GET /alerts` (read-only, tenant-scoped, пагинация, окно истории из `PLAN_LIMITS`), `AlertRead`/`AlertListResponse` (+`history_unavailable`); `include_router`. `make ci-fast` зелёный.
3. Регенерировать `gen.types.ts` (script C1) — alerts-операции в типах.
4. **RED (frontend):** `frontend/tests/e2e/alerts.spec.ts` — лента показывает алерты. Падает. AC1-якорь.
5. `entities/alert` + `features/alerts` (useAlerts/useAlert) + `pages/alerts` (лента, детально, empty-state, history-unavailable+апселл); роуты за guard (C2).
6. unit-тесты (карточка/пагинация/empty/history-unavailable); **GREEN** локально.
7. **G2:** `make up` (+сид алертов); Playwright `alerts.spec.ts` зелёный через nginx (AC1/AC3/AC4/AC6/AC7); backend integration зелёный (AC2/AC5).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Backend-добавка — read-only, tenant-scoped, за `current_user`** — `GET /alerts` фильтрует по `user_id` (чужие не видны, `404` на чужой detail-id); никаких мутаций алертов.
- **Окно истории — из `PLAN_LIMITS`** (`billing/plans.py`), не magic literal; лимит пагинации — named constant/settings. SQL — SQLAlchemy bind-params, full type hints, Pydantic на границе (CONVENTIONS).
- **Backend — источник истины по истории/плану** — фронт показывает то, что вернул backend (+`history_unavailable`), не дублирует окна 30/90 как inline-числа.
- **Cookie-auth, реальные данные через nginx** — `withCredentials: true`; e2e/прод против реального API за edge, не моки.
- **Единая дизайн-система** (C1) — карточки/детали/empty-state/баннеры на общих токенах; responsive + базовая a11y (score-бейдж и статус доступны скринридеру).
- **Не трогаем scorer/delivery** (task-008/009) — только читаем таблицу `alerts` через публичный репозиторий/сервис (cross-module через интерфейсы).

## Edge cases
- Пустая таблица `alerts` у пользователя → empty-state (AC4), не `500`/пустой экран.
- Free-план → история недоступна: backend отдаёт пусто+`history_unavailable`, UI — апселл, не сырой `403`.
- Очень длинная лента → пагинация (limit из настройки); бесконечная прокрутка/«показать ещё» без загрузки всего разом.
- `delivery_status` = failed/pending → визуально отличимый статус (не только delivered); пользователь видит, что доставка не прошла.
- Чужой/несуществующий alert-id в detail → `404` not-found (tenant-scope, не утечка).
- Алерт без некоторых полей (напр. channels_count = 0 на грани) → отображение без поломки; дефолты из типов, не падать.
- Часовые пояса в `first_seen` → отображать консистентно (UTC→локаль), не путать пользователя.

## Test plan
- **unit (backend):** `test_alerts_read.py` — tenant-scope (только свои), пагинация (limit-cap из константы), окно истории по плану (Free пусто+флаг, Pro/Team окно), `404` на чужой detail-id.
- **integration (backend):** `test_alerts_api.py` — AC2 (`GET /alerts` 401/200, tenant-scoped, пагинация, RED-якорь), AC5 (окно истории по плану против реальной БД).
- **unit (frontend):** `tests/unit/alerts/**` — карточка ленты, пагинация-хук, empty-state, history-unavailable+апселл состояние.
- **e2e (Playwright):** `tests/e2e/alerts.spec.ts` — AC1 (лента, RED-якорь), AC3 (детально + чужой id 404), AC4 (пустое состояние), AC6 (no-auth → `/login`). Артефакты on-failure.
- **runtime/behavioral (G2):** `make up` (+сид алертов) → Playwright против реального стека за nginx (AC7); ручная проверка delivery_status-отображения и history-апселла (Free).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 4
baseline_commit: "68f48afd8f100b4adeb4f1a6cfabf11dcbf52520"
branch: "gsd/phase-016-alerts-ui"
lock: "loop-016"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — build + Playwright e2e + real behavior через nginx)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (XSS/санитизация, secrets не в бандле, cookie/CSRF, SSRF в webhook-полях)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-003/004 и контексту: лента/история/детали алертов + тонкая backend-добавка `GET /alerts` (read-only, tenant-scoped, пагинация, окно истории из PLAN_LIMITS поверх таблицы alerts task-008/009), UX пустого состояния и лимита истории (Free — апселл). deps: 014 (guard/current_user), backend 008 (scorer), 009 (delivery). Scorer/delivery не трогаем — только читаем. locate+plan выполнены этим планированием — executor стартует с «3 do».)
