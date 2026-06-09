---
id: TASK-034
title: Postgres backups — ежедневный дамп в object storage + проверка восстановления
status: planned             # planned → in-progress → review → done
owner: infra
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e0, infra, backups, pain-p8, pain-p4]
---

# TASK-034 — Postgres backups + restore-check (Epic E0)

> Закрыть P8/P4 из [pain-points](../architecture/pain-points.md): ежедневный `pg_dump` в
> **Hetzner Object Storage** (S3-совместимый; бакет создаёт [TASK-056](./task-056-hetzner-object-storage-infra.md))
> + регулярная проверка, что дамп реально восстанавливается. «Бэкап, который не проверяли — не бэкап».
> **Deps: TASK-056 (бакет + S3_-env).**

## Context

Весь стек живёт на одном VPS; постоянных бэкапов БД нет — один инцидент = потеря пользователей/подписок/истории.
Инфраструктура: TASK-056 создаёт Hetzner-бакет `trendpulse-backups` (versioning + lifecycle-правило
`expire-backups`: объекты под префиксом `postgres/` живут 30 дней) и прокидывает env через Ansible:
`S3_ENDPOINT`/`S3_REGION`/`S3_BUCKET` (deploy.env) + `S3_ACCESS_KEY`/`S3_SECRET_KEY` (sensitive.env, vault).
Postgres: сервис `postgres` в `development/compose/postgres.yml` (volume `postgres_data`, сеть `postgres_net`,
без публикации портов). Управление — только через root `Makefile` (CONVENTIONS).

## Goal

Ежедневный автоматический дамп Postgres уезжает в private-bucket; `make backup` делает то же руками;
`make backup-restore-check` скачивает последний дамп, поднимает одноразовый чистый Postgres-контейнер,
восстанавливает и проверяет (минимум: `alembic_version` совпадает, count(users) >= 0 без ошибок);
runbook записан. Секреты — только через env из Ansible. DoD = Acceptance Criteria.

## Discussion
<!-- автономные решения при планировании (user offline); пересмотр дёшев -->
- Q: Чем гнать дамп и аплоад — backend-код или инфра-скрипт? → A: инфра → Decision: shell-скрипт +
  one-shot compose-сервис на образе `${PGVECTOR_IMAGE}` (в нём есть `pg_dump`), аплоад через S3-совместимый
  CLI-контейнер (rclone/официальный aws-cli образ, версия в `version.env`). Backend-кода НЕ касаемся —
  Beat-задача не годится: pg_dump-бинаря в app-образе нет, и бэкап не должен зависеть от живости Celery.
- Q: Чем триггерить ежедневно? → A: cron на хосте → Decision: Ansible-роль добавляет cron-запись,
  вызывающую `make backup` (или прямой скрипт) раз в сутки; интервал/время — переменная роли.
- Q: Формат дампа? → Decision: `pg_dump -Fc` (custom, сжатый, restore через `pg_restore`); имя/путь
  `postgres/trendpulse-YYYYMMDD-HHMMSS.dump` — префикс `postgres/` обязателен: на него навешано
  lifecycle-правило бакета.
- Q: Ретенция? → Decision: **на стороне бакета** (lifecycle `expire-backups` 30d из TASK-056) — скрипт
  старые дампы НЕ чистит (упрощение; одна ответственность меньше).
- Q: Restore-check автоматом или руками? → Decision: цель `make backup-restore-check` (запускается
  руками/раз в месяц по календарю ops; полная автоматизация — не сейчас). Runbook — в этом же task-доке/Details.
- Q: Откуда S3-доступ? → Decision: env из TASK-056 (`S3_ENDPOINT`/`S3_REGION`/`S3_BUCKET`/`S3_ACCESS_KEY`/
  `S3_SECRET_KEY` через Ansible) — эта задача env-ключи НЕ заводит, только потребляет.

## Scope
- **Touch ONLY:**
  - `development/scripts/pg_backup.sh` — **новый**: pg_dump -Fc → загрузка в `s3://$S3_BUCKET/postgres/` (ретенцию делает lifecycle бакета).
  - `development/scripts/pg_restore_check.sh` — **новый**: скачать последний дамп → одноразовый postgres-контейнер → `pg_restore` → smoke-проверки → отчёт.
  - `development/compose/pg-backup.yml` — **новый**: one-shot сервисы `pg_backup` (образ `${PGVECTOR_IMAGE}`, сеть `postgres_net`) и `backup_uploader` (S3 CLI, версия в `version.env`).
  - `development/version.env` — пин версии S3-CLI-образа.
  - `Makefile` (root) — цели `backup`, `backup-restore-check`.
  - Ansible: cron-задача (роль/таска) на ежедневный запуск (env-шаблоны S3_* уже сделаны TASK-056 — не дублировать).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `backend/**` (никакого кода приложения), `development/compose/postgres.yml` (сам сервис БД не меняем), сетевую сегментацию.
- **Blast radius:** новые one-shot контейнеры в `postgres_net`; нагрузка pg_dump раз в сутки; секреты — два новых ключа в Ansible. Приложение не затронуто.

## Acceptance Criteria
- [ ] **AC1 — дамп уезжает в bucket.** Given настроенные S3_-env (из TASK-056), When `make backup`, Then в бакете появляется `postgres/trendpulse-<ts>.dump` (custom-format), локальный временный файл удалён.
- [ ] **AC2 — restore-check проходит.** Given хотя бы один дамп в бакете, When `make backup-restore-check`, Then одноразовый Postgres поднимается, `pg_restore` отрабатывает без ошибок, `alembic_version` присутствует и непуста, контейнер и временные файлы удалены.
- [ ] **AC3 — cron на проде.** Given прогон Ansible, When инспекция хоста, Then cron-запись существует и зовёт бэкап-скрипт ежедневно; ключи попали в `sensitive.env` только через Ansible (TASK-056).
- [ ] **AC4 — секреты не светятся.** Given скрипты/композы, When инспекция/логи, Then ключи только из env (без хардкода, не печатаются в stdout); bucket private (Hetzner default, TASK-056).
- [ ] **AC5 — runbook.** Given `Details` этого дока, When читает ops, Then шаги «восстановить прод из дампа» описаны и однажды пройдены руками (зафиксировать дату прогона).

## Plan
1. `development/scripts/pg_backup.sh` + `pg_restore_check.sh` (set -euo pipefail; конфиг из env; ретенция N=14 константой).
2. `development/compose/pg-backup.yml` + пин S3-CLI в `version.env`.
3. Root `Makefile`: `backup`, `backup-restore-check` (compose run --rm).
4. Ansible: cron-таска ежедневного запуска (env уже из TASK-056).
5. Прогон: `make backup` против dev-стека → AC1; `make backup-restore-check` → AC2; runbook в Details (G2).

## Invariants
- Бэкап не зависит от живости приложения/Celery — только от Postgres-контейнера и cron.
- Postgres-порты наружу по-прежнему не публикуются; дамп идёт изнутри `postgres_net`.
- Секреты — только Ansible → `sensitive.env` (ADR-005); в git — ни ключей, ни endpoint-учёток.
- Restore-check никогда не касается боевой БД (только одноразовый контейнер).

## Edge cases
- Bucket недоступен/ключи неверны → скрипт падает ненулевым кодом, cron-MAILTO/лог; дамп не удаляется до успешного аплоада.
- Дамп большой/диск тесный → pg_dump стримится в файл во временный каталог с проверкой свободного места (df-guard в скрипте).
- Параллельный запуск (cron + ручной) → lock-файл (flock) в скрипте.
- Пустой бакет при restore-check → понятная ошибка «нет дампов», ненулевой код.

## Test plan
- **behavioral (G2):** dev-стек: `make backup` → объект в бакете (или MinIO/локальный stub при оффлайне — но финальная проверка против реального Spaces); `make backup-restore-check` → зелёный отчёт.
- **негатив:** битые ключи → ненулевой код, секреты не в выводе.
- unit-тестов нет (инфра-скрипты); shellcheck на оба скрипта в CI (если hook есть — иначе локально).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (секреты/доступ к данным — применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — пересмотр 2026-06-09: object storage — **Hetzner**, не DO (решение owner'а); бакет/env создаёт
TASK-056 (порт terraform по паттерну postbridge, minio-провайдер) — выполнять ПОСЛЕ неё. Ретенция дампов —
lifecycle-правило бакета (префикс `postgres/`, 30d), скрипт не чистит. pg_dump доступен в `${PGVECTOR_IMAGE}`;
целей backup в Makefile нет. Самая приоритетная задача волны E0 по pain-points: «дёшево, и без этого один
инцидент обнуляет всё остальное».)
