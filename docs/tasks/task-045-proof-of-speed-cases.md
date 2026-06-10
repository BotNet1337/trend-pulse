---
id: TASK-045
title: Proof-of-speed — штамп обнаружения в постах + база авто-кейсов showcase_cases
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e3-proof-of-speed-cases"
tags: [epic-e3, backend, growth]
---

# TASK-045 — Proof-of-speed + авто-кейсы (Epic E3)

> Каждый showcase-пост уже несёт «обнаружено в 14:02» (TASK-044). Здесь — копилка
> доказательств: сигналы score > порога складываются в `showcase_cases` (тема, время
> обнаружения, каналы, score) — сырьё для лендинга/рекламы «мы раньше мейнстрима».
> Сравнение с мейнстримом в MVP полуручное: оператор проставляет `mainstream_at`.

## Context

TASK-044 даёт `showcase_posts` и beat-тик. Кейсы — отдельная сущность с другим жизненным
циклом: пост живёт минуты (канал), кейс — месяцы (маркетинг). Кластеры showcase-тенанта:
`trending/service.py`-паттерн выборки. Ретенция: киллер-вопрос — кластеры/посты чистятся
(48h retention), а кейс должен пережить их → кейс ДЕНОРМАЛИЗУЕТ всё нужное в момент
создания (no FK на cluster, snapshot полей).

## Goal

Beat-логика (расширение showcase-тика TASK-044 или отдельный тик): кластеры showcase-тенанта
со score ≥ `showcase_case_min_score` (default 90) фиксируются в `showcase_cases` —
snapshot: topic, title, viral_score, first_seen (= «обнаружено»), channels_count, created_at;
`mainstream_at` NULLABLE — проставляется оператором (пока вручную SQL/админ-скриптом,
admin-UI вне scope). Read-only `GET /cases` (public, top-N по разнице mainstream_at −
first_seen, только заполненные) — сырьё для лендинга. DoD = AC.

## Discussion
- Q: FK на cluster или snapshot? → Decision: **snapshot-денормализация** — кейс переживает
  ретенцию кластеров; ничего не ломается при purge. Поля копируются в момент фиксации.
- Q: mainstream_at — откуда? → Decision: вручную (MVP): оператор видит «выстреливший» кейс
  и проставляет время появления в мейнстрим-СМИ. Автоматизация (мониторинг RSS СМИ) —
  отдельная задача волны E7+, не сейчас.
- Q: Как оператор проставляет без админки? → Decision: `make case-mainstream ID=… AT=…`
  (обёртка над SQL через compose exec api) — дешёвый операторский путь, без UI и без
  расширения API-поверхности записью.
- Q: GET /cases публичный? → Decision: да (лендинг тянет без auth), read-only, лимит/кэш —
  только заполненные кейсы (mainstream_at NOT NULL), поля без чувствительного.

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/0016_showcase_cases.py` — **новая**: `showcase_cases`
    (id, topic, title, viral_score, first_seen, channels_count, mainstream_at NULL,
    created_at; UNIQUE по (topic, title, first_seen) от дублей).
  - `backend/src/storage/models/showcase_cases.py` — **новый**.
  - `backend/src/showcase/cases.py` — **новый**: фиксация кейсов (чистая selection-логика +
    запись), вызывается из showcase-тика (TASK-044) после/независимо от постинга.
  - `backend/src/api/cases/` — **новый** read-only роутер `GET /cases` (public, top-N,
    only mainstream_at NOT NULL, сортировка по lead-time DESC).
  - `backend/src/api/main.py` — include.
  - `backend/src/config.py` — `showcase_case_min_score` (90.0), `cases_top_n_max` (20).
  - `Makefile` — `case-mainstream` target (оператор).
  - tests: `backend/tests/unit/showcase/test_cases.py`,
    `backend/tests/integration/test_cases_api.py` (**новые**).
  - OpenAPI dump + types (контракт меняется).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** лендинг (потребление /cases — отдельная микро-задача фронта при E5),
  showcase_posts-механика, scorer/alerts.
- **Blast radius:** +1 запись на выстреливший кластер (низкая частота), новый публичный
  read-only endpoint (rate-limit по умолчанию).

## Acceptance Criteria
- [x] **AC1 — кейс фиксируется (failing-test anchor).** Given showcase-кластер score ≥ 90,
  When тик, Then строка showcase_cases со snapshot-полями; ниже порога — нет. RED первым.
- [x] **AC2 — дубли не плодятся.** Тот же кластер на следующем тике → кейс один (UNIQUE).
- [x] **AC3 — кейс переживает ретенцию.** После purge кластеров/постов кейс цел и полон.
- [x] **AC4 — GET /cases.** Возвращает только кейсы с mainstream_at, отсортированные по
  lead-time, ≤ top-N; без auth; 200 пустой список, если нет.
- [x] **AC5 — операторский путь.** `make case-mainstream ID=1 AT="2026-06-10T15:00:00Z"` →
  поле проставлено, кейс появился в GET /cases.
- [x] **AC6 — G2.** Живой стек: посев score>90 → кейс в БД → make case-mainstream →
  curl /cases отдаёт его; `make ci-fast` + openapi-drift зелёные.

## Plan
1. **RED:** unit cases-selection/snapshot (AC1–AC3) + integration /cases (AC4).
2. Миграция 0016 + модель + config.
3. cases.py + вызов из showcase-тика + роутер + main.py.
4. Makefile target; gen-openapi/types.
5. GREEN + G2; tasks-index на ship.

## Invariants
- Кейс — самодостаточный snapshot: никаких FK на retention-подверженные таблицы.
- GET /cases не отдаёт незаполненные кейсы (пустой lead-time = не доказательство).
- Фиксация кейса не блокирует и не валит постинг (исключение → log, тик продолжается).
- No raw post content в кейсе — только агрегаты кластера (compliance 48h).

## Edge cases
- mainstream_at < first_seen (оператор ошибся) → валидация в make-обёртке (отказ).
- Два кластера с одинаковым title/topic в разные дни → UNIQUE включает first_seen.
- Кластер растёт после фиксации (score выше) → кейс НЕ апдейтится (snapshot честен к
  моменту обнаружения); зафиксировано.

## Test plan
- **unit:** selection-порог, snapshot-полнота, идемпотентность.
- **integration:** /cases (фильтр/сортировка/лимит), фиксация на db_session, purge-survival.
- **G2:** AC6 на живом стеке.
- **security (5.5):** public endpoint — нет утечки внутренних id/полей сверх схемы.

## Checkpoints
current_step: done
baseline_commit: "b4716465f44619c230d402402e63bdb0282e13e8"
branch: "gsd/phase-e3-proof-of-speed-cases"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior; 1 HIGH найден и исправлен)
- [x] 5 review (adversarial — 1 HIGH (type:ignore×2) исправлен)
- [x] 5.5 security (pass — extra=forbid схема, 6 агрегатных полей, NULL-фильтр незаобходим, rate-limit)
- [x] 6 ship (PR, squash-merge, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-11 TASK-045)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E3. Deps: TASK-044 (showcase-тик; при необходимости 045 может
идти первым с собственным тиком — связность слабая). Ключевое решение — snapshot vs FK:
ретенция 48h убивает кластеры, кейсы должны жить месяцами.)

### locate (2026-06-11, loop run)
- Хук фиксации: showcase/tasks.py::_run_tick_body после send-блока (~260+), try/except
  без re-raise — фиксация не валит постинг.
- Cluster НЕ имеет title — только topic (свободный текст). КОМПЛАЕНС-РЕШЕНИЕ: в snapshot
  хранить ТОЛЬКО санированный лейбл (textutils.sanitize_topic_label) — кейс живёт месяцы,
  raw-текст с retention 48h в нём недопустим.
- channels_count в Score не персистится (trending хардкодит 1) — MVP: 1 + TODO-комментарий.
- Роутер-шаблон: api/trending (но /cases БЕЗ auth, как /feedback); top-N cap по образцу
  trending_top_k_max; rate-limit — глобальный middleware.
- Миграция 0016 по образцу 0015, БЕЗ FK (snapshot), UniqueConstraint(topic,title,first_seen).
- Makefile: case-mainstream по образцу showcase-init (compose exec api uv run ...).
- Тесты: unit по test_selection.py (Fake*), integration по test_trending_api.py +
  purge-survival (кейс переживает удаление кластера).
- OpenAPI меняется (новый GET /cases) → gen-openapi gen-types обязательны.

### do (2026-06-11, loop run)
- TDD RED (17 unit падали) → GREEN: ci-fast 554 unit; integration 154/10 skipped; mypy
  (вкл. scripts/case_mainstream.py) и ruff clean; миграция 0016 применена; OpenAPI перегенерён.
- **Девиация от Scope (обоснована):** колонка topic ОТБРОШЕНА — у Cluster нет отдельного
  watchlist-ключа (cluster.topic = raw post text). Один санированный title;
  UNIQUE(title, first_seen). Задокументировано в докстрингах миграции/модели.
- Фиксация кейсов вызвана из _run_tick_body после постинга, try/except (не валит постинг).
- AC3 purge-survival: scores удаляются раньше clusters (FK) — тест повторяет порядок purge.
- Операторский путь: make case-mainstream → scripts/case_mainstream.py (валидирует
  mainstream_at > first_seen).
- Замечание для review: api/cases/router.py использует собственный _get_db_session.

### verify G2 + fix (2026-06-11, loop run)
- Живой ASGI + реальная БД: /cases скрывает незаполненные (200 []); операторский скрипт
  работает + отказывает при AT < first_seen; lead_time/сортировка/422 over-max корректны;
  purge-survival подтверждён (кейс жив после удаления score+cluster).
- **HIGH (найден verify, исправлен):** ранний return на creds-guard делал fix_cases
  недостижимым без TG-кредов — фиксация перенесена ДО guard'а (unconditional, свой
  try/except). RED-тест test_fix_cases_runs_without_tg_creds падал до фикса.
- LOW: api/cases/router.py переведён на общий get_db_session (как другие роутеры).
- Гейты после фикса: ci-fast 554 unit; integration 155/10 skipped.

### review + security (2026-06-11, loop run)
- review: 1 HIGH — два `# type: ignore` в cases/service.py → убраны None-guard'ом (mypy
  честно зелёный); LOW: docstring unit-тестов поправлен, _TITLE_MAX_LEN теперь derived от
  TOPIC_LABEL_MAX_LEN (+20), кавычки в make case-mainstream.
- security: pass. Follow-up (LOW, не сейчас): расширить san-фильтр textutils на scheme-less
  домены/t.me/+инвайты/телефоны — кейсы живут месяцы.
- Гейты после правок: ci-fast 554 unit; cases+autopost integration 18 passed.
