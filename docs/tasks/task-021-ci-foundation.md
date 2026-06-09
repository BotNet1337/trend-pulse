---
id: TASK-021
title: CI foundation — корневые workflows + изоляция test-БД + dep-scan + coverage-gate
status: planned          # planned → in-progress → review → done
owner: ops
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-021-ci-foundation"
tags: [epic-d, ci, ops, testing]
---

# TASK-021 — CI foundation (Epic D)

> Поднять реально работающий CI. Сейчас корневых `.github/workflows/` НЕТ — workflow лежат в `frontend/.github/workflows/{build,pr-checks}.yml` и `landing/.github/workflows/{build,pr-checks}.yml`, но GitHub их НЕ запускает (workflow распознаются только из `.github/workflows/` в КОРНЕ репозитория). Создать корневые workflow: на PR — backend (ruff+mypy+`pytest -m 'not integration'` + coverage `--cov-fail-under=80`), frontend (lint+vitest+tsc), landing (lint+build), dep-scan (pip-audit/safety + npm audit); integration+e2e — на push в main (поднимают стек/БД). Починить `conftest.py` (не чистит `alembic_version` → ломает `make up` на общем postgres-volume). Добавить coverage-gate в pytest addopts + `make test-cov`. pre-commit `make ci` не должен виснуть на integration.

## Context

Корневых workflow нет: `find` показывает только `apps/trendPulse/landing/.github` и `apps/trendPulse/frontend/.github` (по `build.yml`+`pr-checks.yml` в каждом). GitHub Actions исполняет YAML только из `<repo-root>/.github/workflows/` — вложенные в подпапки игнорируются, т.е. CI де-факто не гоняется. **Сначала определить git-root** (поиск `.git` вверх от `apps/trendPulse` дал пусто в песочнице — executor должен `git rev-parse --show-toplevel`): workflow кладём в `<git-root>/.github/workflows/`. Если монорепо-корень = `apps/trendPulse` сам по себе, то `apps/trendPulse/.github/workflows/`.

`make` — единая точка: `ci`/`ci-fast`/`test`/`test-integration`/`build`/`up` (Makefile цели подтверждены). `backend/pyproject.toml` `addopts = "--strict-markers -ra"`, есть `markers` (включая `integration`); coverage-gate отсутствует. pre-commit зовёт `make ci`, который включает integration → виснет без БД.

`backend/tests/conftest.py`: session-fixture делает `Base.metadata.drop_all`/`create_all` и per-test «truncates all tables on teardown», НО `alembic_version` НЕ управляется (она вне `Base.metadata`, её ставит `migration_runner`). На общем postgres-volume остаточная/отсутствующая `alembic_version` ломает последующий `make up` (миграции думают, что уже на head, либо конфликт схемы). Нужно: чистить `alembic_version` в teardown (`DELETE FROM alembic_version`/`DROP TABLE IF EXISTS alembic_version`) ЛИБО изолированная test-БД (отдельная database/schema), чтобы integration не отравлял dev-volume.

## Goal

После задачи: на каждый PR в GitHub зелёный workflow гоняет backend (ruff+mypy+`pytest -m 'not integration'` с `--cov-fail-under=80`), frontend (lint+vitest+tsc), landing (lint+build), dep-scan (pip-audit/safety для backend, npm audit для front+landing). integration+e2e гоняются на push в main (поднимают стек/БД через `make up`/`test-integration`). `conftest.py` больше не ломает `make up` (alembic_version чистится ИЛИ изолированная test-БД). Coverage-gate (`--cov-fail-under=80`) в pytest addopts; `make test-cov` есть. pre-commit/`make ci` не виснет на integration (использует `ci-fast` или гардит integration за наличие БД). Идеи существующих frontend/landing workflow перенесены в корень (не продублированы в подпапках).

## Discussion
<!-- durable record of clarifications; обратимы. -->
- Q: Куда класть workflow? → A: GitHub читает только корень → Decision: `<git-root>/.github/workflows/`. Executor определяет git-root через `git rev-parse --show-toplevel` (в репо может быть выше `apps/trendPulse`). Команды путей в job — с учётом `apps/trendPulse`-префикса (`working-directory`/`defaults.run`).
- Q: Что на PR vs на main? → A: PR должен быть быстрым и без внешних сервисов → Decision: **PR** — lint/type/unit (`-m 'not integration'`) + coverage + dep-scan (без БД/стека). **push в main** — integration + e2e (поднимают postgres/redis/стек через `make up`/`make test-integration`/Playwright).
- Q: Структура CI — `make` или сырые команды? → A: `make` — единая точка → Decision: job зовут `make` цели (ruff/mypy через `make lint`/`make typecheck`, unit через `make test`/новую `test-cov`, фронт через свои скрипты). Минимум дублирования логики в YAML.
- Q: conftest — чистить alembic_version или отдельная БД? → A: оба валидны, выбрать минимально-инвазивный → Decision: **по умолчанию** — в session-teardown `DROP TABLE IF EXISTS alembic_version` (и/или `DELETE FROM`), плюс по возможности целиться integration в отдельную test-database (env-override `POSTGRES_DB`), чтобы не делить volume с dev. Решение исполнителя по объёму, но AC: `make up` после `make test-integration` не падает.
- Q: coverage-gate где? → A: в pytest addopts → Decision: добавить `--cov=src --cov-fail-under=80` в `backend/pyproject.toml` addopts (или в `make test-cov`); `make test-cov` — отдельная цель, чтобы `ci-fast` оставался быстрым.
- Q: pre-commit виснет на integration? → A: `make ci` тянет integration → Decision: pre-commit зовёт `ci-fast` (или `ci` гардит integration по доступности БД); pre-commit не должен требовать поднятого postgres.
- Q: dep-scan чем? → A: backend Python + npm → Decision: `pip-audit` (или `safety`) для backend deps, `npm audit` (или `--audit-level`) для `frontend`+`landing`. Падать на high/critical (порог — named, не молча).

## Scope
> CI-инфраструктура (корневые workflow), conftest-фикс, pytest/Makefile coverage+гард. Прод-код приложений НЕ трогаем (кроме conftest и конфигов тестов).

- **Touch ONLY (создать/изменить):**
  - `<git-root>/.github/workflows/pr-checks.yml` — **новый**: jobs backend (ruff+mypy+`pytest -m 'not integration'` --cov-fail-under=80), frontend (lint+vitest+tsc), landing (lint+build), dep-scan (pip-audit/safety + npm audit). Триггер `pull_request`.
  - `<git-root>/.github/workflows/main-integration.yml` — **новый**: integration (`make test-integration` + поднятый postgres/redis) + e2e (Playwright через `make up`/nginx). Триггер `push` в `main`.
  - `backend/tests/conftest.py` — teardown чистит `alembic_version` (`DROP TABLE IF EXISTS`/`DELETE FROM`) и/или изолированная test-database; чтобы не ломать `make up`.
  - `backend/pyproject.toml` — addopts `--cov`/`--cov-fail-under=80` (или в новой цели).
  - `Makefile` — `test-cov` (unit+coverage gate); гард integration в `ci`/`ci-fast` так, чтобы pre-commit не виснул.
  - `.pre-commit-config.yaml` (если есть; иначе hook-конфиг) — pre-commit зовёт `ci-fast`, не `ci` с integration.
  - `frontend/.github/workflows/**`, `landing/.github/workflows/**` — **перенести идеи в корень** (удалить/нейтрализовать вложенные, чтобы не плодить неработающие дубликаты).
  - `docs/tasks/tasks-index.md` — на ship (оркестратор).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, прод-код `backend/src/**`/`frontend/src/**`/`landing/src/**` (только тест-конфиги и conftest), бизнес-логика, миграции (чистка `alembic_version` — операция teardown, не изменение схемы).
- **Blast radius:** впервые включается реальный CI на PR (gate на merge); conftest-фикс меняет жизненный цикл test-БД (устраняет порчу dev-volume); coverage-gate может валить PR при <80% (ввести аккуратно); dep-scan может падать на существующих уязвимостях зависимостей (зафиксировать порог/baseline). Перенос workflow меняет местоположение CI-конфигов.

## Acceptance Criteria
- [ ] **AC1 — PR-workflow зелёный и реально запускается (failing-test anchor).** Given корневой `pr-checks.yml`, When открыт PR, Then GitHub запускает jobs backend/frontend/landing/dep-scan и они зелёные; вложенные frontend/landing workflow больше не нужны/нейтрализованы. (Проверка — workflow-файл валиден `actionlint`/локальный прогон job-команд; реальный запуск — на push ветки.)
- [ ] **AC2 — conftest не ломает `make up`.** Given прогон `make test-integration` (drop/create + alembic_version teardown), When затем `make up`, Then миграции применяются чисто, стек поднимается (нет конфликта `alembic_version`/схемы на общем volume). RED-якорь: тест/прогон, воспроизводящий старую поломку.
- [ ] **AC3 — coverage-gate активен.** Given `--cov-fail-under=80` в addopts/`make test-cov`, When unit-прогон с покрытием <80%, Then fail; при ≥80% — pass; `make test-cov` существует и используется в PR-job.
- [ ] **AC4 — dep-scan гоняется.** Given dep-scan job, When PR, Then pip-audit/safety (backend) и npm audit (front+landing) выполняются; на high/critical — fail по заданному порогу (не молча).
- [ ] **AC5 — pre-commit/ci не виснет на integration.** Given pre-commit hook, When коммит без поднятой БД, Then `ci-fast`/гард отрабатывает без зависания на integration; `make ci` (полный) по-прежнему доступен вручную/в main.
- [ ] **AC6 — integration+e2e на main.** Given `main-integration.yml`, When push в main, Then поднимается postgres/redis/стек, прогоняются `make test-integration` + Playwright e2e за nginx; артефакты on-failure сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-021-ci-foundation`; `git rev-parse --show-toplevel` → git-root для путей workflow.
1. **RED:** воспроизвести поломку — `make test-integration` затем `make up` падает на `alembic_version` (анкор AC2). Зафиксировать.
2. `conftest.py` — teardown `DROP TABLE IF EXISTS alembic_version`/`DELETE FROM` (+ опц. изолированная test-database через env). Перепрогон: `make test-integration` → `make up` чисто (AC2 GREEN).
3. `backend/pyproject.toml` addopts `--cov --cov-fail-under=80`; `make test-cov`; убедиться gate валит при <80% и проходит при ≥80% (AC3).
4. `make` — гард integration в `ci`/`ci-fast`; pre-commit конфиг → `ci-fast` (AC5).
5. Корневой `pr-checks.yml`: jobs backend (lint+type+unit+cov), frontend (lint+vitest+tsc), landing (lint+build), dep-scan (pip-audit/safety+npm audit); `working-directory: apps/trendPulse`. `actionlint`/локальный прогон команд (AC1, AC4).
6. Корневой `main-integration.yml`: integration+e2e на push main (стек/БД, Playwright за nginx) (AC6). Нейтрализовать вложенные frontend/landing workflow.
7. **G2:** запушить ветку → наблюдать реальный запуск PR-workflow зелёным; обновить `tasks-index.md` на ship.

## Invariants
- **Workflow только в корне репо** — GitHub исполняет `<git-root>/.github/workflows/`; вложенные подпапки не дублировать (они не запускаются).
- **PR быстрый, без внешних сервисов** — lint/type/unit/cov/dep-scan; integration/e2e (БД/стек) — только push в main.
- **`make` — единая точка** — jobs зовут `make` цели, минимум дублирования логики в YAML.
- **conftest не отравляет dev-volume** — `alembic_version` управляется в teardown и/или test-БД изолирована; `make up` после тестов всегда чист.
- **coverage ≥80%** — gate в addopts/`test-cov`; no magic — порог именован.
- **pre-commit не требует БД** — `ci-fast`/гард; integration не висит локально.
- **dep-scan порог явный** — fail на high/critical по заданному уровню, не молчаливый pass.

## Edge cases
- git-root выше `apps/trendPulse` (монорепо) → workflow в корне, `working-directory`/`defaults.run.working-directory: apps/trendPulse`; иначе пути не найдутся.
- `alembic_version` отсутствует (свежая БД) → `DROP TABLE IF EXISTS` идемпотентен, не падает.
- Общий postgres-volume у dev и тестов → изоляция через отдельную `POSTGRES_DB` для integration, чтобы teardown не сносил dev-данные.
- coverage <80% на старте → сначала измерить, не выставлять gate, ломающий весь PR без шанса (при необходимости — поэтапно/исключения для нерелевантных модулей).
- dep-scan падает на уже существующих CVE в lock-файлах → задать порог/временный allowlist с TODO, не блокировать намертво без видимости.
- npm audit для двух пакетов (frontend+landing) → отдельные шаги/`working-directory`, разные lock-файлы.
- Playwright e2e в CI требует поднятого стека за nginx → `main-integration.yml` ждёт healthcheck перед прогоном (как `make up` в task-013/016).

## Test plan
- **workflow lint:** `actionlint` на оба YAML; локальный прогон команд каждого job (backend/frontend/landing/dep-scan) через `make`/скрипты.
- **conftest regression:** последовательность `make test-integration` → `make up` (AC2) — раньше падала, теперь чисто; integration-набор зелёный.
- **coverage:** `make test-cov` — gate валит при искусственном падении покрытия, проходит при ≥80% (AC3).
- **dep-scan:** pip-audit/safety + npm audit прогоняются, реагируют на high/critical (AC4).
- **pre-commit:** коммит без БД не виснет (AC5).
- **runtime/behavioral (G2):** push ветки → реальный запуск PR-workflow зелёным в GitHub (AC1); push в main → integration+e2e (AC6).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-021-ci-foundation"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через nginx/стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по проверенным фактам: корневых `.github/workflows` нет, есть только `frontend/.github/workflows/{build,pr-checks}.yml` и `landing/.github/workflows/{build,pr-checks}.yml` (GitHub их не запускает); `make` цели `ci/ci-fast/test/test-integration/build/up` подтверждены; `backend/pyproject.toml` addopts `--strict-markers -ra` + `markers` (integration) без coverage-gate; `conftest.py` делает drop/create + per-test truncate, но не трогает `alembic_version` → ломает `make up` на общем volume. git-root в песочнице не нашёлся — executor определяет через `git rev-parse --show-toplevel`. deps: 001 (dev env/compose/make). locate+plan выполнены — executor стартует с «3 do».)
