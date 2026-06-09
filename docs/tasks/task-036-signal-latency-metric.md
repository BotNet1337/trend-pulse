---
id: TASK-036
title: Метрика задержки сигнала p50/p95 «пост→алерт» + Redis memory watch
status: planned
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e0, backend, observability, pain-p3, pain-p7]
---

# TASK-036 — Signal latency p50/p95 (Epic E0)

> P3 из [pain-points](../architecture/pain-points.md): продаём скорость («раньше мейнстрима»), а цепочка
> коллектор→буфер→батч(60с)→скорер(300с) даёт до ~7 минут — и это никто не меряет. «Пока не измеряешь —
> не управляешь». Плюс дёшевая часть P7: мониторинг памяти Redis тем же тиком.

## Context

Тайм-чейн в моделях уже полный: `posts.posted_at` (источник) / `posts.fetched_at` (ингест) →
`clusters.first_seen` → `alerts.first_seen` (= cluster.first_seen при создании, scorer `_create_alert_idempotent`) →
`alerts.delivered_at` (notifier при успехе). `posts.cluster_id` FK есть (task-022).
Паттерн метрик: `observability/alert_status.py` → `log_event` (агрегаты-only). Beat-расписание:
`scheduler.py` (5 существующих периодик, интервалы из Settings). Redis-клиент: `storage/redis_client.py::get_redis_client`.

## Goal

Каждые N минут (default 300с) в structured-логах появляется `signal_latency`: p50/p95/count для
доставленных алертов за скользящее окно, в двух разрезах — **e2e** (`delivered_at - min(posted_at)
постов кластера`) и **delivery** (`delivered_at - alert.first_seen`); рядом `redis_memory`
(used_memory, maxmemory). Это прибор для E5-обещания «real-time» и триггер для TASK-053
(событийный скоринг). DoD = AC.

## Discussion
- Q: Что считать «задержкой»? → Decision: **две** метрики: e2e от появления поста (честная, продуктовая)
  и delivery от создания алерта (диагностическая — где именно теряем). Free-задержка из TASK-040
  исказит p95 → исключаем алерты с `deliver_after IS NOT NULL` из метрики (или отдельный разрез) —
  согласовать поле с TASK-040; до его мержа фильтр не нужен.
- Q: Где считать? → Decision: SQL-агрегат `PERCENTILE_CONT(0.5/0.95) WITHIN GROUP` одним запросом
  по `alerts JOIN posts USING(cluster_id)` за окно (default 1ч, настройка) — БД маленькая (ретенция),
  Beat-тик раз в 5 мин не давит. Никакого Prometheus сейчас — логи-агрегаты как everywhere.
- Q: Куда вешать тик? → Decision: новая Beat-периодика `emit-signal-latency` в `scheduler.py`
  (паттерн существующих), task в `observability`-friendly модуле (например `alerts/tasks.py`-соседстве
  не размазываем — отдельный лёгкий task-модуль или существующий ops-task путь; решит executor по месту,
  главное — без импортных циклов, как `alert_status.py` «safe to import anywhere»).
- Q: Redis memory тут же? → Decision: да — тот же тик дешёво снимает `INFO memory`
  (used_memory, used_memory_peak, maxmemory) → `log_event("redis_memory", ...)`. Закрывает «P7 дёшево».

## Scope
- **Touch ONLY:**
  - `backend/src/observability/signal_latency.py` — **новый**: `emit_signal_latency(session) -> dict`
    (SQL-перцентили, окно из Settings) + `emit_redis_memory(redis) -> dict` (паттерн `alert_status.py`).
  - Celery-task + Beat-запись: `scheduler.py` (`emit-signal-latency`, интервал `latency_emit_interval_seconds`
    default 300) + task-обёртка рядом с существующими периодиками.
  - `backend/src/config.py` — `latency_emit_interval_seconds`, `latency_window_seconds` (default 3600).
  - tests: `backend/tests/unit/observability/test_signal_latency.py` (**новый**), integration-тест с db_session.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** scorer/pipeline/alerts-доставку (только читаем), модели/миграции (поля уже есть), `/ready`.
- **Blast radius:** +1 Beat-периодика (лёгкий SELECT раз в 5 мин); новые settings с дефолтами. Ничего пользовательского не меняется.

## Acceptance Criteria
- [ ] **AC1 — SQL-перцентили (failing-test anchor).** Given доставленные алерты с известными таймстампами,
  When `emit_signal_latency`, Then p50/p95/count корректны для обоих разрезов (e2e и delivery), окно соблюдено;
  пустое окно → count=0, p50/p95=null, без ошибок. RED первым.
- [ ] **AC2 — log_event-агрегаты.** Given emit, Then `log_event("signal_latency", e2e_p50_s=…, e2e_p95_s=…, delivery_p50_s=…, delivery_p95_s=…, count=…, window_s=…)` — секунды float, агрегаты-only.
- [ ] **AC3 — Beat-тик.** Given поднятый стек, When интервал прошёл, Then запись в логах worker'а появляется периодически (integration/G2).
- [ ] **AC4 — redis_memory.** Given тик, Then `log_event("redis_memory", used=…, peak=…, max=…)`; Redis недоступен → warn, тик не падает.
- [ ] **AC5 — G2.** `make up` → реальный прогон: создать алерт (фикстурой/руками) → в течение интервала в логах есть `signal_latency` с count≥1 и правдоподобными секундами.

## Plan
1. **RED:** unit на SQL-агрегат (db_session, заранее посеянные alerts/posts с контролируемыми ts).
2. `observability/signal_latency.py` — два emit'а; settings.
3. Task-обёртка + Beat-запись в `scheduler.py` (паттерн `resweep`).
4. GREEN + integration + G2 через `make up`; tasks-index на ship.

## Invariants
- Метрика read-only: ни одна строка БД не мутируется.
- Агрегаты-only в логах (no raw content) — compliance §7.
- Тик не падает из-за пустых данных/недоступного Redis (warn + продолжение).
- Интервалы/окна — только из Settings (no magic literals).

## Edge cases
- Кластер без постов (теоретически) → e2e-разрез пропускает алерт (LEFT JOIN + фильтр), delivery считается.
- `delivered_at < posted_at` (часы источника врут) → отрицательные значения клампятся в 0 (отметить count_negative в логе).
- Очень старые недоставленные — не в метрике (только delivered за окно).
- После TASK-040: алерты с искусственной задержкой исключить/выделить разрезом (зафиксировано в Discussion).

## Test plan
- **unit/integration:** `test_signal_latency.py` — точные перцентили на посеянных данных (AC1), формат log_event (AC2, caplog), пустое окно, отрицательная дельта.
- **G2:** `make up` → периодическая запись в логах с реальным алертом (AC3/AC5); `redis_memory` присутствует (AC4).
- **security:** не применимо (read-only агрегаты) — 5.5 скип с пометкой.

## Checkpoints
current_step: 3
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (n/a — read-only)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — locate: полный тайм-чейн уже в моделях (`posts.posted_at`/`fetched_at`, `alerts.first_seen`/`delivered_at`, `posts.cluster_id` FK с task-022) — миграции НЕ нужны; паттерн — `alert_status.py` + `log_event`; Beat-паттерн — 5 существующих периодик в `scheduler.py`. PERCENTILE_CONT доступен в Postgres из коробки. Это «прибор» для главного KPI продукта — скорости; данные отсюда триггерят TASK-053.)
