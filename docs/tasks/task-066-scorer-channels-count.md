---
id: TASK-066
title: Scorer персистирует channels_count per cluster — реальный счётчик в trending и proof-of-speed кейсах
status: planned        # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [scorer, trending, showcase, storage, migration, proof-of-speed]
---

# TASK-066 — Scorer персистирует channels_count per cluster

> Закрыть 3 TODO одного корня: trending и proof-of-speed кейсы показывают
> захардкоженный `channels_count=1` вместо реального числа каналов кластера —
> месседж «N каналов за M минут» сейчас врёт в меньшую сторону.

## Context

Scorer УЖЕ считает реальное число каналов кластера:
`unique_channels = {p.channel_id for p in posts}` →
`unique_channels_count=len(unique_channels)` (`backend/src/scorer/tasks.py:203,239`,
датакласс `ScoreInputs` — `backend/src/scorer/score.py:60`). И УЖЕ персистирует его
в алертах: `Alert.channels_count` (`backend/src/storage/models/alerts.py:35`),
`_create_alert_idempotent(..., channels_count=inputs.unique_channels_count)`
(`backend/src/scorer/tasks.py:462`) — алерт-сообщение честно показывает
«N каналов» (`backend/src/alerts/formatting.py:60`).

Но в строку `scores` счётчик НЕ пишется (`Score`: только velocity/engagement/
cross_channel/viral_score — `backend/src/storage/models/scores.py:19-26`;
upsert `_persist_score` — `backend/src/scorer/tasks.py:244-279`). Поэтому три
потребителя фейкуют единицу (3 TODO одного корня):

- `backend/src/api/trending/service.py:103` (select без счётчика) +
  `:119` TODO + `:124` `channels_count=1`;
- `backend/src/showcase/cases.py:42-43` TODO + `_CHANNELS_COUNT_MVP = 1`
  (используется в snapshot `:120` и insert `:200`);
- `backend/src/storage/models/showcase_cases.py:80-81` — комментарий
  «MVP = 1; TODO: persist real count in scorer» + `default=1`.

Оба потребителя уже джойнят `Score`: trending — `service.py:100`, фиксация кейсов —
`cases.py:180`. Витрина: `TrendingItem.channels_count`
(`backend/src/api/trending/schemas.py:41`), `CaseItem.channels_count`
(`backend/src/api/cases/schemas.py:41`, docstring «MVP = 1» — `:26`).
Это оживляет proof-of-speed месседж «N каналов за M минут» (TASK-045, лендинг/кейсы).

## Goal

`scores.channels_count` хранит реальное число уникальных каналов кластера на момент
скоринга; `GET /trending/{pack}` и фиксируемые `showcase_cases` несут этот реальный
счётчик; все 3 TODO удалены. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Куда персистить — колонка в `clusters` или в `scores`? → A: в `scores` →
  Decision: **`scores.channels_count`**. Rationale: счётчик вычисляется в момент
  скоринга из постов (`_build_score_inputs`), его владелец — scorer, который уже
  делает upsert строки Score (`uq_scores_user_cluster`, on_conflict_do_update —
  обновление при каждом тике бесплатно); оба потребителя уже джойнят Score;
  `Cluster` остаётся чистой пайплайн-сущностью (pipeline steps pure/immutable,
  CONVENTIONS) — пайплайн не трогаем вообще.
- Q: Менять ли формулу/компоненты скоринга? → A: нет → Decision: `cross_channel`
  (доля ∈ [0,1]) и `compute_components` не трогаем — добавляется только
  ПЕРСИСТЕНЦИЯ уже вычисленного `inputs.unique_channels_count` в `_persist_score`
  (у него `inputs` уже в сигнатуре — `tasks.py:245`). Поведение алертов не меняется.
- Q: Что с существующими строками `scores` (до миграции)? → A: server_default →
  Decision: `NOT NULL DEFAULT 1` (`server_default="1"`) — честное текущее
  MVP-значение, аддитивная backward-совместимая миграция (паттерн
  `alerts.delivery_status`, migration 0004). Следующий номер цепочки — **0020**
  (последняя — `backend/migrations/versions/0019_field_encryption.py`,
  `revision="0019"`; перепроверить на do — параллельные циклы могли занять номер).
- Q: `build_case_snapshot(cluster)` — как передать реальный счётчик? → A: расширить
  сигнатуру → Decision: `build_case_snapshot(cluster, *, channels_count: int)` —
  явный параметр (хелпер pure, тестируется без БД — `tests/unit/showcase/test_cases.py:191-238`);
  `_CHANNELS_COUNT_MVP` удалить. `fix_cases` добавляет `Score.channels_count`
  в select (`cases.py:173-184`) и кладёт `row.channels_count` в insert (`:200`).
- Q: Докстринги схем («MVP = 1») попадут в OpenAPI → дрейф фронт-типов? → A: да →
  Decision: обновить докстринги `api/cases/schemas.py:26` /
  `api/trending/schemas.py:30` и перегенерировать `make gen-openapi gen-types`
  (`frontend/src/shared/api/gen.types.ts` — drift-check зашит в `make ci`,
  `Makefile:220`). Поля/типы контракта НЕ меняются — только комментарии.

## Scope

- **Touch ONLY:**
  - `backend/migrations/versions/0020_scores_channels_count.py` — новая (ADD COLUMN
    `channels_count INTEGER NOT NULL`, `server_default="1"`; down — drop).
  - `backend/src/storage/models/scores.py` — `channels_count: Mapped[int]`
    (Integer, nullable=False, server_default="1", default=1) после `cross_channel`.
  - `backend/src/scorer/tasks.py::_persist_score` (`:244-279`) —
    `channels_count=inputs.unique_channels_count` в `.values(...)` и в `set_`.
  - `backend/src/api/trending/service.py` — `Score.channels_count` в select
    (`:94-106`), `channels_count=row.channels_count` (`:124`), снять TODO-блок
    (`:114-119`).
  - `backend/src/showcase/cases.py` — убрать `_CHANNELS_COUNT_MVP` (`:39-43`);
    `build_case_snapshot(..., *, channels_count)` (`:99-121`); select + insert в
    `fix_cases` (`:173-206`).
  - `backend/src/storage/models/showcase_cases.py:80-81` — комментарий (default=1
    остаётся как safe-fallback колонки).
  - `backend/src/api/cases/schemas.py:26`, `backend/src/api/trending/schemas.py:30`
    — докстринги; затем `make gen-openapi gen-types` →
    `backend/openapi.json`-дамп + `frontend/src/shared/api/gen.types.ts` (регенерат).
  - Тесты: `backend/tests/integration/test_scorer_alerts.py`,
    `backend/tests/integration/test_trending_api.py`,
    `backend/tests/unit/showcase/test_cases.py`, при необходимости
    `backend/tests/integration/test_showcase_autopost.py`.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** формулу скоринга (`scorer/score.py` — `compute_components`,
  `_cross_channel`), путь алертов (`Alert.channels_count` уже реальный —
  `tasks.py:462`), pipeline (`dedup/normalize/embed/cluster`), модель `Cluster`,
  retention/compliance-механику, фронт-код (типы — только регенерат),
  `_bmad/**`, `.claude/**`.
- **Blast radius:** схема БД `scores` (аддитивная колонка + default — без ломки
  читателей); upsert скорера (каждый тик пишет одно лишнее int-поле); ответы
  `GET /v1/trending/{pack}` и `GET /v1/cases` (значение поля меняется с 1 на
  реальное — тип/контракт тот же); новые строки `showcase_cases` (снапшоты
  исторических кейсов НЕ переписываются — snapshot-семантика TASK-045).

## Acceptance Criteria

- [ ] **AC1 — персистенция.** Given кластер с постами из 3 разных каналов When
  scorer-тик (`_score_user` → `_persist_score`) Then строка `scores` несёт
  `channels_count == 3`; повторный тик с 4-м каналом → upsert обновляет до 4
  (integration, паттерн `test_persist_score_upsert_no_growth` —
  `test_scorer_alerts.py:295`).
- [ ] **AC2 — trending.** Given showcase-кластер с `channels_count=3` в scores When
  `GET /v1/trending/{pack}` Then `items[].channels_count == 3` (не 1).
- [ ] **AC3 — кейсы.** Given showcase-кластер с viral_score ≥ min_score и
  `channels_count=5` When `fix_cases` Then строка `showcase_cases.channels_count == 5`;
  `GET /v1/cases` отдаёт 5 (существующая выдача `api/cases/service.py:60` — без правок).
- [ ] **AC4 — миграция безопасна.** Given БД с существующими строками `scores` When
  `alembic upgrade head` Then старые строки читаются с `channels_count == 1`
  (то же значение, что фейкали потребители, — без регресса витрин).
- [ ] **AC5 — нет дрейфа.** `make ci` зелёный, включая `openapi-drift-check`
  (типы перегенерированы в том же PR); `grep -rn "_CHANNELS_COUNT_MVP"` = 0;
  3 TODO удалены.

## Plan

1. RED: integration-тест AC1 (scores несёт реальный счётчик + upsert-обновление);
   unit-тесты `test_cases.py` на новую сигнатуру `build_case_snapshot` — падают.
2. `migrations/versions/0020_scores_channels_count.py` + модель
   `storage/models/scores.py` → миграция на тестовой БД.
3. `scorer/tasks.py::_persist_score` — values/set_ → GREEN AC1.
4. `api/trending/service.py` — select + item → GREEN AC2
   (`test_trending_api.py`: дополнить сид постами в ≥2 каналах).
5. `showcase/cases.py` — сигнатура snapshot + select/insert → GREEN AC3.
6. Докстринги схем + `make gen-openapi gen-types` (регенерат в тот же коммит).
7. Verify (G2): `make ci` + живой прогон trending/cases на стенде.

## Invariants

- Формула viral_score и компоненты НЕ меняются — ни один существующий
  score-результат/порог/алерт не сдвигается (это правка персистенции, не скоринга).
- Compliance §7: `channels_count` — агрегатное ЧИСЛО; никаких channel_id/хэндлов
  в trending/cases ответах (как и раньше).
- `showcase_cases` остаётся самодостаточным снапшотом без FK на
  clusters/posts/scores (переживает 48h-purge — инвариант TASK-045);
  исторические кейс-строки не переписываются.
- Миграция аддитивна: откат (down) не теряет чужих данных; старые читатели
  таблицы `scores` не ломаются.
- `Alert.channels_count`-путь не затронут (он уже реальный).

## Edge cases

- Кластер без постов (`posts == []`) → `inputs.unique_channels_count = 0`
  (`tasks.py:196`) → в scores попадёт 0. На практике кластер создаётся пайплайном
  только из постов, а trending-окно (24h) короче retention (48h) — 0 возможен лишь
  для деградировавших данных; алерты при этом не создаются (score 0 ≤ threshold).
  Handling: персистим честный 0, витрины его не увидят (не попадает в top-K с
  нулевым скором при живых конкурентах); НЕ клампим — данные не врут.
- Строки scores до миграции → server_default 1 == текущему поведению витрин
  (no regress, AC4).
- Посты кластера удалены retention-purge после скоринга → scores хранит последний
  вычисленный счётчик (snapshot-семантика, как viral_score) — осознанно.
- Параллельная задача займёт номер 0020 → на do взять следующий свободный
  (`down_revision` от фактического head цепочки).
- Дедуп-кейс `uq_showcase_cases_title_first_seen`: тот же кластер на следующем тике
  с выросшим счётчиком → insert игнорируется (on_conflict_do_nothing,
  `cases.py:204`) — кейс фиксирует момент ПЕРВОГО пересечения порога; осознанно,
  зафиксировать в Details.

## Test plan

- unit: `tests/unit/showcase/test_cases.py` — `build_case_snapshot` с явным
  `channels_count` (включая граничные 0/1/большое); `tests/unit/test_score.py` —
  без изменений (формула не тронута, прогон как регресс-гард).
- integration: `test_scorer_alerts.py` — AC1 (персист + upsert-update);
  `test_trending_api.py` — AC2 (сид мульти-канального кластера);
  `test_cases_api.py`/`test_showcase_autopost.py` — AC3 + существующие сиды с
  `channels_count=1` остаются валидны; `test_migrations.py` — цепочка с 0020.
- e2e: не требуется (контракт/типы не меняются — только значение поля).
- security: не требуется (нет auth/input/secrets поверхностей) — подтвердить skip
  на review.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "c390c4c"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11: корень всех трёх TODO один — scorer вычисляет
`unique_channels_count`, но персистирует его только в alerts; решение — колонка в
`scores` (владелец значения — scorer, потребители уже джойнят Score), миграция 0020
с default=1 для старых строк. deps: TASK-022 (per-cluster посты, FK миграции 0007),
TASK-045 (showcase_cases + fix_cases).)
