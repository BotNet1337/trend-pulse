---
id: TASK-127
title: Latency — ускорить путь post→alert (scorer interval 300→60)
status: planned
owner: backend
created: 2026-06-17
updated: 2026-06-17
baseline_commit: 6c33a50e5820b9769cddbe0bf9443d63ece29f51
branch: ""
tags: [scoring-evolution, s6, backend, latency, pain-p3, config]
---

# TASK-127 — Latency: ускорить путь post→alert (P3 «продаём скорость»)

> Surgical step 1 для S6: понизить `scorer_interval_seconds` 300→60 (config-only) — scorer
> тикает раз в 60с вместо 300с. С батчем 60с → worst-case post→alert ~2-3 мин (было ~6-7).
> Нулевое изменение кода-пути: меняется ОДИН named-constant дефолт. Event-driven (TASK-053) — отложен.

## Context

P3 ([pain-points](../architecture/pain-points.md)): «продаём скорость», а цепочка
collector(60s)→buffer→batch(60s)→scorer(**300s**) даёт p50 post→alert ~6 мин. S6
([03-scoring-evolution-plan §S6](../architecture/states/03-scoring-evolution-plan.md)) /
D6 ([02-state-target §D6](../architecture/states/02-state-target.md#d6)) рекомендует
**event-driven trigger (1) forever + interval 300→60 (2) немедленно дёшево**. Этот тикет — шаг 2:
самый малый, безопасный, нулевого-радиуса диффект.

Прибор для proof — TASK-036 (`observability/signal_latency.py`, beat `emit-signal-latency`),
который уже эмитит `signal_latency` p50/p95 в двух разрезах (e2e `delivered_at - min(posted_at)`,
delivery `delivered_at - alert.first_seen`). Метрику менять НЕ нужно — она уже ловит интервал; этот
тикет лишь сдвигает время, которое она измеряет.

Текущее устройство (прочитано):
- `config.py`: `_DEFAULT_SCORER_INTERVAL_SECONDS = 300`, поле `scorer_interval_seconds` (env-override
  `SCORER_INTERVAL_SECONDS`). `_DEFAULT_BATCH_INTERVAL_SECONDS = 60`, `_DEFAULT_COLLECT_INTERVAL_SECONDS = 60`.
- `scheduler.py`: `beat_schedule["score-tick"].schedule = float(_settings.scorer_interval_seconds)`.
- `pipeline/tasks.py::score_tick` → `scorer/tasks.py::score_recent_clusters` — тик идемпотентен:
  кластеры без in-window постов / без topic-overlap пропускаются; `_persist_score` = `ON CONFLICT DO UPDATE`
  (scores не растут); алерты идемпотентны по `uq_alerts_user_cluster`. Чаще тикать = больше DB-чтений,
  НЕ дубли алертов/скоров.
- `tests/unit/test_scheduler.py:31` ассертит `scorer_interval_seconds == 300` — **сломается**, надо
  перевернуть на `== 60` (тот же тест — anchor для RED→GREEN).

## Goal

p50 post→alert сдвинуть с ~6 мин к <2 мин, изменив ровно ОДИН config-дефолт
(`_DEFAULT_SCORER_INTERVAL_SECONDS` 300→60). Сохранить инвариант collect ≤ batch ≤ scorer.
DoD = Acceptance Criteria ниже. Event-driven scoring (TASK-053) явно ОТЛОЖЕН.

## Discussion

- Q: Какой шаг брать сейчас? → A: D6-вариант 2 (interval 300→60). → Decision: только config-дефолт.
  Rationale: smallest-first; нулевой код-путь; немедленная ценность; event-driven (D6.1) — больший радиус.

### Варианты latency-ускорения (D6, ≥5) — рекомендация smallest-first

1. **(РЕК. ЭТОТ ТИКЕТ) Снизить `scorer_interval_seconds` 300→60 (config-дефолт).** Радиус: 1 строка
   дефолта + 1 тест + комменты. worst-case post→alert = collect(60)+batch(60)+scorer(60) ≈ 3 мин,
   p50 ~2 мин. Trade-off: scorer тикает в 5× чаще → больше DB-чтений; ограничено (тик идемпотентен,
   пропускает когда нечего скорить, БД маленькая по ретенции) — приемлемо на текущем масштабе.
2. **(DEFER → TASK-053, owner-gated) Event-driven scoring** — батч, обновивший свежий кластер, кладёт
   scorer-job в очередь «hot cluster» вместо фикс-тика. «Навсегда»-фикс (D6.1), но больший blast radius
   (новая очередь/триггер, push pipeline→scorer). Вне scope этого хирургического тикета.
3. Двух-скоростной beat (D6.3): алерт-кандидаты скорить чаще, остальное реже. Сложнее (две периодики +
   маршрутизация), не нужно при текущем объёме.
4. Streaming-инкремент фич в Redis (D6.4): не пересчитывать из Postgres каждый тик. Большой рефактор
   фич-пайплайна — преждевременно.
5. Push из pipeline в scorer через очередь «hot cluster» (D6.5) — частный случай (2), та же причина defer.
6. Гибрид 60s + немедленный re-score при пересечении порога широты (D6.6) — комбинация (1)+(3); после (2).

→ **Рек. 1 сейчас (этот тикет), 2 (TASK-053) — следующий, owner-gated.**

- Q: Не упереться ли в beat max_interval? → A: Нет. Celery beat `max_interval=300s` — это лишь верхняя
  граница сна beat между тиками; периодика с schedule 60s срабатывает по своему расписанию (beat всё равно
  просыпается ≥ каждые 300s). `beat_heartbeat_ttl_seconds`(600) > 300 — независимый инвариант, НЕ затронут.
  → Decision: 60s валиден, валидаторы heartbeat не трогаем.
- Q: Нужен ли validator scorer ≥ batch? → A: В коде такого нет (enforced только collect ≤ batch). scorer
  логически идёт ПОСЛЕ батча, но между ними нет drain-зависимости (scorer читает уже-персистнутые кластеры),
  поэтому scorer == batch == 60 безопасно. → Decision: НЕ добавляем новый validator (scope-creep); фиксируем
  цепочку collect ≤ batch ≤ scorer как тест-инвариант (assert в test_scheduler), не как config-validator.
- Q: Менять ли метрику TASK-036? → A: Нет — она уже эмитит p50/p95 post→alert; proof = сравнить
  `signal_latency` до/после на проде. При ~0 живых алертов — доказываем интервал-математикой
  (collect+batch+scorer = 60+60+60). → Decision: метрику не трогаем, используем как прибор.
- Q: `scorer_recent_window_seconds`(3600) и `alerts_per_hour_limit`-окно(3600)? → A: Не зависят от тик-частоты
  (окна по `updated_at`/`first_seen`, не по числу тиков). Чаще тикать их не нарушает. → Decision: не трогаем.

## Scope

- **Touch ONLY:**
  - `backend/src/config.py` — `_DEFAULT_SCORER_INTERVAL_SECONDS` 300 → 60 (+ обновить коммент-блок «scorer
    tick every 5 minutes» → «every minute»).
  - `backend/tests/unit/test_scheduler.py` — `test_intervals_match_documented_defaults`: ассерт
    `scorer_interval_seconds == 300` → `== 60`; коммент «scorer every 300s» → «every 60s»; + добавить
    assert монотонной цепочки `collect ≤ batch ≤ scorer` (инвариант-страж).
  - `backend/src/scheduler.py` — обновить коммент «fires the scorer tick every SCORER_INTERVAL_SECONDS»
    остаётся как есть (имя-через-settings, без литерала); никакого код-изменения, только если коммент
    называет «300s» — заменить на «60s» (проверить при do).
  - `docs/tasks/tasks-index.md` — строка на ship.
- **Do NOT touch:** scorer-логика (`scorer/tasks.py`, `scorer/score.py`), pipeline, `observability/signal_latency.py`
  (метрика TASK-036), модели/миграции, alerts-доставка, любые другие интервалы (collect/batch/retention/…),
  event-driven очередь (TASK-053). Никаких новых config-полей и validator'ов.
- **Blast radius:** один named-constant дефолт scheduler-периодики «score-tick». Потребители: beat
  `beat_schedule["score-tick"]` (читает settings — авто-подхват), scorer-тик (чаще зовётся, идемпотентен).
  Без схемы/API/openapi/очередей/публичных контрактов. Env-override `SCORER_INTERVAL_SECONDS` сохранён —
  прод может откатить значением env без передеплоя кода.

## Acceptance Criteria

- [ ] **AC1 — новый дефолт (failing-test anchor).** Given свежий `Settings()` без env-override, When читаем
  `scorer_interval_seconds`, Then значение == 60. (RED первым: текущий тест ассертит 300.)
- [ ] **AC2 — beat подхватывает.** Given `beat_schedule`, When читаем `score-tick`, Then
  `schedule == float(settings.scorer_interval_seconds)` (== 60.0) и task == `SCORE_TICK_TASK`.
- [ ] **AC3 — инвариант цепочки.** Given дефолтные `Settings()`, When сравниваем интервалы, Then
  `collect_interval_seconds ≤ batch_interval_seconds ≤ scorer_interval_seconds` (60 ≤ 60 ≤ 60) держится;
  существующий collect ≤ batch validator не нарушен.
- [ ] **AC4 — env-override сохранён.** Given `SCORER_INTERVAL_SECONDS=300` в окружении, When `Settings()`,
  Then `scorer_interval_seconds == 300` (откат значением env без передеплоя возможен).
- [ ] **AC5 — нет регрессий тик-пути.** Given дефолт 60s, When `score_tick`/`score_recent_clusters` отрабатывает,
  Then поведение идемпотентно (нет дублей Score/Alert) — существующие scorer-тесты зелёные, byte-identical логика.
- [ ] **AC6 — latency proof.** Given прод после деплоя, When метрика `signal_latency` (TASK-036) эмитится,
  Then e2e p50 падает к <2 мин ИЛИ (при ~0 живых алертов) интервал-математика 60+60+60 задокументирована в Details.

## Plan

1. **RED:** в `test_scheduler.py` перевернуть `test_intervals_match_documented_defaults` на `== 60` (падает на текущем коде).
2. `config.py` — `_DEFAULT_SCORER_INTERVAL_SECONDS = 60` (+ коммент-блок «every 5 minutes»→«every minute»).
3. `test_scheduler.py` — добавить assert цепочки `collect ≤ batch ≤ scorer` (AC3) + добавить/проверить AC4 env-override тест.
4. `scheduler.py` — обновить любой коммент, называющий «300s» для scorer (если есть), на «60s» (без код-изменений).
5. GREEN: `make ci-fast` (unit) зелёный; mypy+ruff чисто.
6. tasks-index строка на ship; в Details зафиксировать latency-proof (метрика до/после ИЛИ интервал-математика).

## Invariants

- **collect ≤ batch ≤ scorer** (монотонная цепочка задержки): collect ≤ batch — enforced config-validator'ом
  (`validate_collect_interval_invariant`); batch ≤ scorer — НЕ enforced в коде, фиксируется тест-ассертом
  (60 ≤ 60). Понижение scorer ниже batch допустимо (scorer не drain-зависит от batch), но бессмысленно —
  держим равенство.
- Тик идемпотентен: чаще тикать НЕ создаёт дубли (Score = ON CONFLICT upsert; Alert = `uq_alerts_user_cluster`).
- `beat_heartbeat_ttl_seconds`(600) > beat max_interval(300) — НЕ затронут (независимый инвариант).
- No magic literals: значение живёт в named-constant `_DEFAULT_SCORER_INTERVAL_SECONDS` + env-override.
- Никаких новых config-полей/validator'ов/очередей — нулевой код-путь, только дефолт.

## Edge cases

- Прод имеет `SCORER_INTERVAL_SECONDS` в env? → env-override побеждает дефолт (AC4) — деплой меняет поведение
  только там, где env НЕ задан; зафиксировать при do, что прод-deploy.env не пинит scorer-интервал (иначе no-op).
- ~0 живых алертов на проде → e2e p50 не наблюдаем → AC6 удовлетворяется интервал-математикой (60+60+60),
  записанной в Details (как в Discussion TASK-036).
- DB-нагрузка от 5× частоты тика → тик идемпотентен и пропускает «нечего скорить»; БД маленькая (ретенция);
  если на проде вырастет нагрузка — откат значением env без передеплоя.

## Test plan

- **unit:** `test_scheduler.py` — AC1 (дефолт 60), AC2 (beat подхватывает 60.0), AC3 (цепочка collect≤batch≤scorer),
  AC4 (env-override 300 сохранён). RED первым (текущий ассерт 300 падает).
- **integration:** не требуется (config-only, без БД/брокера); существующие scorer-тесты зелёные (AC5).
- **G2 / прод-факт:** метрика `signal_latency` (TASK-036) до/после деплоя — e2e p50 < 2 мин (AC6) ИЛИ
  интервал-математика при ~0 алертов; beat/worker-нагрузка в норме.
- **security:** N/A (config-дефолт, без auth/input/secrets) — 5.5 скип с пометкой.

## Checkpoints
current_step: 3
baseline_commit: 6c33a50e5820b9769cddbe0bf9443d63ece29f51
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + latency proof)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (N/A — config-only, no auth/input/secrets)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — locate: единственный код-touch = `_DEFAULT_SCORER_INTERVAL_SECONDS` 300→60 в config.py:37;
beat подхватывает через `scheduler.py:90-93` (settings-driven, без литерала); `test_scheduler.py:31`
ассертит 300 → flip на 60 = RED-anchor. Тик идемпотентен (scorer/tasks.py: ON CONFLICT upsert +
uq_alerts_user_cluster), чаще = больше DB-чтений, не дубли. Метрика TASK-036 (observability/signal_latency.py)
= прибор proof, НЕ трогаем. Инвариант collect(60)≤batch(60)≤scorer(60→) — collect≤batch enforced validator'ом,
batch≤scorer фиксируем тест-ассертом. Event-driven (D6.1) = TASK-053, отложен/owner-gated. worst-case
post→alert после = collect60+batch60+scorer60 ≈ 2-3 мин (было ~6).)
