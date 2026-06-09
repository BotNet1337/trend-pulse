---
id: TASK-035
title: TG account pool — целевой размер ≥3, health-метрика, self-alert опсам при бане/флуде
status: planned
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e0, backend, collector, observability, pain-p1]
---

# TASK-035 — Пул TG-аккаунтов: health + self-alert (Epic E0)

> P1 из [pain-points](../architecture/pain-points.md): сейчас `POOL_MIN=1` (боевой пул фактически из одной
> dev-сессии — learnings task-005). Бан/FLOOD волной = продукт молчит, а первым об этом узнаёт клиент.
> Сделать: health-метрику пула, self-alert опсам в Telegram, операционный таргет ≥3 аккаунтов.

## Context

`collector/constants.py`: `POOL_MIN=1`, `POOL_MAX=10`, backoff base 2s / cap 300s.
`collector/telegram/account_pool.py::AccountPool`: `from_sessions`, `acquire()` (бросает
`AllAccountsFloodWaitError` когда все остывают), `report_flood_wait()`, `report_success()`,
`cooldown_remaining()`. Сессии — `Settings.telegram_pool_sessions` (CSV из `TELEGRAM_POOL_SESSIONS`).
Метрики-паттерн: `observability/alert_status.py::emit_alerts_by_status` → `log_event(...)` (structured JSON,
агрегаты-only). Доставка: `alerts/backends.py::TelegramBotBackend` (переиспользуемый, SSRF-guarded HTTP).
Ops-конфига для «своего» бота в `Settings` нет.

## Goal

Опс видит здоровье пула (size/active/cooling/смены состояния) в structured-логах и получает Telegram-сообщение
себе при деградации (все аккаунты во FLOOD / пул ниже целевого / auth-ошибка сессии) — раньше, чем заметит
клиент. Целевой размер пула задаётся настройкой (default 3) и алертится при недоборе. Self-alert троттлится.
DoD = AC.

## Discussion
- Q: Поднять `POOL_MIN` до 3 жёстко? → A: нет → Decision: `POOL_MIN=1` остаётся абсолютным полом
  (dev/тесты с одной сессией должны жить), вводим **операционный таргет** `pool_min_healthy: int = 3`
  в `Settings`; пул меньше таргета = деградация (warn-метрика + self-alert), но не отказ старта.
  Реальные 3–5 аккаунтов с запасом 2× — операционная работа owner'а вне кода (отметить в Details при ship).
- Q (owner, 2026-06-09): пока в vault **одна** сессия — добавит ещё, когда увидит, что апка стабильна.
  → Decision: в prod-env выставить `POOL_MIN_HEALTHY=1` (через deploy.env/Ansible), чтобы недобор не
  спамил self-alert'ами каждый час; код-default остаётся 3; когда owner добавит сессии — поднять env
  до 3 (одна строка). AC3 проверяется юнитом с `pool_min_healthy=3`, живой G2-недобор — форсом env.
- Q: Куда слать self-alert? → Decision: новые настройки `ops_telegram_bot_token`/`ops_telegram_chat_id`
  (env, optional; пусто → self-alert выключен, только лог). Переиспользуем `TelegramBotBackend` —
  свой HTTP-код не катаем. Этот же ops-бот дальше нужен витрине (TASK-044) — двойная отдача.
- Q: Где детектить деградацию? → Decision: в местах, где она уже видна: (1) `AllAccountsFloodWaitError`
  в reader-цикле; (2) auth/ban-исключение Telethon при connect/read (маппится в Collector-ошибку);
  (3) периодическая сводка пула (size, cooling, target) в существующем collector-тике — без нового Beat-расписания.
- Q: Троттлинг self-alert'ов? → Decision: не чаще 1 сообщения на причину в `ops_alert_throttle_seconds`
  (default 3600, именованная константа/настройка) — ключ троттла в Redis.

## Scope
- **Touch ONLY:**
  - `backend/src/config.py` — `pool_min_healthy` (default 3), `ops_telegram_bot_token`, `ops_telegram_chat_id`, `ops_alert_throttle_seconds`.
  - `backend/src/observability/pool_health.py` — **новый**: `emit_pool_health(...)` (паттерн `alert_status.py`) + `notify_ops(reason, text)` (троттл через Redis, отправка через `TelegramBotBackend`, ошибки доставки глотаются в warn-лог — self-alert не должен ронять сбор).
  - `backend/src/collector/telegram/account_pool.py` — read-only свойства для метрики (`size`, `cooling_count`) если их нет.
  - точка сбора (`collector`-цикл/задача, где ловится `AllAccountsFloodWaitError`) — вызовы `emit_pool_health` + `notify_ops` на деградации.
  - `ops/ansible/roles/env/templates/` — `OPS_TELEGRAM_BOT_TOKEN`/`OPS_TELEGRAM_CHAT_ID` в sensitive-шаблон.
  - tests: `backend/tests/unit/collector/test_pool_health.py` — **новый**; правки `tests/unit/observability/` по паттерну.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** интерфейс `SourceCollector` (ADR-001 — rate-limit/health инкапсулированы), ротацию/backoff-логику пула, alerts-доставку юзерам, `/ready` (деградация пула ≠ неготовность API — не гейтим трафик).
- **Blast radius:** новые settings (optional, default-safe); новый observability-модуль; 2 env-ключа в Ansible. Пайплайн/скоринг не затронуты.

## Acceptance Criteria
- [ ] **AC1 — health-метрика (failing-test anchor).** Given пул из N аккаунтов, M в cooldown, When `emit_pool_health`, Then `log_event("pool_health", size=N, cooling=M, healthy=N-M, target=pool_min_healthy, degraded=bool)` — агрегаты-only, без сессий/секретов. Пишется ПЕРВЫМ (RED).
- [ ] **AC2 — self-alert при all-flood.** Given все аккаунты во FLOOD (фейк-пул), When reader ловит `AllAccountsFloodWaitError`, Then `notify_ops` отправляет сообщение через ops-бота (мок HTTP) с причиной и cooldown_remaining.
- [ ] **AC3 — self-alert при недоборе пула.** Given сессий меньше `pool_min_healthy`, When сводка пула, Then warn-метрика `degraded=true` + однократный self-alert.
- [ ] **AC4 — троттлинг.** Given повторная деградация той же причины в течение throttle-окна, When `notify_ops`, Then второе сообщение НЕ отправляется (Redis-ключ), лог пишется.
- [ ] **AC5 — отказоустойчивость self-alert.** Given ops-бот недоступен/токен пуст, When `notify_ops`, Then сбор НЕ падает (warn-лог, no raise); при пустых настройках — только метрика.
- [ ] **AC6 — секреты + G2.** Given конфиг, When инспекция, Then ops-токен из env (Ansible sensitive), не светится в логах/Sentry (scrub `_token`); `make ci-fast` зелёный; ручная G2: задушить фейк-пул → сообщение пришло в реальный тест-чат.

## Plan
1. **RED:** `test_pool_health.py` — AC1 (emit) + AC2 (all-flood → notify, мок backend/Redis).
2. `config.py` — настройки; `observability/pool_health.py` — emit + notify_ops (троттл, переиспользование `TelegramBotBackend`).
3. `account_pool.py` — экспонировать `size`/`cooling_count` (read-only, без изменения поведения).
4. Врезки в collector-точки: all-flood, auth-fail, периодическая сводка.
5. Ansible env-шаблоны; GREEN + G2 (реальный тест-чат); tasks-index на ship.

## Invariants
- Сбор никогда не падает из-за самонаблюдения (метрика/self-alert — best-effort).
- `SourceCollector`-интерфейс не меняется (ADR-001); ротация/backoff пула не тронуты.
- В метриках/алертах — только агрегаты: ни session-string, ни токенов, ни содержимого постов.
- `POOL_MIN=1` остаётся валидным для dev; деградация — warn, не crash.

## Edge cases
- Redis недоступен при троттле → шлём без троттла? Нет: fail-open в ЛОГ (не спамим Telegram при сетевом шторме), отправка пропускается с warn.
- Пул из 1 аккаунта в dev с пустыми ops-настройками → тишина, только метрика (не раздражаем dev).
- FLOOD c retry_after > cap → cooldown_remaining корректно в сообщении (секунды, не наносы).
- Одновременные воркеры эмитят сводку → троттл-ключ общий в Redis — дублей сообщений нет.

## Test plan
- **unit:** `test_pool_health.py` — emit-агрегаты (AC1), notify при all-flood (AC2, фейк-пул из conftest `make_pool()`), троттл (AC4, фейк-Redis/мок), пустые настройки → no-op (AC5), недобор (AC3).
- **integration:** не требуется (HTTP замокан); существующие collector-тесты зелёные (поведение пула не менялось).
- **G2:** реальный тест-чат: форсануть деградацию в dev (`pool_min_healthy=99`) → сообщение пришло; `make ci-fast` зелёный.
- **security (5.5):** ops-токен из env, scrub в Sentry покрывает `_token`, нет секретов в log_event.

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
- [ ] 5.5 security (token/secrets — применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — locate: `POOL_MIN=1` в `collector/constants.py`; `AllAccountsFloodWaitError` в `collector/errors.py`; паттерн метрик `observability/alert_status.py::emit_alerts_by_status` + `log_event`; `TelegramBotBackend` переиспользуем для ops-бота; ops-конфига в Settings нет — добавить. `/ready` НЕ трогаем: деградация пула не должна гейтить API-трафик. Операционная часть (купить/прогреть 3–5 аккаунтов, прокси) — вне кода, на owner.)
