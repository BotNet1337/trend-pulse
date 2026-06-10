---
id: TASK-043
title: Адаптивный порог по доле 👎 + анти-fatigue (лимит алертов/час)
status: done                # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e2-adaptive-threshold-anti-fatigue"
tags: [epic-e2, backend, scorer, alerts]
---

# TASK-043 — Адаптивный порог + анти-fatigue (Epic E2)

> Часто 👎 → порог юзера медленно растёт (с floor/ceiling); поток алертов ограничен N/час на
> юзера. Замыкает петлю E2: 041 дал честный сигнал, 042 дал данные о реакции, 043 подстраивает
> систему под юзера. Депенденси: TASK-042 (alert_feedback).

## Context

Порог: `watchlists.threshold` (float, default 0.0), читается в
`scorer/tasks.py::_topic_configs` (минимальный по watchlist'ам юзера на topic); сравнение
`viral_score <= config.threshold → skip`. Фидбек: `alert_feedback` (TASK-042). Триггер-путь
алертов: `_create_alert_idempotent` + dispatch (`alerts/tasks.py`), beat-резweep уважает
deliver_after (TASK-040). Beat schedule: `backend/src/scheduler.py` (6 задач).

## Goal

(1) Beat-задача `adapt-thresholds` (интервал-константа, default 6h): для юзеров с ≥K оценок
за окно 7d считает downvote_share; > X% → `threshold += step` (не выше ceiling), < Y% →
`threshold -= step` (не ниже floor = исходного значения юзера). (2) Rate-guard в триггер-пути:
не больше `alerts_per_hour_limit` (default 6) создаваемых алертов на юзера в час; излишек
не создаётся (skip + log_event("alert_rate_limited")), похожие кластеры в окне группируются
(skip если алерт по близкому кластеру уже создан в окне — по cluster topic). DoD = AC.

## Discussion
- Q: Адаптировать per-watchlist или per-user? → Decision: **per-watchlist** (топики разные),
  но downvote_share считается per-user (объём данных мал) — применяется ко всем watchlist'ам
  юзера. Зафиксировать как MVP-упрощение; per-topic split — когда будет объём оценок.
- Q: Что считать floor? → Decision: floor = значение threshold, выставленное юзером руками
  (текущее значение на момент первого адаптивного шага — снапшотится в новое поле
  `threshold_floor`); адаптация никогда не опускает ниже и не поднимает выше ceiling
  (floor + adaptive_range, константа). Юзер меняет threshold руками → floor переснапшотится.
- Q: Лимит N/час — на создание или на доставку? → Decision: **на создание** (в scorer) —
  дешевле всего, и resweep/dispatch не трогаем (они уже сложные после TASK-040).
- Q: «Группировка похожих» — насколько умная? → Decision: MVP — не более 1 алерта на
  (user, topic) в `alert_group_window_seconds` (default 1800); НЕ векторная близость
  (кластеры уже дедуплицируют семантику).

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/0014_watchlist_threshold_floor.py` — **новая**: nullable
    `watchlists.threshold_floor` float.
  - `backend/src/storage/models/watchlists.py` — поле.
  - `backend/src/scorer/adaptation.py` — **новый**: расчёт downvote_share + шаг адаптации
    (чистая функция) + task.
  - `backend/src/scheduler.py` — beat-запись `adapt-thresholds`.
  - `backend/src/scorer/tasks.py` — rate-guard + group-guard перед `_create_alert_idempotent`.
  - `backend/src/api/watchlist/` — PATCH threshold руками → переснапшот floor (минимальная
    правка в существующем update-пути).
  - `backend/src/config.py` — `threshold_adapt_interval_seconds` (21600),
    `threshold_adapt_step` (5.0), `threshold_adapt_range` (20.0),
    `threshold_adapt_min_ratings` (5), `threshold_adapt_up_share` (0.5),
    `threshold_adapt_down_share` (0.2), `alerts_per_hour_limit` (6),
    `alert_group_window_seconds` (1800).
  - tests: `backend/tests/unit/scorer/test_threshold_adaptation.py`,
    `backend/tests/unit/scorer/test_alert_rate_guard.py` (**новые**).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** dispatch/resweep (TASK-040-механика), формула score (TASK-041),
  alert_feedback-схема (TASK-042), ALERTS_PER_DAY plan-лимиты (billing).
- **Blast radius:** триггер-путь scorer (guards ДО создания — идемпотентность не задета);
  UX: порог юзера меняется «сам» — обязательно log_event("threshold_adapted", old, new,
  user_id) для объяснимости и E6-дашборда.

## Acceptance Criteria
- [x] **AC1 — порог растёт при 👎 (failing-test anchor).** Given юзер с ≥K оценок и
  downvote_share > X%, When adapt-tick, Then каждый его watchlist.threshold += step, но
  ≤ floor+range. RED первым.
- [x] **AC2 — порог отпускает.** downvote_share < Y% → threshold -= step, но ≥ floor.
- [x] **AC3 — мало данных = no-op.** < K оценок за окно → порог не трогается.
- [x] **AC4 — rate-guard.** Given за час уже создано N алертов юзера, Then новый кластер выше
  порога НЕ создаёт алерт (skip + log_event), создаст на следующем тике, если поток спал.
- [x] **AC5 — group-guard.** Два кластера одного topic в group-окне → один алерт.
- [x] **AC6 — ручной PATCH переснапшотит floor.** Юзер ставит threshold=90 → floor=90,
  адаптация пляшет от него.
- [x] **AC7 — G2.** Живой стек: посев 👎-оценок → adapt-tick реально двигает threshold в БД;
  поток из 10 кластеров за час → ≤N алертов; `make ci-fast` зелёный.

## Plan
1. **RED:** test_threshold_adaptation (AC1–AC3, AC6 чистые функции) + test_alert_rate_guard
   (AC4/AC5 c фейк-временем).
2. Миграция 0014 + модель + config.
3. adaptation.py (чистая логика + beat task) + scheduler.
4. Guards в scorer/tasks.py + PATCH-floor.
5. GREEN + G2; tasks-index на ship.

## Invariants
- Адаптация никогда не выходит из [floor, floor+range]; шаг медленный (step << range).
- Guards стоят ДО `_create_alert_idempotent` — идемпотентность и TASK-040 deliver_after
  не затронуты.
- Все константы — из Settings (no magic literals).
- Объяснимость: каждый сдвиг порога — log_event с old/new.

## Edge cases
- Юзер без watchlist'ов, но с оценками → no-op.
- threshold_floor NULL (до первого шага) → floor = текущий threshold на момент тика.
- Гонка adapt-tick и PATCH юзера → last-write-wins, floor переснапшотится PATCH'ем.
- Часовой rate-окно через границу часа → скользящее окно по created_at, не календарный час.

## Test plan
- **unit:** адаптация (граничные share, floor/ceiling, min_ratings), rate/group-guard
  (freeze-time), floor-снапшот при PATCH.
- **integration:** adapt-tick на db_session с посевом alert_feedback; поток кластеров →
  guard в действии.
- **G2:** AC7 на живом стеке.
- **security (5.5):** n/a по input (внутренние механики); review подтверждает, что guards
  не дают обойти план-лимиты в обратную сторону.

## Checkpoints
current_step: done
baseline_commit: "6157871c72dd497608d52902b43668eef8192876"
branch: "gsd/phase-e2-adaptive-threshold-anti-fatigue"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior)
- [x] 5 review (auto, adversarial — pass, без блокеров)
- [x] 5.5 security (n/a подтверждён review: нет нового input-surface, bind-param SQL, guards только подавляют)
- [x] 6 ship (PR, squash-merge, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-10 TASK-043)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E2, замыкает 041→042→043. Deps: TASK-042 (alert_feedback).
Главная UX-ловушка: «порог сам уехал» — без log_event и floor-инварианта юзер потеряет
доверие. Rate-guard сознательно в create-пути, не в dispatch — dispatch после TASK-040 и
так перегружен ответственностью.)

### locate (2026-06-10, loop run)
- Beat: scheduler.py:17-59 — 6 записей, schedule float из settings; задачи по паттерну
  @celery_app.task(name=CONST) в домен-модуле + lazy import (pipeline/tasks.py,
  observability/tasks.py — best-effort try/except).
- Триггер-путь: scorer/tasks.py::_score_user ~372-375 — `viral_score <= threshold → skip`,
  затем `_create_alert_idempotent(...)`. Guards вставлять МЕЖДУ. В скоупе: session, user_id,
  cluster (id, topic, first_seen), score, config.
- Время алерта для rate-окна: alerts.first_seen (created_at у Alert НЕТ). Group-guard: topic
  через join alerts→clusters (Alert хранит только cluster_id).
- watchlists.threshold: Float default 0.0; threshold_floor — nullable Float; миграция 0014
  (op.add_column). PATCH-путь: api/watchlist/service.py::update ~106-135, threshold ставится
  на :124 через alert_config.score_threshold → переснапшот floor сразу после.
- alert_feedback: verdict SmallInteger (1=up/0=down), created_at/updated_at; SQL-стиль —
  по emit_alert_precision (f-string только для констант-алиасов, bind params для значений).
- Тесты: backend/tests/unit/test_*.py (подкаталога scorer/ нет — удалён в 041).
- log_event: alert_rate_limited/alert_group_limited/threshold_adapted с old/new/share.

### do (2026-06-10, loop run)
- TDD RED→GREEN; ci-fast 495 unit, integration 137 passed/10 skipped; mypy/ruff clean.
- Девиации (обоснованные): scorer/constants.py (cycle-breaker по паттерну alerts.constants)
  + celery_app.py (include новой задачи).
- Guards строго до _create_alert_idempotent: rate (func.count по first_seen за 1h-окно),
  group (JOIN clusters по topic за alert_group_window_seconds); в логах только int-id
  (topic-строка может содержать сырой текст — learnings TASK-039).
- compute_threshold_step клампит [floor, floor+range], None при no-op (без пустых записей).
- AC6: floor NULL → снапшот при первом тике; PATCH переснапшотит floor.
- Миграция 0014 применена; OpenAPI не менялся.

### verify G2 (2026-06-10, loop run)
- ci-fast 495 unit + integration 137/10 skipped + drift-check clean; миграция 0014 идемпотентна.
- AC7 на реальной dev-БД: adapt-tick 50→55→60→65→70 (ceiling держит, на потолке
  watchlists_changed=0); вниз 70→50 (floor держит); rate-guard: 6 алертов/час → skip+log,
  после старения first_seen>1h — алерт создаётся; group-guard: same (user,topic) в 1800s →
  skip+log (без topic-строки в полях); beat 'adapt-thresholds' = 21600s.
- Ожидаемое в dev: enqueue доставки падает без Redis (best-effort warning, строка алерта
  авторитетна) — поведение TASK-040.

### review (2026-06-10, loop run)
- Вердикт: pass, блокеров нет; security n/a подтверждён. Применено: комментарий-инвариант
  (rate-guard окно ↔ scorer_recent_window_seconds — alerts.first_seen = cluster.first_seen,
  при окне scorer > 1h алерты старых кластеров обошли бы cap); fail-fast валидаторы
  настроек адаптации (step/range > 0; 0 <= down_share < up_share <= 1); типизация фикстуры.
- MEDIUM про untracked prod.yml: файл не стейджится (явные git add), в коммит не попадает.
