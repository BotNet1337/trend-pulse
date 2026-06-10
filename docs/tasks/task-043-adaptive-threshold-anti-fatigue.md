---
id: TASK-043
title: Адаптивный порог по доле 👎 + анти-fatigue (лимит алертов/час)
status: planned             # planned → in-progress → review → done
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
- [ ] **AC1 — порог растёт при 👎 (failing-test anchor).** Given юзер с ≥K оценок и
  downvote_share > X%, When adapt-tick, Then каждый его watchlist.threshold += step, но
  ≤ floor+range. RED первым.
- [ ] **AC2 — порог отпускает.** downvote_share < Y% → threshold -= step, но ≥ floor.
- [ ] **AC3 — мало данных = no-op.** < K оценок за окно → порог не трогается.
- [ ] **AC4 — rate-guard.** Given за час уже создано N алертов юзера, Then новый кластер выше
  порога НЕ создаёт алерт (skip + log_event), создаст на следующем тике, если поток спал.
- [ ] **AC5 — group-guard.** Два кластера одного topic в group-окне → один алерт.
- [ ] **AC6 — ручной PATCH переснапшотит floor.** Юзер ставит threshold=90 → floor=90,
  адаптация пляшет от него.
- [ ] **AC7 — G2.** Живой стек: посев 👎-оценок → adapt-tick реально двигает threshold в БД;
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
current_step: 1
baseline_commit: ""
branch: "gsd/phase-e2-adaptive-threshold-anti-fatigue"
lock: ""
- [ ] 1 locate (scope + patterns + blast radius)
- [ ] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (conditional — подтвердить n/a на review)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E2, замыкает 041→042→043. Deps: TASK-042 (alert_feedback).
Главная UX-ловушка: «порог сам уехал» — без log_event и floor-инварианта юзер потеряет
доверие. Rate-guard сознательно в create-пути, не в dispatch — dispatch после TASK-040 и
так перегружен ответственностью.)
