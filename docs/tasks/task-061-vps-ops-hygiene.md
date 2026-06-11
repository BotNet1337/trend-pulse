---
id: TASK-061
title: Ops-гигиена VPS — лог-ротация, restore-check в cron, диск/память/бэкап-алерты, fail2ban
status: planned             # planned → in-progress → review → done
owner: infra
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [launch, ops, ansible, hygiene, cron, p4]
---

# TASK-061 — Ops-гигиена VPS (лог-ротация + restore-check cron + host-алерты + fail2ban)

> Аудит VPS-гигиены нашёл 4 гэпа, каждый из которых тихо убивает прод через недели:
> (a) docker-логи без ротации → диск заполняется json-file-логами; (b) restore-check
> существует только как ручной `make restore-check` — бэкап без проверки восстановления
> = вера, не бэкап; (c) диск >85% / память / упавший бэкап — никто не узнает до падения;
> (d) fail2ban ставится только через TF cloud-init — ansible-путь (`make deploy` на
> уже живом хосте) его не гарантирует. Всё чинится идемпотентными ansible-тасками,
> попадающими в существующий `make deploy` (site.yml = provision + deploy).

## Context

Provision: `ops/ansible/playbooks/provision.yml` — пакеты (стр. 43–52), docker engine
(63–69, `docker.io` только если не предустановлен), сервис (71–75), swarm init (80–91),
ufw 22/80/443 (101–123). **daemon.json не настраивается нигде** — docker пишет json-file
логи без лимита. Бэкап (TASK-034): `ops/ansible/roles/backup/tasks/main.yml:31-39` —
ежедневный cron `make -C release backup-now >> /var/log/trendpulse-backup.log 2>&1`
(03:00 UTC, defaults `roles/backup/defaults/main.yml:6-10`); лог растёт вечно, MAILTO=""
(лог — единственный аудит-след, но его никто не читает). `release/Makefile:203-210` —
`backup-now` и `restore-check` (скачивает последний дамп → throwaway PG → smoke,
PASS/FAIL по exit-коду) — restore-check ТОЛЬКО ручной. Self-alert механизм (TASK-035):
`backend/src/observability/pool_health.py:95-155` `notify_ops()` — httpx POST
`api.telegram.org/bot<token>/sendMessage`, no-op при пустых кредах, throttle per-reason;
креды `OPS_TELEGRAM_BOT_TOKEN`/`OPS_TELEGRAM_CHAT_ID` рендерятся env-ролью в
`/opt/trendpulse/release/env/sensitive.env` (`roles/env/templates/sensitive.env.j2:34-35`,
mode 0600). Для shell-алертов с хоста backend не нужен — тот же Bot API через curl,
креды source'ятся из уже лежащего на хосте sensitive.env. fail2ban: ставится TF
cloud-init'ом (`ops/terraform/modules/hetzner/server/cloud-init.yml.tftpl:22,36-37`),
но провижен через ansible (не-TF хост / drift) его не обеспечивает. Деплой-вход:
корневой `Makefile:181-188` `make deploy` → `ops/ansible/site.yml` (TASK-057).

## Goal

После задачи: docker-логи ротируются (json-file, max-size/max-file); backup-лог под
logrotate; `make -C release restore-check` гоняется cron'ом еженедельно; диск >85% /
память на пределе / упавший backup/restore-check → алерт в ops TG-чат (тот же бот, что
TASK-035); fail2ban активен на SSH. Все таски идемпотентны: повторный прогон
`make deploy` = 0 changed по этим таскам. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Куда класть docker log-ротацию? → A: daemon-уровень, не per-service → Decision:
  `/etc/docker/daemon.json` с `log-driver: json-file`, `max-size: 10m`, `max-file: 3` —
  таск в `provision.yml` (это host-setup, как ufw). Per-service `logging:` в compose
  не покрывает будущие контейнеры (restore-check, builds). Restart docker — только
  handler при изменении файла (см. Edge cases: рестарт ронят все контейнеры — окно).
- Q: daemon.json может уже существовать (cloud-init/ручные правки)? → A: проверено —
  ни TF cloud-init, ни ansible его не создают → Decision: пишем целиком через `copy`
  (идемпотентно по content-diff). Первым шагом do-стадии — `ls /etc/docker/daemon.json`
  на живом хосте; если файл есть с чужими ключами — merge руками в шаблон, зафиксировать
  в Details.
- Q: restore-check как часто и когда? → A: еженедельно, не пересекаясь с бэкапом →
  Decision: воскресенье 04:30 UTC (бэкап — ежедневно 03:00; restore-check тянет дамп
  и поднимает throwaway PG — тяжёлый, off-peak). Cron в той же backup-роли (она владеет
  cron+логом), вывод в тот же `/var/log/trendpulse-backup.log`.
- Q: Алертинг — через backend (notify_ops) или shell? → A: shell → Decision: cron-скрипт
  `/usr/local/bin/trendpulse-host-alert.sh` (ansible-шаблон): curl к Bot API, креды
  source из `/opt/trendpulse/release/env/sensitive.env` (root читает 0600-файл deploy'я).
  Backend-путь (notify_ops) требует живой app+Redis — host-алерт должен работать ИМЕННО
  когда app мёртв. Паттерн поведения копируем с notify_ops: пустые креды → silent no-op;
  throttle per-reason (state-файл `/var/lib/trendpulse/alerts/<reason>`, окно 6h —
  Redis на хост-уровне не тянем); send fail → не падать (cron не должен спамить MAILTO).
- Q: Пороги? → A: простые, в defaults роли → Decision: диск (df -P /) used% > 85;
  память: MemAvailable < 10% MemTotal. Проверка каждые 15 мин. Переопределяемо через
  group_vars (`host_alert_disk_pct: 85` и т.п.) — no magic literals в скрипте.
- Q: Алерт при упавшем бэкапе — как? → A: тем же скриптом → Decision: cron-строки
  backup/restore-check получают `|| /usr/local/bin/trendpulse-host-alert.sh send
  pg_backup_failed "..."` (отдельный reason на каждый job). Скрипт = единственный
  канал host→TG (один источник, как notify_ops для backend).
- Q: Куда кладём alert-скрипт — новая роль или backup-роль? → A: новая роль →
  Decision: роль `host_alerts` в `deploy.yml` ПОСЛЕ роли env (скрипту нужен отрендеренный
  sensitive.env) и ДО backup (cron-строки backup ссылаются на скрипт). backup-роль не
  раздуваем чужой ответственностью (диск/память — не про бэкап).
- Q: fail2ban — не дубль ли cloud-init? → A: дубль осознанный → Decision: идемпотентные
  таски (package present + service enabled/started) в `provision.yml`. На TF-хосте =
  0 changed (уже стоит), на любом другом — закрывает гэп. Кастомные jail'ы не пишем:
  дефолтный sshd-jail достаточен (22 открыт миру, ключи-only — task-057 §анализ).

## Scope
> **ops only.** Backend, release/Makefile, compose — НЕ трогаем. Owner-шагов нет
> (всё едет штатным `make deploy`); живые проверки — на проде после деплоя.

- **Touch ONLY:**
  - `ops/ansible/playbooks/provision.yml` — (1) таск `/etc/docker/daemon.json`
    (copy + handler restart docker, перед «Ensure Docker service is running», стр. 71);
    (2) таски fail2ban (package + service) рядом с ufw-секцией (стр. 101+).
  - `ops/ansible/roles/host_alerts/**` — **новая роль**: `defaults/main.yml` (пороги,
    интервалы, throttle), `templates/trendpulse-host-alert.sh.j2`, `tasks/main.yml`
    (директория state, скрипт 0750, cron каждые 15 мин).
  - `ops/ansible/playbooks/deploy.yml:45-53` — роль `host_alerts` между `env` и `backup`.
  - `ops/ansible/roles/backup/tasks/main.yml` — (1) logrotate-конфиг
    `/etc/logrotate.d/trendpulse-backup` (weekly, rotate 8, compress); (2) cron-строка
    backup: `|| trendpulse-host-alert.sh send pg_backup_failed`; (3) новый cron
    `trendpulse-pg-restore-check` (вс 04:30 UTC) с тем же fail-hook
    (reason `pg_restore_check_failed`).
  - `ops/ansible/roles/backup/defaults/main.yml` — `restore_check_cron_*` defaults.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `release/**` (Makefile/скрипты бэкапа работают — TASK-034),
  `backend/**` (notify_ops — backend-зона), `ops/terraform/**` (cloud-init не правим),
  роли `env`/`tls`, ufw-правила, vault-ключи (используем существующие
  `vault_ops_telegram_*` — только проверить заполненность).
- **Blast radius:** restart docker при ПЕРВОМ накате daemon.json = рестарт всех
  контейнеров узла (≈1–2 мин даунтайма — деплой-окно; swarm поднимает сервисы сам);
  cron-таблица root (+2 записи); 1 новый исполняемый файл на хосте. Стек/приложение
  не затронуты.

## Acceptance Criteria

- [ ] **AC1 — лог-ротация docker.** Given прод после деплоя When
  `docker info --format '{{.LoggingDriver}}'` + inspect любого контейнера Then
  json-file с max-size=10m/max-file=3; When контейнер пишет >30m логов Then старые
  сегменты удаляются (файлов ≤3).
- [ ] **AC2 — logrotate backup-лога.** Given `/etc/logrotate.d/trendpulse-backup`
  When `logrotate -d` (dry-run) Then конфиг валиден, лог попадает в weekly-ротацию.
- [ ] **AC3 — restore-check в cron.** Given воскресный тик (или ручной прогон
  cron-строки) When `make -C release restore-check` отрабатывает Then PASS пишется в
  `/var/log/trendpulse-backup.log`; When restore-check падает (exit≠0) Then в ops
  TG-чат приходит алерт `pg_restore_check_failed`.
- [ ] **AC4 — диск/память алерт.** Given порог временно снижен (стенд-эксперимент:
  `host_alert_disk_pct: 1`) When cron-тик Then алерт в ops-чат ≤15 мин, ровно один
  за throttle-окно (повторный тик молчит); When порог возвращён Then тишина.
- [ ] **AC5 — бэкап-алерт.** Given backup-cron падает (эксперимент: временно битый
  S3-ключ ИЛИ прямой вызов fail-ветки `... false || trendpulse-host-alert.sh send
  pg_backup_failed "test"`) Then алерт приходит; лог содержит причину.
- [ ] **AC6 — fail2ban.** `fail2ban-client status sshd` → jail активен; повторный
  деплой → 0 changed по fail2ban-таскам.
- [ ] **AC7 — идемпотентность.** Второй подряд `make deploy` (без изменений кода)
  → ВСЕ новые таски (daemon.json, logrotate, cron'ы, скрипт, fail2ban) = `changed=0`;
  docker НЕ рестартует.

## Plan

1. `provision.yml` — daemon.json (copy + notify handler `Restart docker`) + fail2ban
   таски. `make ansible-check` (syntax).
2. Роль `host_alerts`: defaults (пороги/интервал/throttle/путь env-файла) → шаблон
   скрипта (source sensitive.env; пустые креды → exit 0; check disk/mem; throttle
   state-файл; curl sendMessage `-fsS -o /dev/null`, токен НЕ в аргументах echo/логах)
   → tasks (dir, script, 2 cron-записи: check каждые 15 мин). Подключить в deploy.yml.
3. backup-роль: logrotate-конфиг + fail-hook в существующей cron-строке + новый
   restore-check cron (вс 04:30) с fail-hook; defaults.
4. Прогон на проде: деплой → AC1/AC2/AC6 → эксперименты AC4 (порог 1%) и AC5
   (прямой вызов fail-ветки) → вернуть пороги → повторный деплой = AC7.
5. AC3 — ручной прогон cron-строки restore-check (не ждать воскресенья).

## Invariants

- Пустые `OPS_TELEGRAM_*` → host-алерты = silent no-op (как notify_ops; деплой без
  ops-бота валиден). Заполненность кредов — первый шаг чек-листа verify.
- Токен бота не появляется: в cron-строках, в логах скрипта, в ansible-выводе
  (источник — только source sensitive.env внутри скрипта; curl без -v).
- Throttle: максимум 1 алерт на reason за окно — host-алерты не превращаются в спам
  (паттерн notify_ops/TASK-035).
- Все новые таски идемпотентны (AC7); `make deploy` остаётся единственным путём
  накатки (никаких ручных правок на хосте — ADR-005 дисциплина).
- restore-check и backup не пересекаются по времени (03:00 daily vs 04:30 Sunday);
  внутри backup-пути взаимоисключение уже даёт flock (pg_backup.sh, F2).

## Edge cases

- Первый накат daemon.json → restart docker → все контейнеры узла перезапускаются:
  выполнять деплой-окном; swarm восстанавливает сервисы; smoke в конце deploy.yml
  подтверждает живость. Зафиксировать в PR-описании.
- На хосте уже есть daemon.json с другими ключами → copy его перезапишет МОЛЧА →
  do-стадия начинается с инспекции файла на живом хосте; чужие ключи мержатся в шаблон.
- Диск 100% → state-файл throttle не пишется → скрипт всё равно шлёт алерт (порядок:
  сначала send, потом запись state; неудачная запись state → повторный алерт лучше
  тишины).
- `sensitive.env` отсутствует (свежий хост до первого деплоя env-роли) → скрипт
  exit 0 без ошибки (роль host_alerts идёт ПОСЛЕ env — на штатном пути файл есть).
- restore-check дольше окна (большой дамп) → cron-наложение со следующим тиком
  невозможно (weekly); наложение с backup-cron'ом — времена разнесены.
- fail2ban банит самого owner'а (fail по ключу не триггерит; пароль-фейлы — да) →
  дефолтный bantime 10 мин, не lockout навсегда; runbook-заметка в PR.
- Telegram API недоступен → `curl -fsS` fail → скрипт молчит (exit 0 после
  логирования в backup-лог), cron не шлёт MAILTO-спам.

## Test plan

- Кода приложения нет; проверки — ansible + поведенческие:
- локально: `make ansible-check` (syntax site.yml); `ansible-lint` при наличии;
  рендер шаблона скрипта глазами + `bash -n` на отрендеренном скрипте.
- прод (вместо molecule): двойной прогон `make deploy` — второй = 0 changed по новым
  таскам (AC7 = главный идемпотентность-тест); AC1–AC6 эксперименты из Plan §4–5.
- security (5.5): REQUIRED-кандидат — скрипт читает sensitive.env: проверить токен
  не течёт (cron-строки, ansible stdout, ps-аргументы — токен только в env curl'а
  или URL? URL содержит токен → ps видит curl-процесс → использовать `--data-urlencode`
  + токен в URL неизбежен для Bot API → митигировать: скрипт 0750 root, процесс
  короткоживущий, хост single-operator; зафиксировать как осознанный остаточный риск).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "c390c4c"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (ansible-таски + роль host_alerts + backup-роль)
- [ ] 4 verify (G2 — ansible-check + двойной деплой + AC-эксперименты)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED-кандидат — скрипт с доступом к sensitive.env)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 из аудита VPS-гигиены. Deps: TASK-034 (backup-роль/cron/лог — база
для logrotate и restore-check cron), TASK-057 (make deploy / site.yml — путь накатки;
живые AC — на задеплоенном хосте). Использует существующий ops-бот TASK-035 —
новых секретов не вводит. Прод-эксперименты AC4/AC5 требуют живого хоста: если деплой
057 ещё owner-blocked — код мержится, живые AC помечаются blocked как в 059/060.)
