---
id: TASK-033
title: GDPR data-export — GET /account/export (Art.20 portability), tenant-scoped, без секретов
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-033-gdpr-data-export"
tags: [epic-d, backend, compliance, gdpr]
---

# TASK-033 — GDPR data-export (Epic D)

> Реализовать **GDPR Art.20 portability** (сейчас есть только erasure — `DELETE /account`). Новый эндпоинт `GET /account/export` (или `POST` + async Celery-job, если объём велик) отдаёт ВСЕ персональные данные `current_user` (профиль, watchlists, alerts, delivery-config — **токены маскированно/исключить секреты**, subscription/billing-история) в машиночитаемом формате (JSON, опц. zip). Tenant-scoped строго `current_user.id` (как delete, `backend/src/compliance/account.py`). Security 5.5: не светить секреты (`telegram_bot_token` маскированно), tenant-scope (no IDOR), rate-limit (тяжёлая операция). DoD — Acceptance Criteria ниже.

## Context

TrendPulse — [task-011](./task-011-compliance-retention-gdpr.md) реализовал GDPR **erasure**: `backend/src/compliance/account.py::delete_user(session, user_id)` — единственный delete-путь, один `DELETE FROM users WHERE id=:id` (bind param), `ON DELETE CASCADE` снимает все зависимые строки (watchlists/clusters/scores/alerts/posts/subscriptions/oauth_accounts — [task-002](./task-002-data-model.md)/[ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md)). Эндпоинт `DELETE /account` (`backend/src/api/routes/account.py`) — tenant-scoped: передаёт ТОЛЬКО `current_user.id` в `delete_user` (пользователь удаляет только себя), 204.

**Portability (Art.20) отсутствует** — нет эндпоинта выгрузки данных. Это симметрично erasure: тот же tenant-scope, тот же набор user-owned таблиц (но READ вместо DELETE).

Релевантные данные `current_user` (по моделям/роутам):
- Профиль: `User` (email, plan, is_verified, …) — `api/auth/me.py` (`GET /users/me`).
- Watchlists: `api/watchlist/` (tenant-scoped CRUD).
- Alerts: `api/alerts/` (tenant-scoped read).
- Delivery-config: `telegram_bot_token`/`chat_id`/`webhook_url` (`api/account/delivery_config.py`) — **секреты**: токен МАСКИРОВАННО (`mask_bot_token`, [task-017](./task-017-billing-account-ui.md)) или исключить; webhook_url — можно (не секрет, но осторожно).
- Subscription/billing: subscriptions-история (`billing/`).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, Pydantic на границе, tenant-scope строго `current_user.id`, секреты не в ответах/логах, no magic literals. Rate-limit: глобальный slowapi 120/min (`api/main.py`); export тяжёлый — учесть.

## Goal

После задачи: `GET /account/export` без cookie → `401`; с cookie → `200` полный машиночитаемый дамп ВСЕХ персональных данных `current_user` (профиль/watchlists/alerts/delivery-config/subscription) в JSON (опц. zip); `telegram_bot_token` маскирован/исключён, никаких секретов в дампе; строго tenant-scoped (`current_user.id` — нет чужих данных, no IDOR); валидный JSON; integration покрывает. Если объём велик — async Celery-job (`POST /account/export` → job-id → готовый файл). Security: маскирование секретов, tenant-scope, rate-limit тяжёлой операции. DoD — Acceptance Criteria.

## Discussion
<!-- durable record of clarifications. Решения по task-011 (erasure-симметрия) + overview §7; обратимы. -->
- Q: GET sync или POST async? → A: **GET sync по умолчанию** → Decision: для текущих объёмов (один пользователь: watchlists ≤500, alerts, config) sync `GET /account/export` достаточно. **Если объём окажется велик** (история alerts/posts большая) → `POST /account/export` + Celery-job (job-id, polling, готовый файл в storage) — зафиксировать порог/решение. Минимальный путь — sync GET (избегаем over-engineering); async — fallback при доказанном объёме.
- Q: Что включать? → A: все user-owned персональные данные (симметрия erasure) → Decision: профиль (`User`: email/plan/is_verified/created), watchlists (channels/topics/source_kind), alerts (история), delivery-config (chat_id/webhook_url; **токен маскированно**), subscription/billing-история. НЕ включать: чужие данные, внутренние системные поля без персональной ценности, секреты в открытом виде.
- Q: Секреты в дампе? → A: НЕ светить → Decision: `telegram_bot_token` — маскированно (`mask_bot_token` reuse, [task-017](./task-017-billing-account-ui.md)) ИЛИ исключить из дампа (portability ≠ выгрузка секретов; пользователь и так знает свой токен). `webhook_url` — можно (его собственный URL, не секрет, но не логировать). Пароль-хэш НЕ включать.
- Q: Tenant-scope? → A: строго `current_user.id` (как delete) → Decision: все запросы фильтруются по `current_user.id` (симметрия `delete_user`); сборщик данных принимает ТОЛЬКО `user_id` от `current_user` — no IDOR (нельзя экспортировать чужой аккаунт).
- Q: Формат? → A: JSON (опц. zip) → Decision: машиночитаемый JSON (Art.20 «structured, commonly used, machine-readable»); опц. `Content-Disposition: attachment` + zip если крупно. Schema-стабильный (Pydantic-модели экспорта).
- Q: Rate-limit? → A: тяжёлая операция → Decision: export дороже обычного GET (много запросов к БД); либо отдельный nginx-лимит ([task-032](./task-032-security-hardening.md) edge-rate-limit) на `/api/account/export`, либо опираемся на глобальный slowapi 120/min. Зафиксировать; не дать DoS через частый export.
- Q: Переиспользовать compliance/account.py? → A: симметрия → Decision: новый `compliance/export.py::export_user_data(session, user_id) -> dict` (READ-зеркало `delete_user`); единый источник tenant-scoped сборки данных (как `delete_user` — единый delete-путь).

## Scope
> **backend** (новый `GET /account/export` + `compliance/export.py` сборщик + export-схемы) + опц. Celery-job если async. Тонкая additive-добавка (read, за `current_user`, tenant-scoped). Erasure (`delete_user`) и доменные роуты НЕ трогаем — только читаем данные.

- **Touch ONLY (создать/изменить):**
  - **Backend:**
    - `backend/src/compliance/export.py` — **новый**: `export_user_data(session, user_id) -> ExportPayload` — tenant-scoped сборка всех user-owned данных (профиль/watchlists/alerts/delivery-config-маскированный/subscription); READ-зеркало `delete_user` (единый источник, no drift).
    - `backend/src/api/routes/account.py` — **новый** `GET /account/export` (за `Depends(current_user)`, передаёт ТОЛЬКО `current_user.id`); JSON-ответ (опц. `Content-Disposition` attachment); ИЛИ `POST /account/export`+Celery если async (решение Discussion).
    - `backend/src/api/account/schemas.py` (или `compliance/`) — Pydantic export-схемы (`ExportPayload`, под-схемы; `telegram_bot_token` маскирован/исключён).
    - **Если async:** `backend/src/compliance/tasks.py` — Celery export-job (зеркало retention-tasks паттерна); storage готового файла.
    - `backend/tests/integration/test_account_export.py` — **новый**: `401` без cookie; `200` с cookie — полный дамп; токен маскирован/исключён; tenant-scope (данные только `current_user`, не чужие — no IDOR); JSON валиден.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `landing/**`, `frontend/**` (UI-кнопка экспорта — опционально/отдельно; ядро задачи — backend-эндпоинт), `compliance/account.py::delete_user` (erasure — не трогаем, только зеркалим READ), доменная логика watchlist/alerts/billing (только читаем). SSRF/delivery-механику не меняем.
- **Blast radius:** аддитивный read-эндпоинт за `current_user` (tenant-scoped); не меняет существующие роуты/схемы. Читает много таблиц (нагрузка → rate-limit). Security-чувствительно (персональные данные + риск утечки секретов/IDOR) → **стадия 5.5 обязательна**. Если async — добавляет Celery-задачу + storage готовых файлов.

## Acceptance Criteria
- [ ] **AC1 — GET /account/export 401/200 (failing-test anchor).** Given эндпоинт, When без cookie → `401`; с cookie → `200` машиночитаемый JSON-дамп всех персональных данных `current_user`. integration пишется ПЕРВЫМ (RED — эндпоинта нет).
- [ ] **AC2 — полный набор данных.** Given залогиненный пользователь, When export, Then дамп содержит профиль (email/plan/is_verified), watchlists (channels/topics/source_kind), alerts (история), delivery-config (chat_id/webhook_url), subscription/billing-историю — симметрично erasure-набору ([task-011](./task-011-compliance-retention-gdpr.md)).
- [ ] **AC3 — секреты не светятся.** Given delivery-config в дампе, When инспекция, Then `telegram_bot_token` маскирован (`mask_bot_token`) или исключён; пароль-хэш/системные секреты отсутствуют; webhook_url присутствует (собственный URL пользователя), но не логируется.
- [ ] **AC4 — tenant-scope (no IDOR).** Given два пользователя, When user A делает export, Then дамп содержит ТОЛЬКО данные A (нет данных B); сборщик принимает только `current_user.id` (как `delete_user`); невозможно экспортировать чужой аккаунт.
- [ ] **AC5 — валидный машиночитаемый формат.** Given ответ, When парсинг, Then валидный JSON (Art.20 structured/machine-readable); схема стабильна (Pydantic export-модели); опц. `Content-Disposition: attachment`/zip если крупно.
- [ ] **AC6 — rate-limit тяжёлой операции.** Given export дороже обычного GET, When частые вызовы, Then ограничены (nginx edge-лимит на `/api/account/export` [task-032](./task-032-security-hardening.md) ИЛИ глобальный slowapi); решение зафиксировано; не DoS-able.
- [ ] **AC7 — security (5.5) + поведенческая (G2) через nginx.** Given `make up`, When `GET /api/account/export` без cookie → `401`, с cookie → `200` дамп (токен маскирован, только свои данные); Then наблюдаемо за nginx; integration зелёный (AC1–AC4); инспекция: нет секретов в ответе/логах; артефакты on-failure.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-033-gdpr-data-export`.
1. **RED:** `test_account_export.py` — `401` без cookie, `200` с cookie (полный дамп), токен маскирован, tenant-scope (A не видит B), JSON валиден. Падает (эндпоинта нет). AC1/AC3/AC4-якорь.
2. `compliance/export.py::export_user_data(session, user_id)` — tenant-scoped READ-сборка (профиль/watchlists/alerts/delivery-config-маскированный/subscription); зеркало `delete_user`-набора.
3. Export-схемы (Pydantic; токен маскирован/исключён).
4. `api/routes/account.py` — `GET /account/export` (за `current_user`, только `current_user.id`); JSON (опц. attachment). Решить sync/async (Discussion — sync по умолчанию).
5. Rate-limit решение: edge-лимит ([task-032](./task-032-security-hardening.md)) на `/api/account/export` ИЛИ глобальный slowapi — зафиксировать. AC6.
6. **GREEN + G2 + 5.5:** `make ci-fast`/`make up`; integration зелёный (AC1–AC4); export за nginx (AC7); security 5.5 — нет секретов в дампе/логах, tenant-scope (no IDOR), rate-limit.
7. Обновить `tasks-index.md` на ship.

## Invariants
- **Tenant-scope строго `current_user.id`** — сборщик принимает только id от `current_user` (симметрия `delete_user`); no IDOR — нельзя экспортировать чужой аккаунт ([ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md)).
- **Секреты не в дампе** — `telegram_bot_token` маскирован/исключён (`mask_bot_token` reuse); пароль-хэш/системные секреты никогда; webhook_url не логируется (CONVENTIONS security, [task-011](./task-011-compliance-retention-gdpr.md) hygiene).
- **Симметрия erasure** — export-набор зеркалит delete-набор user-owned данных; единый сборщик (`compliance/export.py`) — no drift (как `delete_user` единый delete-путь).
- **Машиночитаемый формат (Art.20)** — structured/commonly-used JSON; стабильная Pydantic-схема; не «сырой ORM-дамп».
- **Read-only, аддитивно** — не меняет existing-роуты/данные; erasure (`delete_user`) не трогаем.
- **Rate-limit тяжёлой операции** — export не DoS-able (edge ИЛИ slowapi); решение зафиксировано.
- **No magic literals** — поля/формат из схем; rate-limit-порог named.

## Edge cases
- Пользователь без watchlists/alerts/subscription → дамп с пустыми коллекциями (не падать; `[]`/`null` валидны).
- Большой объём (много alerts/posts-истории) → sync GET может таймаутить → порог на async Celery-job (Discussion); по умолчанию sync, async — при доказанном объёме.
- `telegram_bot_token` слишком короткий для маскирования → `mask_bot_token` возвращает «set but hidden»/None (как [task-017](./task-017-billing-account-ui.md)); не светить частично.
- IDOR-попытка (передать чужой user_id) → невозможно: эндпоинт берёт только `current_user.id`, параметра user_id нет; AC4 ловит.
- Export сразу после частичного удаления данных → дамп отражает текущее состояние БД (консистентность транзакции).
- Частый export (DoS) → rate-limit отклоняет (AC6); тяжёлая операция не должна валить БД.
- Секрет случайно попал в дамп через nested-relation (напр. oauth-токен) → явный allow-list полей в export-схеме (не сериализовать модель целиком); AC3 ловит.
- JSON с datetime/Decimal (alerts/billing) → корректная сериализация (ISO datetime, Decimal→str/number); AC5 валидность.

## Test plan
- **integration (backend):** `test_account_export.py` — AC1 (`401` без cookie / `200` с cookie, RED-якорь), AC2 (полный набор: профиль/watchlists/alerts/delivery-config/subscription), AC3 (токен маскирован/исключён, нет секретов), AC4 (tenant-scope: A не видит B, no IDOR), AC5 (валидный JSON/схема). Async-job-тест если реализуем.
- **runtime/behavioral (G2):** `make up` → `GET /api/account/export` за nginx (без cookie→401, с cookie→200 дамп) — AC7; инспекция ответа на отсутствие секретов; rate-limit-проверка (AC6).
- **security (5.5 обязательна):** секреты не в дампе/логах (токен маскирован, нет пароль-хэша/oauth-токенов); tenant-scope (no IDOR — только `current_user`); rate-limit тяжёлой операции; персональные данные не логируются ([task-011](./task-011-compliance-retention-gdpr.md) hygiene).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-033-gdpr-data-export"
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
(initial — план по эталону [task-013](./task-013-frontend-foundation.md)/[task-017](./task-017-billing-account-ui.md) и реальному коду: GDPR erasure уже есть ([task-011](./task-011-compliance-retention-gdpr.md)) — `compliance/account.py::delete_user(session, user_id)` единый delete-путь (один cascade-DELETE, tenant-scoped только `current_user.id`), эндпоинт `DELETE /account` (`api/routes/account.py`) → 204. Portability (Art.20) ОТСУТСТВУЕТ — добавляем `GET /account/export` как READ-симметрию erasure: новый `compliance/export.py::export_user_data` (зеркало delete-набора: профиль/watchlists/alerts/delivery-config/subscription), tenant-scoped строго `current_user.id` (no IDOR — параметра user_id нет, берётся из current_user). Секреты НЕ светим: `telegram_bot_token` маскирован (reuse `mask_bot_token` из task-017) или исключён; пароль-хэш/oauth-токены — никогда (allow-list полей в export-схеме, не сериализуем ORM целиком). Формат: машиночитаемый JSON (Art.20), опц. attachment/zip. Sync GET по умолчанию (избегаем over-engineering); async Celery-job (POST+job-id) — fallback при доказанном большом объёме. Rate-limit: тяжёлая операция → edge-лимит (task-032) на /api/account/export ИЛИ глобальный slowapi 120/min — зафиксировать. Security-чувствительно → стадия 5.5 обязательна. Frontend-кнопка экспорта — опционально/вне ядра (ядро = backend-эндпоинт). deps: 011 (GDPR-delete/compliance/hygiene). locate+plan выполнены этим планированием — executor стартует с «3 do».)
