---
id: TASK-045
title: Proof-of-speed — штамп обнаружения в постах + база авто-кейсов showcase_cases
status: planned             # planned → in-progress → review → done
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
- [ ] **AC1 — кейс фиксируется (failing-test anchor).** Given showcase-кластер score ≥ 90,
  When тик, Then строка showcase_cases со snapshot-полями; ниже порога — нет. RED первым.
- [ ] **AC2 — дубли не плодятся.** Тот же кластер на следующем тике → кейс один (UNIQUE).
- [ ] **AC3 — кейс переживает ретенцию.** После purge кластеров/постов кейс цел и полон.
- [ ] **AC4 — GET /cases.** Возвращает только кейсы с mainstream_at, отсортированные по
  lead-time, ≤ top-N; без auth; 200 пустой список, если нет.
- [ ] **AC5 — операторский путь.** `make case-mainstream ID=1 AT="2026-06-10T15:00:00Z"` →
  поле проставлено, кейс появился в GET /cases.
- [ ] **AC6 — G2.** Живой стек: посев score>90 → кейс в БД → make case-mainstream →
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
current_step: 1
baseline_commit: ""
branch: "gsd/phase-e3-proof-of-speed-cases"
lock: ""
- [ ] 1 locate (scope + patterns + blast radius)
- [ ] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (public read-only endpoint — лёгкий чеклист)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E3. Deps: TASK-044 (showcase-тик; при необходимости 045 может
идти первым с собственным тиком — связность слабая). Ключевое решение — snapshot vs FK:
ретенция 48h убивает кластеры, кейсы должны жить месяцами.)
