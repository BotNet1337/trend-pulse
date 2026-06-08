---
id: TASK-008
title: Scorer — velocity/engagement/cross_channel viral score + alert trigger
status: done        # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "f75c9294ec268c8abb6be97c96633ce66fbfe608"
branch: "gsd/phase-008-scorer"
tags: [backend, scorer, scoring, alerts, celery]
---

# TASK-008 — Scorer (velocity · engagement · cross_channel + alert trigger)

> Реализовать viral scoring (`scorer/score.py`) поверх НОРМАЛИЗОВАННЫХ `PostMetrics` (ADR-001) — формула `viral_score = velocity·0.4 + engagement·0.35 + cross_channel·0.25` — и Celery-задачу (`scorer/tasks.py`, тик каждые 5 мин из task-006), которая для свежих кластеров каждого юзера считает score, применяет его topic-фильтр + порог и создаёт ровно один `alert` (task-002), не дублируя по уже отмеченному кластеру.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md) §4 «Scorer», [`../architecture/high-level-architecture.md`](../architecture/high-level-architecture.md) §3–§4): после батч-pipeline (task-007: dedup→normalize→embed→cluster) в Postgres лежат кластеры с `user_id`. Scorer — следующий шаг data-flow (§4 шаг 4): «считает `viral_score = velocity·0.4 + engagement·0.35 + cross_channel·0.25`; если `> threshold` юзера и тема совпала — создаёт alert». Это предпоследнее звено критического пути до первого сигнала (roadmap: 001→002→005→006→007→**008**→009).

Scorer обязан быть **платформо-независимым**: работает только с нормализованными `PostMetrics`/кластерами (ADR-001 — «`metrics` нормализуются к общему виду, чтобы scorer был платформо-независим»), ничего не знает про Telegram. Это даёт бесплатный cross-platform viral score в Фазе 2 (overview §9).

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — full type hints, no magic literals (веса/порог — именованные константы/настройки), Celery task args JSON-serializable (передаём id, не ORM), cross-module через сервис-интерфейсы (`storage/` репозитории), SQL только через SQLAlchemy bind-params.

## Goal

Появляется модуль `scorer/`: чистая детерминированная функция `compute_viral_score(...)` по формуле overview §4 над `PostMetrics` + Celery-задача `score_recent_clusters`, которую beat дёргает каждые 5 минут (task-006). Задача для каждого активного юзера берёт его свежие кластеры, считает score, применяет topic-фильтр и порог из его alert-config (task-004 schema) и при `score > threshold` ∧ topic-match создаёт строку `alert` (task-002) — **идемпотентно** (повторный тик по тому же кластеру не плодит дубли). DoD ниже (AC1–AC6).

## Discussion
<!-- durable record of clarifications. Решения по дефолтам overview/ADR; обратимы. -->
- Q: Откуда берутся метрики для scoring? → A: из НОРМАЛИЗОВАННЫХ `PostMetrics` (ADR-001), агрегированных по кластеру → Decision: scorer принимает уже-нормализованные данные кластера (метрики + список уникальных каналов + временные метки), НЕ лезет в Telegram/raw (rationale: ADR-001 — scorer платформо-независим; платформо-специфика живёт в `metrics.extra` и сюда не протекает).
- Q: Формула и веса? → A: overview §4 дословно → Decision: `viral_score = velocity·0.4 + engagement·0.35 + cross_channel·0.25`; `velocity = Δchannel_count/Δhours` (log-scale), `engagement = (views + forwards·3 + reactions·2)/channel_avg`, `cross_channel = unique_channels_count/watched_channels_count`. Веса/коэффициенты (3, 2) — именованные константы (CONVENTIONS: no magic literals).
- Q: log-scale velocity — что именно? → A: рост по числу каналов нелинеен → Decision: `velocity = log1p(Δchannel_count) / Δhours` (log1p — безопасно для 0; деление на часы — скорость распространения). Зафиксировано в Details/Edge cases.
- Q: Что делает Celery-задача и как часто? → A: тик каждые 5 мин (overview §4, beat из task-006) → Decision: `score_recent_clusters` — beat-задача; внутри per-user обход свежих кластеров, score + topic-filter + threshold → alert. Args JSON-serializable (передаём `user_id`/`cluster_id`, не ORM).
- Q: Где порог и топик юзера? → A: alert-config из watchlist (task-004) → Decision: scorer читает порог (`threshold`) и топик(и) юзера через `storage/`-репозиторий; topic-match — кластер помечен/классифицирован темой, совпадающей с топиком юзера. Дефолтный порог — именованная константа/настройка, не literal.
- Q: Как не дублировать алерт? → A: идемпотентность по кластеру → Decision: алерт уникален по `(user_id, cluster_id)` (или флаг `alerted_at` на кластере) — повторный тик видит уже-отмеченный кластер и пропускает. Конкретный механизм (unique-constraint vs флаг) выбирается под schema task-002 на шаге 3; предпочтение — DB unique-constraint (гонка тиков безопасна).
- Q: Где живёт scorer — `scorer.py` или `scorer/`? → A: overview §8 показывает `pipeline/scorer.py`, но high-level-arch §3 выделяет отдельный модуль `scorer/` → Decision: модуль `scorer/` (как в arch §3), файлы `score.py` (чистая функция) + `tasks.py` (Celery), `__init__.py` (rationale: разделение pure-compute и Celery-обвязки тестируемо и соответствует arch).

## Scope
> **Раскладка:** только `backend/`. Scorer — доменный модуль `backend/src/trendpulse/scorer/`; общается с `storage/` (кластеры, alert-config, alert-запись) только через его публичные сервис-функции/репозитории (CONVENTIONS «cross-module via service interfaces»), регистрируется в beat-расписании (task-006).

- **Touch ONLY (создать):**
  - `apps/trendPulse/backend/src/trendpulse/scorer/__init__.py` — публичный экспорт (`compute_viral_score`, `score_recent_clusters`).
  - `apps/trendPulse/backend/src/trendpulse/scorer/score.py` — чистая детерминированная функция `compute_viral_score(...)` по формуле overview §4 над `PostMetrics`; именованные константы весов/коэффициентов (`VELOCITY_WEIGHT=0.4`, `ENGAGEMENT_WEIGHT=0.35`, `CROSS_CHANNEL_WEIGHT=0.25`, `FORWARD_FACTOR=3`, `REACTION_FACTOR=2`); helper-функции `_velocity`, `_engagement`, `_cross_channel` (pure, без I/O).
  - `apps/trendPulse/backend/src/trendpulse/scorer/tasks.py` — Celery-задача `score_recent_clusters` (per-user обход свежих кластеров → score → topic-filter + threshold → idempotent alert через `storage/`-репозиторий). Args JSON-serializable.
  - `apps/trendPulse/backend/tests/unit/test_score.py` — детерминированные unit-тесты формулы (RED-якорь AC1).
  - `apps/trendPulse/backend/tests/integration/test_scorer_alerts.py` — behavioral (G2): seed кластеров → тик задачи → assert строки `alert` (порог/topic/идемпотентность), маркер `integration`.
- **Touch (минимально, по необходимости):**
  - `apps/trendPulse/backend/src/trendpulse/scheduler.py` — зарегистрировать `score_recent_clusters` в `beat_schedule` каждые 5 мин (если task-006 ещё не оставил слот) — именованная константа `SCORER_TICK_SECONDS`.
  - `apps/trendPulse/backend/src/trendpulse/config.py` — дефолтный порог как настройка (`default_alert_threshold`), если его ещё нет.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`, `api/**`, `collector/**`, `pipeline/**`, `alerts/**` (доставка — task-009; scorer только СОЗДАЁТ строку `alert`, не шлёт), `billing/**`. Схему БД (`storage/models`) не менять — потреблять как есть из task-002; если потребуется unique-constraint для идемпотентности — зафиксировать как зависимость/мелкую миграцию на шаге 3, не расширяя scope молча.
- **Blast radius:** потребитель scorer'а — task-009 (alert delivery читает созданные строки `alert`). Зависит от task-007 (кластеры в Postgres), task-006 (beat/Celery), task-002 (schema `clusters`/`alerts`), task-004 (alert-config: threshold/topic). Контракт наружу: форма `alert`-строки + детерминизм score.

## Acceptance Criteria
- [ ] **AC1 — детерминированный score (RED-якорь).** Given известные входы (`PostMetrics` + Δchannel_count/Δhours + unique/watched каналы), When `compute_viral_score(...)`, Then результат равен заранее посчитанному ожидаемому числу (тест пишется ПЕРВЫМ и сначала падает; формула overview §4 с весами 0.4/0.35/0.25).
- [ ] **AC2 — платформо-независимость.** Given нормализованные `PostMetrics` (без Telegram-специфики), When scoring, Then функция считается без обращения к коллектору/платформе (никаких импортов `collector/`/Telethon в `scorer/`).
- [ ] **AC3 — ниже порога → нет алерта.** Given кластер со `score ≤ threshold` юзера, When `score_recent_clusters` тик, Then строка `alert` НЕ создаётся.
- [ ] **AC4 — выше порога + topic-match → ровно один алерт.** Given кластер со `score > threshold` И темой, совпадающей с топиком юзера, When тик, Then создаётся **ровно одна** строка `alert` (правильный `user_id`/`cluster_id`/score/topic).
- [ ] **AC5 — topic-mismatch → нет алерта.** Given кластер со `score > threshold`, но темой, НЕ входящей в топики юзера, When тик, Then `alert` НЕ создаётся.
- [ ] **AC6 — идемпотентность.** Given уже сработавший по кластеру алерт, When `score_recent_clusters` запускается повторно по тому же кластеру, Then дубликат `alert` НЕ создаётся (всё ещё ровно одна строка).

## Plan
1. **RED:** `tests/unit/test_score.py` — захардкодить вход (`PostMetrics(views/forwards/reactions)`, `channel_avg`, `Δchannel_count`, `Δhours`, `unique_channels_count`, `watched_channels_count`) и руками посчитанный ожидаемый `viral_score`; вызвать `compute_viral_score(...)` (ещё нет) → тест падает (AC1). Добавить кейсы граней (Δhours→0, нулевой engagement, cross_channel=1.0).
2. `scorer/score.py` — именованные константы (веса 0.4/0.35/0.25, `FORWARD_FACTOR=3`, `REACTION_FACTOR=2`); pure helpers `_velocity = log1p(Δchannel_count)/Δhours`, `_engagement = (views + forwards·3 + reactions·2)/channel_avg`, `_cross_channel = unique/watched`; `compute_viral_score(...)` = взвешенная сумма. Full type hints, без I/O. → GREEN для AC1/AC2.
3. `scorer/tasks.py` — `@celery_app.task score_recent_clusters()`: через `storage/`-репозиторий взять активных юзеров → для каждого свежие, ещё-не-отмеченные кластеры → собрать нормализованный вход → `compute_viral_score` → сравнить с `threshold` юзера И проверить topic-match → при прохождении создать `alert` идемпотентно (insert с unique `(user_id, cluster_id)` / отметить `alerted_at`). Args JSON-serializable (id, не ORM); `max_instances`/per-user изоляция (CONVENTIONS).
4. Идемпотентность: предпочесть DB unique-constraint на `(user_id, cluster_id)` в `alerts` — insert ловит конфликт и пропускает (гонка двух тиков безопасна). Если constraint отсутствует в schema task-002 — зафиксировать мелкую миграцию как зависимость на этом шаге.
5. `scheduler.py` — зарегистрировать `score_recent_clusters` в `beat_schedule` с интервалом `SCORER_TICK_SECONDS = 300` (5 мин), если слот ещё не задан task-006.
6. `config.py` — `default_alert_threshold` как настройка (pydantic-settings), без magic literal в коде scorer.
7. **G2 behavioral:** `tests/integration/test_scorer_alerts.py` — seed юзера + alert-config + кластеры (ниже порога / выше+topic-match / выше+topic-mismatch) в тестовую БД → вызвать `score_recent_clusters` → assert строки `alert` (AC3–AC5); повторно вызвать → assert без дублей (AC6).
8. Прогнать `make ci-fast` (ruff+mypy+pytest unit) и `make test-integration` (G2 с поднятыми Postgres/Redis); затем `make up-d` и проверить, что beat планирует scorer-тик в логах.

## Invariants
- **Scorer платформо-независим.** `scorer/` работает только с нормализованными `PostMetrics`/кластерами (ADR-001); НИ одного импорта из `collector/`/Telethon, ни одной платформо-специфичной ветки.
- **`compute_viral_score` — чистая и детерминированная.** Без I/O, без времени/рандома внутри (Δhours приходит аргументом); одни входы → один выход (база для AC1).
- **Веса и коэффициенты — именованные константы**, не magic literals в выражении (CONVENTIONS «no magic literals»: thresholds/factors в константах; время в секундах как именованные константы).
- **Идемпотентность по кластеру** — повторный тик никогда не плодит второй `alert` для той же `(user_id, cluster_id)`.
- **Celery task args JSON-serializable** — передаём `user_id`/`cluster_id`, не ORM-объекты; per-user изоляция (`max_instances=1`).
- **Cross-module через сервис-интерфейсы** — кластеры/alert-config/запись `alert` только через публичные функции `storage/`; SQL — bind-params, не f-string.
- **Scorer не доставляет.** Только СОЗДАЁТ строку `alert`; отправка в Telegram-бот/webhook — task-009.
- **`make` — единственная точка входа** для тестов/окружения (CONVENTIONS).

## Edge cases
- `Δhours → 0` (все каналы засветились в один момент) → деление на ноль во `_velocity`: подставить минимальный временной квант (именованная константа `MIN_WINDOW_HOURS`) или клампить, не падать.
- `channel_avg == 0` (нет исторической базы у канала) → `_engagement`: защититься (epsilon/минимум), иначе ZeroDivision; зафиксировать поведение тестом.
- `watched_channels_count == 0` (пограничная конфигурация) → `_cross_channel`: защита от деления на ноль; кластер без watched-каналов — score не считается / 0.
- `cross_channel > 1.0` теоретически невозможен (unique ≤ watched), но если данные грязные — клампить в `[0, 1]`; зафиксировать инвариант тестом.
- Гонка двух beat-тиков по одному кластеру (overlap, если предыдущий тик не успел) → DB unique-constraint `(user_id, cluster_id)` делает второй insert no-op (AC6 устойчив к гонке).
- Топик у кластера отсутствует/`None` (классификация не проставлена) → topic-mismatch (no alert), не падать.
- Float-детерминизм: `log1p` и взвешенная сумма должны давать стабильное число на CI; в AC1 сравнивать с допуском (`pytest.approx`), а не на точное равенство битов.
- Очень большой `Δchannel_count` → `log1p` гасит рост (по дизайну log-scale), не переполняется.

## Test plan
- **unit:** `tests/unit/test_score.py` — `compute_viral_score(...)` на известных входах == ожидаемое число (пишется ПЕРВЫМ, RED → GREEN, AC1); отдельные кейсы `_velocity`/`_engagement`/`_cross_channel`; грани (Δhours→0, channel_avg=0, watched=0, cross_channel-клампинг). Проверка отсутствия импортов `collector/` (AC2).
- **integration / behavioral (G2):** `tests/integration/test_scorer_alerts.py` (маркер `integration`) — seed юзера + alert-config + кластеры в тестовую БД → `score_recent_clusters` → assert: ниже порога нет alert (AC3); выше+topic-match ровно один alert с корректными полями (AC4); выше+topic-mismatch нет alert (AC5); повторный тик без дублей (AC6).
- **runtime:** `make up-d` → в логах `beat` виден запланированный scorer-тик каждые 5 мин; `worker` исполняет `score_recent_clusters` без ошибок.
- Запуск только через `make` (`ci-fast`, `test-integration`) — не bare `pytest`.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "f75c9294ec268c8abb6be97c96633ce66fbfe608"
branch: "gsd/phase-008-scorer"
lock: "loop-008"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto — PASS, 0 blocking; 2 LOW fixed)
- [x] 5.5 security (N/A — pure compute, own-tenant)
- [x] 6 ship (PR #9, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по overview §4 «Scorer» + high-level-architecture §3–§4 + ADR-001; depends on task-007 (кластеры), task-006 (beat/Celery), task-002 (schema clusters/alerts), task-004 (alert-config). Scorer платформо-независим над нормализованными `PostMetrics`; security 5.5 = N/A, чистый compute над данными своего тенанта.)


### Step 3 do · 4 verify · 5 review · loop-008
- **do (TDD, FLAT):** `scorer/score.py` pure `compute_viral_score` (overview §4: weights 0.4/0.35/0.25; velocity=log1p(Δch)/Δh; engagement=(views+fwd·3+react·2)/channel_avg; cross_channel=unique/watched; named consts; zero-div guards). `scorer/tasks.py` `score_recent_clusters` (per-user fresh clusters → score → topic+threshold → idempotent Alert). Wired into existing `score_tick` seam (no competing task). Idempotency: unique `alerts(user_id,cluster_id)` (migration 0003, down_revision 0002) + savepoint/begin_nested insert (IntegrityError → no-op, prior work preserved). RED→GREEN: test_score AC1 hand-verified 4.381960808726313. ci-fast 139 unit green (mypy strict). AC2 platform-independent (score+tasks no collector import).
- **verify (G2):** integration 3 passed — AC4+AC6 (ровно один alert, идемпотентно при повторном тике), AC3 (≤ threshold → нет), AC5 (topic-mismatch → нет); migration chain 0001→0002→0003 PASS.
- **review (opus) PASS 0 blocking.** 2 LOW исправлены (убран мёртвый `default_alert_threshold`; AC2-тест расширен на `scorer.tasks`). MEDIUM (документированные footguns, не блок):
  - **scoring per-TOPIC, не per-CLUSTER** (нет post↔cluster FK) → несколько свежих кластеров одной темы получают одинаковый score и каждый >порога даёт свой alert. **→ task-009 (alert delivery) должен rate-limit'ить; future: post↔cluster FK для точного score.**
  - `channel_avg` = среднее по текущему окну, не исторический baseline (engagement не «спайк-vs-норма») → future: trailing-baseline.
  - `Score`-строки append-only без upsert → растут каждый тик; ретенция/индекс → task-011.
- **security 5.5:** N/A (pure compute, own-tenant, no secret/auth/input/raw SQL).
