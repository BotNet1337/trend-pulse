---
id: TASK-020
title: Alerts — cursor (keyset) пагинация + составной индекс
status: planned          # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-020-alerts-cursor-pagination"
tags: [epic-d, backend, frontend, perf]
---

# TASK-020 — Alerts cursor-pagination (Epic D)

> Заменить offset/limit-пагинацию `GET /alerts` (task-016) на keyset/cursor по `(first_seen, id)` — стабильно и быстро при росте таблицы (offset деградирует и даёт дубли/пропуски на вставке). Backend `api/alerts/{service,router,schemas}`: opaque-cursor, `AlertListResponse` + `next_cursor`. Составной индекс `Index("ix_alerts_user_first_seen","user_id","first_seen")` (модель + Alembic-миграция `0006`). Frontend `features/alerts` `useAlerts` — infinite-query по cursor. Сохранить tenant-scope (`Alert.user_id`) и history-window (`PLAN_LIMITS`) из task-016. Бизнес-логику scorer/delivery НЕ трогаем — только читаем `alerts`.

## Context

task-016 добавил read-роут `GET /alerts` (read-only, tenant-scoped, `Depends(current_user)`) с offset/limit (`DEFAULT=20`/`MAX=100` clamp) и history-window из `PLAN_LIMITS[Resource.HISTORY]` (Free пусто+`history_unavailable`, Pro 30д/Team 90д). Долг task-016 прямо назван: «cursor-пагинация для deep-offset». offset/limit на растущей `alerts`: (а) `OFFSET N` сканирует и отбрасывает N строк (медленно при глубине); (б) вставка нового алерта между запросами страниц сдвигает окно → дубли/пропуски на границе.

Модель `backend/src/storage/models/alerts.py`: `Alert{id, user_id, cluster_id, score, channels_count, first_seen, delivery_status}`, есть `UniqueConstraint("user_id","cluster_id","uq_alerts_user_cluster")` и `Index("ix_alerts_user_id","user_id")`. Сортировка ленты — по `first_seen DESC`; для стабильного keyset нужен tiebreaker `id` (first_seen не уникален) и составной индекс `(user_id, first_seen)`.

Фронт: `frontend/src/features/alerts/{queries.ts,api.ts}`, `frontend/src/entities/alert/{model.ts,ui/alert-card.tsx}` (task-016, learnings: `useAlerts` infinite). Миграции — `backend/migrations/versions/` (chain ...`0005_billing`; следующий — `0006`), прогон через `migration_runner`/`make migrate`.

Конвенции: tenant-scoped, full type hints, Pydantic на границе, no magic literals (page size — named const/settings), SQLAlchemy bind-params, opaque-cursor не должен светить внутренние поля как доверяемый ввод.

## Goal

После задачи: `GET /alerts` принимает `cursor` (opaque) и `limit`, отдаёт страницу алертов пользователя по keyset `(first_seen DESC, id DESC)` + `next_cursor` (null на последней странице); пагинация стабильна — нет дублей/пропусков при вставке нового алерта между запросами; составной индекс `ix_alerts_user_first_seen(user_id, first_seen)` создан (модель + миграция `0006`); фронт `useAlerts` — infinite-query, листает по `next_cursor`; tenant-scope и history-window из task-016 сохранены. backend integration + frontend e2e зелёные.

## Discussion
<!-- durable record of clarifications; обратимы. -->
- Q: Чем сортируем и как tiebreak? → A: лента — новейшие сверху → Decision: keyset по `(first_seen DESC, id DESC)`; `id` — tiebreaker (first_seen не уникален), исключает дубли/пропуски на равных `first_seen`.
- Q: Формат cursor? → A: клиент не должен конструировать произвольный фильтр → Decision: **opaque** cursor — base64url от `(first_seen_iso, id)`; сервер декодирует и валидирует (battle-tested keyset: `WHERE (first_seen, id) < (:fs, :id)` через bind-params). Невалидный/битый cursor → `422`/первая страница (решение исполнителя, без `500`).
- Q: Контракт ответа? → A: паттерн API Response Format → Decision: `AlertListResponse{items: list[AlertRead], next_cursor: str | None}`; `next_cursor=None` ⇒ конец. Сохранить `history_unavailable` из task-016.
- Q: Индекс? → A: keyset по `(user_id, first_seen)` горяч → Decision: `Index("ix_alerts_user_first_seen","user_id","first_seen")` в модели + Alembic `0006`. Старый `ix_alerts_user_id` — оставить или заменить (исполнитель; составной покрывает префикс `user_id`).
- Q: limit-cap? → A: защита от DoS → Decision: `DEFAULT`/`MAX` clamp как в task-016 (named const/settings), не magic literal.
- Q: Совместимость со старым offset? → A: фронт — единственный потребитель, меняем оба разом → Decision: чистая замена offset→cursor (offset-параметры убрать); регенерить `gen.types.ts`.

## Scope
> Backend `api/alerts` (контракт пагинации + индекс + миграция) и `entities`/`features/alerts` на фронте. Scorer/delivery (task-008/009) и таблица-генератор НЕ трогаем — только читаем.

- **Touch ONLY (создать/изменить):**
  - `backend/src/api/alerts/service.py` — keyset-запрос `(first_seen, id) < cursor` (bind-params), формирование `next_cursor`; сохранить tenant-фильтр `Alert.user_id` + history-window (`PLAN_LIMITS`).
  - `backend/src/api/alerts/schemas.py` — `AlertListResponse` с `next_cursor: str | None` (+ `history_unavailable`); удалить offset-поля.
  - `backend/src/api/alerts/router.py` — параметры `cursor: str | None`, `limit` (clamp); убрать `offset`.
  - `backend/src/storage/models/alerts.py` — `Index("ix_alerts_user_first_seen","user_id","first_seen")` в `__table_args__`.
  - `backend/migrations/versions/0006_alerts_user_first_seen_index.py` — **новая** миграция (create index; down — drop).
  - `backend/tests/integration/test_alerts_api.py` — расширить: cursor-листание, отсутствие дублей/пропусков при вставке между страницами, `next_cursor=None` на конце, limit-clamp, tenant-scope, история по плану сохранена.
  - `frontend/src/features/alerts/{queries.ts,api.ts}` — `useAlerts` infinite по `next_cursor`.
  - `frontend/src/shared/api/gen.types.ts` — регенерировать (новый контракт; источник — дамп из task-019, иначе живой стек).
  - `frontend/tests/e2e/alerts.spec.ts` — листание/«показать ещё» по cursor (populated-лента).
  - `frontend/tests/unit/alerts/**` — infinite-хук cursor.
  - `docs/tasks/tasks-index.md` — на ship (оркестратор).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `backend/src/{scorer,alerts,pipeline,collector}/**` (только читаем `alerts`), `billing/**` (seam чтения `PLAN_LIMITS`), `landing/**`. Не менять состав полей `AlertRead`/детальный роут `GET /alerts/{id}` (task-016).
- **Blast radius:** меняется контракт `GET /alerts` (offset→cursor) → регенерация типов, правка фронт-хука и e2e. Новый индекс + миграция `0006` (изменение схемы — chain после `0005`). Поведение детального роута и tenant-scope/history не меняются.

## Acceptance Criteria
- [ ] **AC1 — cursor-листание без дублей/пропусков (failing-test anchor).** Given пользователь с N>limit алертами, When листаем по `next_cursor` до конца И между страницами вставляется новый алерт, Then каждый алерт встречается ровно один раз (нет дублей/пропусков на границе); `next_cursor=None` на последней. integration пишется ПЕРВЫМ (RED — пока offset).
- [ ] **AC2 — составной индекс создан.** Given миграция `0006`, When `make migrate`/`alembic upgrade head`, Then `ix_alerts_user_first_seen(user_id, first_seen)` существует; down-миграция его дропает; chain `0005→0006` корректен.
- [ ] **AC3 — контракт + clamp + opaque.** Given `GET /alerts?cursor=&limit=`, When запрос, Then ответ `{items, next_cursor}`; `limit` клампится к `MAX` (named const); битый/чужеродный cursor → не `500` (422/первая страница); cursor opaque (не доверяемый фильтр по сырым полям).
- [ ] **AC4 — tenant-scope + history сохранены.** Given Free/Pro/Team и чужие алерты, When листание, Then видны только свои (`Alert.user_id`); Free → пусто+`history_unavailable`; Pro/Team — окно 30/90 дней из `PLAN_LIMITS` (как task-016).
- [ ] **AC5 — фронт infinite по cursor.** Given `useAlerts`, When скролл/«показать ещё», Then подгружает следующую страницу по `next_cursor`, останавливается на `None`; типы из регенерённого `gen.types.ts`; `tsc`/`build` зелёные.
- [ ] **AC6 — тесты + G2 через nginx.** Given `make up` (+сид >limit алертов), When Playwright `alerts.spec.ts` листает за nginx и backend integration прогнан, Then AC1/AC5 наблюдаемы; integration зелёный; артефакты on-failure.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-020-alerts-cursor-pagination`.
1. **RED:** в `test_alerts_api.py` — листание по cursor + сценарий «вставка между страницами не даёт дублей/пропусков», `next_cursor=None` на конце. Падает (offset). AC1-якорь.
2. Модель: `Index("ix_alerts_user_first_seen",...)`; миграция `0006` (create/drop index); `make migrate` (AC2).
3. `service.py` — keyset `(first_seen, id) < cursor` (bind-params, `ORDER BY first_seen DESC, id DESC LIMIT :n+1` для определения next), opaque encode/decode; сохранить tenant + history-window. `schemas.py`/`router.py` — `next_cursor`, убрать offset.
4. `make ci-fast` + integration зелёные (AC1/AC3/AC4 GREEN).
5. Регенерировать `gen.types.ts`; `features/alerts` `useAlerts` infinite по cursor; unit-хук; `tsc`/`build` зелёные (AC5).
6. **G2:** `make up` (+сид >limit) → Playwright листает за nginx (AC1/AC5/AC6); integration зелёный.
7. Обновить `tasks-index.md` на ship.

## Invariants
- **Keyset стабилен** — сортировка `(first_seen DESC, id DESC)`, фильтр `(first_seen, id) < cursor`; tiebreaker `id` обязателен (first_seen не уникален).
- **Cursor opaque + bind-params** — сервер декодирует и подставляет через bind-параметры; клиент не строит произвольный SQL-фильтр; битый cursor не роняет (`не 500`).
- **Tenant-scope + history неизменны** — фильтр по `Alert.user_id`, окно из `PLAN_LIMITS` (task-016 контракт сохранён).
- **No magic literals** — `DEFAULT`/`MAX` page size — named const/settings; `le=`/clamp согласован с тестом (как task-016: clamp в service).
- **Read-only** — никаких мутаций `alerts`; scorer/delivery не трогаем.
- **Индекс покрывает горячий путь** — `(user_id, first_seen)` соответствует keyset-предикату и сортировке.

## Edge cases
- Равные `first_seen` у нескольких алертов → tiebreaker `id` исключает пропуск/дубль на границе страницы.
- Вставка алерта с `first_seen` новее текущей страницы между запросами → keyset не сдвигает уже отданное окно (в отличие от offset).
- Пустая лента / лента короче `limit` → `next_cursor=None`, без лишнего запроса.
- Невалидный/обрезанный/чужеродный cursor → `422` или первая страница, не `500`, не утечка.
- Free-план → пусто+`history_unavailable` даже при наличии cursor (history-window применяется до keyset).
- Граница окна истории (Pro 30д/Team 90д) при листании вглубь → последняя страница обрезается окном, `next_cursor=None`.
- Часовые пояса `first_seen` (timezone-aware) при encode/decode cursor → консистентный ISO/UTC, round-trip без сдвига.

## Test plan
- **integration (backend):** `test_alerts_api.py` — cursor-листание до конца (AC1), вставка между страницами без дублей/пропусков (AC1), `next_cursor=None` на конце, limit-clamp, битый cursor не `500` (AC3), tenant-scope + Free/Pro/Team окно (AC4).
- **migration (backend):** `make migrate`/upgrade head — `ix_alerts_user_first_seen` создан, down дропает, chain `0005→0006` (AC2); прогон `test_migrations.py`.
- **unit (frontend):** `tests/unit/alerts/**` — infinite-хук листает по `next_cursor`, стоп на `None`.
- **e2e (Playwright):** `alerts.spec.ts` — листание/«показать ещё» на populated-ленте за nginx (AC5).
- **runtime/behavioral (G2):** `make up` (+сид >limit) → Playwright за nginx; integration зелёный (AC6).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-020-alerts-cursor-pagination"
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
(initial — план по эталону task-016 и проверенным путям: task-016 оставил долг «cursor-пагинация для deep-offset»; модель `alerts.py` имеет `ix_alerts_user_id` + `uq_alerts_user_cluster`, сортировка ленты по `first_seen` → keyset `(first_seen DESC, id DESC)` + составной `ix_alerts_user_first_seen`; миграции chain `...0005_billing` → новая `0006`; фронт `features/alerts/{queries,api}` + `entities/alert` (task-016 infinite-хук) переводим на cursor; `gen.types.ts` регенерим из дампа task-019. Сохраняем tenant-scope + history-window из task-016. deps: 016. locate+plan выполнены — executor стартует с «3 do».)
