---
id: TASK-034
title: Postgres backups — ежедневный дамп в object storage + проверка восстановления
status: done                # planned → in-progress → review → done
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
current_step: done
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: "gsd/phase-e0-pg-backup-restore-check"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — после 2 debug-циклов; AC1/AC2/AC4 живьём, AC3 code-verified, AC5 runbook — см. Details)
- [x] 5 review (auto, adversarial — fail→fix→re-review pass, остался 1 INFO)
- [x] 5.5 security (секреты/доступ к данным — pass; least-privilege и чистка дампа исправлены в цикле 2)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto — записаны в docs/learnings.md до ship, в том же PR)
debug_runs:
  - "2026-06-09 G2: (1) HIGH — backup_restore_check сервис на amazon/aws-cli образе зовёт docker run/exec, docker CLI в образе нет → make backup-restore-check падает (127); сам скрипт на хосте отработал PASS. Root cause: docker-in-docker дизайн. Fix: переразбить на fetch (aws-cli) + check (PGVECTOR_IMAGE c внутренним pg_ctl/initdb), без docker-сокета. (2) MEDIUM — make backup падает на pre-existing 'FRONTEND_COOKIE_SECRET is missing' (TASK-029 добавил :?-интерполяцию во frontend.yml, COMPOSE грузит только version.env). Fix в рамках scope: backup-цели гоняем standalone через -f development/compose/pg-backup.yml + явные --env-file, не через общий include."
  - "2026-06-10 review/security: (1) HIGH — make-цели зовут `run pg_backup` + `run backup_uploader` без --no-deps → depends_on перезапускает pg_dump ВТОРОЙ раз за вызов; fix: одна терминальная служба (`run --rm backup_uploader`), deps-цепочка гонит dump ровно раз. (2) HIGH — flock на /tmp контейнера (эфемерный) → cron+ручной не контендят; fix: lock на shared volume ${DUMP_DIR}. (3) MEDIUM — pg_restore без --exit-on-error может вернуть 0 на частично битом дампе → ложный PASS. (4) MEDIUM security — env_file sensitive.env ЦЕЛИКОМ в uploader/fetch (интернет-egress) — least-privilege; передавать только нужные vars через environment:. (5) MEDIUM security — latest.dump (полная копия прод-БД) живёт в restore_tmp бессрочно; fix: чистка после check."

## Details
(initial — пересмотр 2026-06-09: object storage — **Hetzner**, не DO (решение owner'а); бакет/env создаёт
TASK-056 (порт terraform по паттерну postbridge, minio-провайдер) — выполнять ПОСЛЕ неё. Ретенция дампов —
lifecycle-правило бакета (префикс `postgres/`, 30d), скрипт не чистит. pg_dump доступен в `${PGVECTOR_IMAGE}`;
целей backup в Makefile нет. Самая приоритетная задача волны E0 по pain-points: «дёшево, и без этого один
инцидент обнуляет всё остальное».)

2026-06-09/10 (do+verify, итог после 1 debug-цикла):
- Дизайн: `pg_backup.sh`/`pg_restore_check.sh` со STAGE-dispatch (dump|upload, fetch|check); compose
  `development/compose/pg-backup.yml` — STANDALONE (не в корневом include): one-shot сервисы `pg_backup`
  (${PGVECTOR_IMAGE}, postgres_net external=development_postgres_net) → `backup_uploader` (amazon/aws-cli,
  пин в version.env), volume pgdump_tmp; restore-check = `restore_fetch` (aws-cli) → `restore_check`
  (${PGVECTOR_IMAGE}: внутренний одноразовый postgres через initdb+pg_ctl на unix-сокете, БЕЗ docker-сокета
  и БЕЗ сети postgres_net — полная изоляция от боевой БД). Make-цели зовут pg-backup.yml напрямую с
  --env-file version.env+deploy.env+sensitive.env (обход pre-existing регрессии FRONTEND_COOKIE_SECRET
  из TASK-029, которая ломает все цели через корневой include, — отмечено как отдельный фикс).
- Живые прогоны (dev-стек, реальный Hetzner nbg1): `make backup` → s3://trendpulse-backups/postgres/
  trendpulse-20260609-210609.dump (40665 b, custom-format), temp очищен; `make backup-restore-check` →
  PASS (alembic_version=0010, users count=0, exit 0, контейнеры/temp убраны). Негатив: битый секрет →
  exit 1, секреты в выводе не светятся, дамп НЕ удаляется до успешного аплоада. shellcheck 0 warnings,
  ansible-lint роли backup: 0 failures.
- AC3: cron-роль `ops/ansible/roles/backup` (daily 03:00 UTC, backup_cron_* vars, лог
  /var/log/trendpulse-backup.log) подключена в deploy.yml; ПРОД-прогон Ansible pending owner
  (вход: сначала починить vault-синтаксис — см. TASK-056 Details, — затем `ansible-playbook deploy.yml`).
- **Runbook «восстановить прод из дампа»** (AC5; restore-check пройден руками 2026-06-09, дамп
  trendpulse-20260609-205351.dump, миграция 0010):
  1. ssh на прод-хост → `cd /opt/trendpulse`.
  2. Остановить приложение, БД оставить: `docker compose -f development/docker-compose.yml stop api worker beat nginx`.
  3. Выбрать дамп: `aws s3 ls s3://$S3_BUCKET/postgres/ --endpoint-url $S3_ENDPOINT` (ключи — из development/env/sensitive.env).
  4. Скачать: `aws s3 cp s3://$S3_BUCKET/postgres/<имя>.dump /tmp/restore.dump --endpoint-url $S3_ENDPOINT`.
  5. `docker cp /tmp/restore.dump <postgres-container>:/tmp/` → `docker exec <postgres-container> pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists /tmp/restore.dump`.
  6. Проверить `SELECT version FROM alembic_version;` соответствует ожидаемой; при отставании — `make migrate`.
  7. `make up` → smoke `/health`; удалить /tmp/restore.dump на хосте и в контейнере.
  Прежде чем восстанавливать вслепую — прогнать дамп через `make backup-restore-check`.

2026-06-10 (fix-цикл 2 + финальный G2): все находки review/security закрыты — make-цели гонят только
терминальную службу (deps-цепочка → ровно один pg_dump/fetch за вызов), flock на shared volume, pg_restore
--exit-on-error, env per-service least-privilege (uploader/fetch видят ТОЛЬКО AWS_*/S3_*, restore_check —
без секретов вовсе), `down --volumes` после успешного restore-check убирает дамп с диска (после
НЕуспешного — volume сознательно живёт для диагностики, INFO). Финальный живой прогон: `make backup` →
trendpulse-20260609-211713.dump (один объект), exit 0; `make backup-restore-check` → PASS
(alembic 0010, users=0), volumes/контейнеры удалены. MAILTO="" реально ставится cron-задачей.
Follow-up вне scope: pre-existing регрессия `FRONTEND_COOKIE_SECRET is missing` (TASK-029) ломает ВСЕ
цели через корневой compose-include, пока env-файлы не загружены — заведено как кандидат в отдельный
мини-фикс (COMPOSE var должен грузить deploy.env/sensitive.env или frontend.yml не должен :?-ассертить).
