---
id: TASK-062
title: Долги TASK-051 — ops-тесты /v1 + showcase mypy (верификация) + integration-smoke на PR CI
status: review         # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: "task/062-ops-tests-mypy-debts"
tags: [debt, ci, tests, mypy, ops]
---

# TASK-062 — Долги TASK-051: ops-тесты + showcase mypy + защита от рецидива в PR CI

> Закрыть известные долги TASK-051. Факт на baseline: оба долга УЖЕ исправлены PR #70
> (`e9070d3`) — остаточная работа = верификация на текущем main + закрытие процессной
> дыры, из-за которой долг вообще возник (integration-тесты не гоняются на PR).

## Context

Долги зафиксированы после TASK-051 (money dashboard, PR #65): (a) 6 интеграционных
ops-тестов падали на main — ходили на до-версионные маршруты без `/v1`-префикса
(TASK-030 ввёл `v1_router` с `_API_VERSION_PREFIX = "/v1"` —
`backend/src/api/main.py:78`, монтаж `backend/src/api/main.py:264`,
ops-роутер `backend/src/api/main.py:357`); (b) модуль `backend/src/showcase/` не был
покрыт mypy (отсутствовал в `[tool.mypy] packages`).

**Ключевой механизм возникновения долга:** интеграционная сюита гоняется ТОЛЬКО на
push в main (`.github/workflows/main-integration.yml`), а PR CI = `ci-fast` = unit-only
(`.github/workflows/pr-checks.yml:42-46`, `make ci-fast` — `Makefile:222`). Дрейф
маршрута/контракта проходит PR зелёным и краснеет уже на main.

## Goal

Подтверждено фактами: 6 ops-тестов зелёные на main, mypy по showcase чистый; PR CI
получает лёгкий integration-smoke (контрактные тесты маршрутов), чтобы этот класс
долга больше не мог попасть в main незамеченным. DoD = AC.

## Discussion
<!-- durable record; верификация выполнена на этапе планирования -->
- Q: Долги (a) и (b) всё ещё открыты на baseline `c390c4c`? → A: НЕТ → Decision:
  **оба долга уже закрыты PR #70** (`e9070d3` «fix(tests): /v1 paths in ops-metrics
  integration tests + showcase mypy coverage»). Проверено на плане:
  тесты ходят на `/v1/...` (`backend/tests/integration/test_ops_business_metrics.py:83,90,178,186,203,220,309,361`);
  `showcase` присутствует в `[tool.mypy] packages` (`backend/pyproject.toml:98`);
  `uv run mypy src/showcase --no-error-summary` на baseline — пусто (0 ошибок);
  последний прогон `main-integration` (run 27353800476): job «Backend integration
  tests» = **success**. Красный там только E2E (CSRF/Origin — параллельная работа
  #82, НЕ наш scope).
- Q: Что тогда остаётся в задаче? → A: процессная дыра → Decision: задача
  переформулируется в (1) **формальную верификацию** долгов прогоном на стенде
  (G2-доказательство, фиксируем в Details) и (2) **integration-smoke на PR CI** —
  минимальный набор контрактных тестов против живого Postgres в service-контейнерах
  (паттерн уже есть в `main-integration.yml:24-44`), чтобы route/contract-дрейф
  ловился ДО merge. Это standing process note из памяти проекта.
- Q: Гонять на PR всю `-m integration` сюиту? → A: нет → Decision: только smoke-набор
  «контракт маршрутов»: `tests/integration/test_api_versioning.py` +
  `tests/integration/test_ops_business_metrics.py` (детекторы префикс-дрейфа —
  именно их класс падал). Полная сюита остаётся на main-integration (время PR CI
  не раздуваем; полнота — на push в main, как и было).
- Q: Нужен ли отдельный Make-таргет? → A: да → Decision: `make test-integration-smoke`
  (CONVENTIONS: make — единая точка входа, не raw pytest в workflow).

## Scope

- **Touch ONLY:**
  - `.github/workflows/pr-checks.yml` — новый job `integration-smoke`:
    service-контейнеры postgres (`pgvector/pgvector:pg16`) + redis (slim-копия блока
    из `main-integration.yml:24-44`, те же env `POSTGRES_*`/`REDIS_URL`/`JWT_SECRET: ci`),
    шаги uv sync → `make test-integration-smoke`.
  - `Makefile` — таргет `test-integration-smoke` рядом с `test-integration`
    (`Makefile:208-209`): `$(UV) pytest -m integration tests/integration/test_api_versioning.py tests/integration/test_ops_business_metrics.py`.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `backend/tests/integration/test_ops_business_metrics.py` (уже на
  `/v1`), `backend/pyproject.toml` `[tool.mypy]` (showcase уже покрыт),
  `backend/src/showcase/**`, `.github/workflows/main-integration.yml` (полная сюита
  и e2e — как есть), e2e/CSRF-красноту main-integration (параллельный цикл #82),
  `_bmad/**`, `.claude/**`.
- **Blast radius:** только CI-конфигурация. Время PR CI +~2-3 мин (2 файла
  integration-тестов + подъём service-контейнеров). Кода приложения diff не касается.

## Acceptance Criteria

- [x] **AC1 — долг (a) подтверждён закрытым.** Given baseline `c390c4c` и живой
  Postgres When `uv run pytest -m integration tests/integration/test_ops_business_metrics.py`
  Then все тесты (auth-matrix 401/403/200, seeded numbers, funnel) зелёные —
  вывод прогона зафиксирован в Details.
- [x] **AC2 — долг (b) подтверждён закрытым.** Given baseline When
  `make typecheck` (mypy strict, `showcase` входит в packages — `pyproject.toml:98`)
  Then 0 ошибок по `src/showcase/`.
- [x] **AC3 — smoke ловит дрейф.** Given ветка, где ops-роут уезжает из-под `/v1`
  (локальная проверка-симуляция: временно снять `v1_router.include_router(ops_business_router)`)
  When `make test-integration-smoke` Then прогон красный; после отката — зелёный.
- [x] **AC4 — PR CI расширен.** Given открытый PR When отрабатывает `pr-checks`
  Then job `integration-smoke` присутствует, зелёный, и обязателен наравне с
  остальными jobs (без изменения их состава).

## Plan

1. `Makefile` — добавить `test-integration-smoke` (RED не нужен — таргет проверяется
   запуском; контрактные тесты уже существуют).
2. `.github/workflows/pr-checks.yml` — job `integration-smoke` с service-контейнерами
   (копия-минимум из `main-integration.yml`, без e2e-части).
3. Верификация AC1/AC2 на стенде: поднять Postgres (socat-форвард 15432 либо
   service-контейнер), прогнать smoke + mypy; вывод — в Details.
4. AC3: негативная проверка (симуляция дрейфа) локально, откат.
5. Ship: PR; убедиться, что новый job отработал на самом этом PR (self-test).

## Invariants

- Состав и поведение существующих CI-jobs (`ci-fast`, coverage, frontend, drift)
  не меняются — smoke строго аддитивен.
- Никакого кода приложения/тестов в диффе (долги (a)/(b) уже закрыты — не «чинить
  починенное»).
- Секреты в workflow — только фиктивные CI-значения (`JWT_SECRET: ci`, как в
  `main-integration.yml`); реальных секретов в PR CI нет.

## Edge cases

- Хост-машина без `make up` (исчерпание bridge-подсетей) → верификацию AC1 гонять
  через socat-форвард `tp-pg-fwd:15432` (известный обход) либо положиться на
  GitHub service-контейнеры самого smoke-job.
- Параллельный красный E2E на main (CSRF #82) → НЕ блокер этой задачи; main-required
  check для merge — pr-checks, не main-integration.
- Flaky integration-тест в smoke-наборе заблокирует все PR → набор из двух файлов
  выбран как детерминированный (auth-matrix + версионирование, без Celery/времени);
  если флак появится — исключить файл из smoke, не из сюиты.

## Test plan

- integration (существующие, прогон): `test_ops_business_metrics.py` — 6+ тестов,
  `test_api_versioning.py`.
- typecheck: `make typecheck` (mypy strict, showcase включён).
- CI: self-test нового job на ship-PR; негативная симуляция дрейфа (AC3) — локально.
- security: не требуется (нет auth/input/secrets поверхностей — только CI-конфиг);
  skip подтвердить на review.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 7
baseline_commit: "c390c4c"
branch: "task/062-ops-tests-mypy-debts"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial) — APPROVE, 0 CRITICAL/HIGH/MEDIUM
- [x] 5.5 security — SKIP подтверждён review: дифф = CI-конфиг, фиктивные ci-секреты
- [x] 6 ship (confirm plan done → PR(s))
- [x] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11: на этапе плана выяснено, что заявленные долги (a) 6 ops-тестов
и (b) showcase mypy уже закрыты PR #70 `e9070d3` — задача честно сужена до
верификации + закрытия корневой причины: PR CI не гоняет integration, дрейф
контракта виден только на main. Smoke из 2 контрактных файлов — минимальный дифф.)

(do+verify 2026-06-11, ветка task/062, от main=5fc442c):
- do: `Makefile` — таргет `test-integration-smoke` (+ .PHONY); `pr-checks.yml` —
  job `integration-smoke` (pgvector:pg16 + redis:7 service-контейнеры, env-блок
  идентичен `main-integration.yml`, фиктивные CI-секреты `JWT_SECRET: ci` и т.п.).
- AC1 ✓: хост без `make up` (bridge-подсети исчерпаны), socat tp-pg-fwd отсутствовал →
  одноразовый контейнер `tp-pg-task062` (pgvector/pgvector:pg16, default bridge,
  localhost:15432, user/pass/db=trendpulse). `make test-integration-smoke` →
  **19 passed** за 21.5s (test_ops_business_metrics: auth-matrix 401/403/200,
  no-per-user-identifiers, seeded MRR/планы/avg-check, funnel; + test_api_versioning).
- AC2 ✓: `make typecheck` → «Success: no issues found in 167 source files»
  (showcase в `[tool.mypy] packages`, pyproject.toml:98).
- AC3 ✓: закомментирован `v1_router.include_router(ops_business_router)`
  (api/main.py:357) → `make test-integration-smoke` → **6 failed, 13 passed**,
  make exit≠0; после `git checkout` отката — снова **19 passed**.
- YAML pr-checks.yml валиден, jobs: backend, integration-smoke, openapi-contract,
  frontend, landing, templates, dep-scan (существующие не тронуты — инвариант).
- AC4 ✓: PR #86 — job «Backend integration smoke (route contracts)» присутствует и
  pass за 50s (run 27360865558); все 7 jobs pr-checks зелёные, существующие не
  изменены. Required-статус в branch protection (если required-набор задан явным
  списком) добавляет owner.
