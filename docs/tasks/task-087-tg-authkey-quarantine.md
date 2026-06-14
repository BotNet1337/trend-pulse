---
id: TASK-087
title: Починить AuthKeyDuplicated-спам — карантин мёртвых сессий пула + алерт ровно один раз
status: done           # planned → in-progress → review → done (PR #148, merged 9c77dd5)
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: "9e85d1e"
branch: "task/087-tg-authkey-quarantine"
tags: [collector, telegram, account-pool, auth-error, ops-alert, prod-critical, phase-0]
---

# TASK-087 — Карантин мёртвых TG-сессий + дедуп алерта (ФАЗА 0)

> Симптом (прод): в ops-TG-канал «по кд» сыпется
> `TG pool: account error on entity resolve (AuthKeyDuplicatedError)`.
> Корень: `collector/telegram/reader.py::_read_one` при non-flood ошибке резолва
> шлёт алерт `reason=auth_error` и кидает `SourceUnavailableError`, **но аккаунт НЕ
> выселяется из пула**. `AuthKeyDuplicatedError` = одна сессия используется двумя
> клиентами одновременно → Telegram НАВСЕГДА инвалидирует ключ. Каждый тик чтения
> снова берёт ту же мёртвую сессию через `AccountPool.acquire()` → снова ошибка →
> снова алерт. Throttle по `reason=auth_error` (один Redis-ключ на reason) не давит
> спам при деградации/эвикции Redis.

## Goal

Минимальный surgical-фикс коллектора: (1) отличать **перманентные** auth-ошибки от
транзиентных; (2) на перманентной — **карантинить** аккаунт в `AccountPool`, чтобы пул
больше никогда его не выдавал; (3) алерт по мёртвой сессии — **ровно один раз** на
аккаунт, причём дедуп НЕ зависит только от эвиктируемого Redis-ключа (карантин = дедуп
в процессе); (4) гарантировать, что полностью мёртвый пул не вешает тик. Scope: только
`collector/` + `observability/pool_health.py` + тесты. БЕЗ frontend/templates/pipeline/scorer.

## Discussion
<!-- durable record; автономные дефолты зафиксированы здесь -->
- Q: как классифицировать перманентные auth-ошибки без импорта telethon на уровне модуля?
  → A: по имени класса ПО ВСЕМУ MRO (`auth_errors.is_permanent_auth_error`) — тот же
  ленивый приём, что `reader._flood_wait_seconds` (matching по структуре, без import-time
  зависимости от telethon). Набор: `AuthKeyDuplicatedError`, `AuthKeyError`,
  `AuthKeyUnregisteredError`, `AuthKeyInvalidError`, `SessionRevokedError`,
  `SessionExpiredError`, `UserDeactivatedError`, `UserDeactivatedBanError`,
  `UnauthorizedError` (базовый telethon-класс ловит и неизвестные подклассы через MRO).
- Q: где живёт карантин? → A: новое булево поле `_Account.quarantined` + метод
  `AccountPool.quarantine_current()`. `acquire()` пропускает карантинных НАВСЕГДА (на жизнь
  процесса). Это и есть Redis-независимый дедуп: карантинный аккаунт больше не выдаётся →
  `_read_one` по нему не вызывается → повторного алерта нет, даже если Redis-throttle-ключ
  эвиктнулся.
- Q: как не повесить тик, когда ВСЕ аккаунты карантинены? → A: `acquire()` бросает новый
  `PoolExhaustedError` (а НЕ `AllAccountsFloodWaitError`), иначе `_acquire_ready_client`
  ушёл бы в `sleep(0)`-цикл (`cooldown_remaining()` карантинных = 0). `PoolExhaustedError`
  пробрасывается до `collect_tick._collect_refs`, где ref скипается как и flood/unavailable.
- Q: ключ дедупа алерта? → A: per-account reason-ключ `auth_dead:{index}` (index = стабильный
  непубличный fingerprint аккаунта в пуле; НИКОГДА session-строка). Длинный cooldown даёт
  существующий `ops_alert_throttle_seconds`. Реальная гарантия «один раз» — карантин, не Redis.
- Q: алерт при iter_messages-ошибке (не только resolve)? → A: да, классификация в ОБЕИХ
  non-flood ветках `_read_one` через общий `_quarantine_dead_account`. AuthKeyDuplicated может
  прилететь на любой запрос.
- Q: первопричина совместного использования сессии (#3 ФАЗА 0)? → A: основные векторы уже
  закрыты/задокументированы: (а) deploy-overlap двух воркеров на одной сессии — PR #133
  (worker stop-first); (б) backfill на pool-сессии — память `trendpulse-tg-session-incident`
  (НИКОГДА не реюзать pool-сессию для backfill). Остаточный код-вектор: per-process registry
  cache + global Redis-lock сериализуют ТИКИ, но клиенты остаются connected между тиками; если
  тик отрабатывает поочерёдно на разных worker-процессах, каждый держит живой коннект к одной
  сессии. Полный single-owner-гард (dedicated single-concurrency collector-worker/queue ИЛИ
  disconnect-after-tick) вынесен в отдельную follow-up surgical-задачу (FZ0-2) + MANUAL-TODO,
  т.к. это ops/deploy-изменение; данный код-фикс уже разрывает петлю спама (карантин) даже при
  остаточном overlap. Решение зафиксировано как дефолт (automode, без вопроса владельцу).
- Дефолт: `quarantined` сбрасывается только пересозданием пула (рестарт воркера) — это
  корректно: после рестарта мёртвая сессия всё ещё мертва и даст РОВНО ОДИН алерт за жизнь
  процесса, что и нужно (напоминание владельцу перевыпустить сессию).

## Acceptance Criteria

- AC1: `is_permanent_auth_error` → True для всех перечисленных классов и их подклассов (MRO),
  False для `FloodWaitError`-подобных и generic `Exception`. Unit-тест.
- AC2: `AccountPool.quarantine_current()` выселяет текущий аккаунт: после карантина `acquire()`
  его НИКОГДА не возвращает; возвращает стабильный int-fingerprint; `quarantined_count` растёт;
  `cooling_count`/`cooldown_remaining()` исключают карантинных. Unit-тесты.
- AC3: все аккаунты карантинены → `acquire()` бросает `PoolExhaustedError` (не
  `AllAccountsFloodWaitError`); смешанный пул (часть cooling, часть live) ведёт себя как раньше.
- AC4: reader на перманентной auth-ошибке (resolve И iter) карантинит текущий аккаунт и кидает
  `SourceUnavailableError`; следующий тик берёт ДРУГОЙ (живой) аккаунт, мёртвый не реюзается.
  Транзиентная non-flood ошибка → прежнее поведение (`reason=auth_error`, без карантина).
- AC5: алерт о мёртвой сессии уходит РОВНО ОДИН раз (per-account reason-ключ + карантин);
  спам прекращается даже если Redis-throttle-ключ эвиктнут (карантин не даёт повторного вызова).
  Текст алерта без секрета/session-строки. Unit-тест.
- AC6: `PoolExhaustedError` пробрасывается из reader и скипается в `collect_tick._collect_refs`
  (тик не падает). `emit_pool_health` отражает `quarantined` в healthy/aggregates.
- AC7: scope — тронут только `collector/*` + `observability/pool_health.py` + тесты; покрытие
  нового кода ≥80%; `make test` + `make ci-fast` зелёные.

## Verify
- `make test` (unit) зелёный; новые тесты `test_auth_quarantine.py` проходят.
- `make ci-fast` (ruff format --check, ruff check, mypy) зелёный.
- Живой прод-чек (collector выселяет мёртвый аккаунт, алерт один раз, живые продолжают
  ингест, Redis без OOM) — owner-gated MANUAL-TODO (нужна реально мёртвая сессия в пуле;
  на текущем проде сессии healthy=2, 0 auth-ошибок — латентный фикс).

## Review (G3)
- code-reviewer (adversarial, отдельная сессия) на prod-diff `backend/src`: **0 CRITICAL**.
  Подтверждено: нет бесконечного цикла/хэнга (PoolExhaustedError прозрачно пробрасывается
  из reader в `collect_tick._collect_refs`); once-only гарантия держится при эвикции Redis
  (карантин — дедуп); `validate_ref` не пробрасывает (PoolExhausted<:CollectorError<:Exception
  ловится широким except → False); нет утечки секретов в алертах/логах; нет гонок (single-loop
  per worker).
- **HIGH (исправлено):** базовый `UnauthorizedError` (401) в наборе мог по MRO ложно
  карантинить ЖИВОЙ аккаунт на транзиентном reconnect-401. Карантин необратим до рестарта →
  fail-safe: убрал базовый класс из `_PERMANENT_AUTH_ERROR_NAMES`, оставил только
  однозначно-мёртвые классы. Неизвестный/голый 401 → транзиентный путь (throttled `auth_error`,
  БЕЗ выселения) — безопасный восстановимый режим. Тесты обновлены (голый UnauthorizedError →
  false; MRO проверяется подклассом реального permanent-класса).
- MEDIUM (принято как есть): алерт повторяется ОДИН раз на рестарт воркера (карантин in-memory)
  — ожидаемо/задокументировано (напоминание перевыпустить сессию). LOW: нет health-emit при
  PoolExhaustedError выходе — намеренно (per-account алерт уже ушёл; иначе спам каждый тик).

## Checkpoints
- [x] G0 plan (this doc)
- [x] G1 do (tests-first → code): auth_errors.py, account_pool.py, reader.py, errors.py,
      pool_health.py, tasks.py + test_auth_quarantine.py (+ test_pool_health key-set)
- [x] G2 verify: `make test` 830 passed; покрытие изменённых модулей 91%; ci-fast (ruff
      format --check / ruff check / mypy 171 files) зелёный
- [x] G3 review: code-reviewer, 0 CRITICAL, HIGH исправлен (см. выше)
- [x] G4 ship: PR #148 merged (squash) → main `9c77dd5`; ветка удалена

current_step: done
