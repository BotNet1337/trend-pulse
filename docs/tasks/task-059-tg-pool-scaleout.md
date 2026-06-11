---
id: TASK-059
title: TG-пул до ≥3 аккаунтов — сессии в vault, prod-таргет здоровья, операторский runbook
status: in-progress         # planned → in-progress → review → done
owner: infra
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "e859da3"
branch: "gsd/phase-tg-pool-scaleout"
tags: [launch, ops, collector, runbook, p1]
---

# TASK-059 — TG-пул ≥3 аккаунтов + runbook (закрытие P1 «сейчас»)

> Прод живёт на ОДНОМ Telegram-аккаунте (`POOL_MIN=1`, learnings task-005) — один бан =
> продукт молчит у всех клиентов ([pain-points P1](../architecture/pain-points.md)).
> Код пула и health-метрика готовы (TASK-035); недостаёт самих аккаунтов (действие
> владельца) и **runbook'а «добавить аккаунт в пул»** — процедура сейчас живёт в голове.
> Цель: 3 живые сессии в vault, prod-таргет `pool_min_healthy=3`, воспроизводимая процедура.

## Context

Пул: `collector/telegram/account_pool.py` — ротация, `report_flood_wait()` (exponential
backoff 2s→300s), `AllAccountsFloodWaitError`; `collector/constants.py::POOL_MIN=1`
(dev), `POOL_MAX=10`. Сессии — CSV StringSession'ов в env `TELEGRAM_POOL_SESSIONS`
(`config.py`), рендерится из vault-ключа `vault_telegram_pool_sessions`
(`ops/ansible/roles/env/templates/sensitive.env.j2`; рядом `vault_telegram_api_id`/`_api_hash`).
Health (TASK-035): `observability/pool_health.py` эмитит `log_event("pool_health",
size/cooling/healthy/target/degraded)`; деградация = healthy < `pool_min_healthy`
(settings; **код-default 3, но prod group_vars выставляет 1** — после заполнения пула
перевод на 3 обязателен); self-alert опсам через `ops_telegram_bot_token`/`ops_telegram_chat_id`
(throttle `ops_alert_throttle_seconds=3600`, reasons `all_flood`/`pool_below_target`).
Генерация сессии: `development/scripts/get-telegram-session.sh` — QR-login (Telethon
`qr_login`; коды входа исчерпываются — урок task-005), креды из `sensitive.env`, человек
сканирует QR телефоном-владельцем. Прокси per-account в коллекторе НЕТ (осознанно: см.
Discussion). StringSession = доступ уровня пароля — только vault, никогда в логи/чат
(урок task-005).

## Goal

После задачи: в `vault_telegram_pool_sessions` — ≥3 валидные сессии РАЗНЫХ аккаунтов;
prod `pool_min_healthy=3`; `pool_health` на проде показывает `size=3, healthy=3,
degraded=false`; self-alert проверен «вживую» (выключение одной сессии триггерит алерт
опсам); runbook «добавить/заменить аккаунт» проходится по шагам без устных знаний. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Это код-задача или ops? → A: 95% ops → Decision: код почти не трогаем; изменения —
  только конфиг (prod group_vars `pool_min_healthy: 3`) + runbook. `POOL_MIN` в
  `collector/constants.py` НЕ поднимаем: 1 — корректный нижний гард для dev; целевой
  размер на проде задаёт `pool_min_healthy` (так и задумано в TASK-035).
- Q: Откуда аккаунты? → A: владелец → Decision: 2 новых номера (физические SIM или
  надёжный провайдер виртуальных номеров — решает владелец; одноразовые SMS-сервисы НЕ
  рекомендуем: аккаунты банятся чаще, теряется доступ при ре-логине). Аккаунты «прогреть»:
  возраст хотя бы несколько дней, заполненный профиль, без массовых действий первые дни —
  фиксируем рекомендации в runbook (анти-бан гигиена, мы ТОЛЬКО читаем публичные каналы).
- Q: Прокси per-account? → A: не сейчас → Decision: коллектор ходит с одного VPS-IP —
  для READ-ONLY MTProto это штатно (так живут TGStat-подобные); per-account прокси =
  новая фича коллектора → отложено в TASK-054 (fallback-источник/авто-прогрев, P1
  «навсегда»). Зафиксировать как осознанный риск в runbook.
- Q: Как добавить сессию БЕЗ передачи StringSession через чат/диск? → A: vault-only →
  Decision: процедура = `get-telegram-session.sh` (локально, креды из sensitive.env) →
  вывод СРАЗУ в `ansible-vault edit vault/sensitive.vault.yml` (append к CSV) → `make
  ansible-unpack` (локальная проверка рендера) → деплой (пере-рендер env на хосте) →
  проверка `pool_health` в логах. Никаких промежуточных файлов/буферов обмена в заметках.
- Q: Где живёт runbook? → A: рядом с существующей доков-структурой → Decision: расширить
  `development/scripts/README.md` (уже описывает get-telegram-session.sh) разделом
  «Пул: добавить/заменить аккаунт» + сослаться из `docs/full-system-test.md` §B (live
  TG-каналы) и из pain-points P1. Отдельный каталог runbooks не плодим (один источник).
- Q: Как проверить self-alert честно (G2)? → A: контролируемая деградация → Decision:
  временно убрать одну сессию из env на стенде (или невалидную третьей) → ждать
  `pool_below_target` в ops-чате → вернуть. На ПРОДЕ — только наблюдение метрики.

## Scope
> **ops + docs.** Код коллектора/health НЕ меняется. Owner-шаги явно помечены.

- **Touch ONLY:**
  - `ops/ansible/inventory/group_vars/prod*` — `pool_min_healthy: 3` (точный файл — где
    лежит текущее значение 1; найдено на locate-стадии исполнения).
  - vault `sensitive.vault.yml` — `vault_telegram_pool_sessions`: +2 сессии (CSV)
    **[owner, через ansible-vault edit — содержимое не попадает в diff/PR]**;
    `vault_ops_telegram_*` — проверить заполненность (self-alert получатель).
  - `development/scripts/README.md` — раздел «Пул технических аккаунтов: добавить /
    заменить / отозвать» (процедура из Discussion + анти-бан гигиена + чек-лист проверки).
  - `docs/architecture/pain-points.md` — P1 строка «сейчас»: отметить закрытие
    (TASK-035 → TASK-059 выполнены, остаётся «навсегда» TASK-054).
  - `docs/full-system-test.md` §B — ссылка на runbook (prereq для live-TG прогона).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `collector/**` (пул/ротация/backoff — работают),
  `observability/pool_health.py` (TASK-035 — работает), `POOL_MIN`/`POOL_MAX` константы,
  `get-telegram-session.sh` (работает; правка только если прогон найдёт баг — тогда
  отдельным мини-диффом в этом же PR с пометкой).
- **Blast radius:** env прода (`TELEGRAM_POOL_SESSIONS` — формат CSV должен распарситься:
  битая сессия в CSV не должна валить воркер на старте — поведение проверить на стенде
  ДО прода); ops-алертинг (порог 1→3 начнёт орать, если сессий меньше — поэтому порядок:
  сначала сессии, потом порог).

## Acceptance Criteria

- [ ] **AC1 — runbook воспроизводим.** Given чистый исполнитель (агент/человек) по
  `development/scripts/README.md` When проходит процедуру на dev-стенде с тестовым
  аккаунтом Then получает сессию в vault и видит её в `pool_health.size` — без устных
  подсказок.
- [ ] **AC2 — пул заполнен.** Given прод после деплоя When смотрим `pool_health` Then
  `size=3, healthy=3, target=3, degraded=false`; коллектор читает каналы (свежие посты
  появляются), FLOOD_WAIT-ротация живёт (нет `all_flood`).
- [ ] **AC3 — порог боевой.** prod `pool_min_healthy=3`; Given одна сессия деградирует
  (стенд-эксперимент) When healthy=2 Then self-alert `pool_below_target` приходит в
  ops-чат в течение throttle-окна, ровно один (throttle работает).
- [ ] **AC4 — секрет-гигиена.** StringSession'ы НЕ появляются: в git-diff, PR, логах
  (`grep` по префиксу сессии в логах стенда = 0), Sentry (scrub-суффиксы покрывают),
  в этом доке. Проверка — часть review/security.
- [ ] **AC5 — G2 (боевой).** На проде ≥24h после включения: ни одного
  `pool_below_target`/`all_flood`; алерты юзерам доставляются (E2E «пост→алерт» из
  full-system-test §B зелёный).

## Plan

1. Runbook-раздел в `development/scripts/README.md` (процедура + анти-бан гигиена +
   чек-лист + отзыв/замена сессии).
2. **[owner]** 2 аккаунта: номера → QR-login через скрипт → vault append (по runbook —
   это одновременно AC1-прогон).
3. Стенд: рендер env → пул size=3 → эксперимент деградации (AC3) → вернуть.
4. prod group_vars `pool_min_healthy: 3` → деплой → наблюдение AC2.
5. 24h-наблюдение (AC5) → pain-points P1 отметка → ship.

## Invariants

- StringSession = пароль: существует ТОЛЬКО в vault и в памяти процесса; не в git, не в
  логах, не в задаче, не в чате (урок task-005).
- Порядок «сессии → порог»: порог 3 поднимается только когда 3 сессии уже живые
  (иначе самоиндуцированный алерт-шторм).
- Один источник процедуры — scripts/README.md (full-system-test и pain-points ссылаются,
  не копируют).
- Каналы читаем ТОЛЬКО публичные; аккаунты не пишут/не джойнятся массово (ToS-гигиена,
  overview §7).

## Edge cases

- Битая/отозванная сессия в CSV → воркер должен стартовать с остальными и алертить
  (`auth`-reason), не crash-loop — проверить на стенде; если падает — это БАГ, фикс
  отдельным мини-диффом (помеченным) в этом PR.
- FLOOD_WAIT на новом «холодном» аккаунте чаще → backoff поглощает; в runbook —
  «не добавлять 2 новых аккаунта в один день под нагрузкой».
- `ops_telegram_bot_token` не заполнен → self-alert молчит МОЛЧА → AC3 невозможен;
  проверка заполненности — первый шаг чек-листа.
- Владелец теряет телефон аккаунта → сессия живёт, но ре-логин невозможен → runbook-раздел
  «замена»: генерируем новую сессию другого аккаунта, отзываем старую (Telegram → Devices).
- Telegram режет VPS-IP (datacenter range) при логине → сессии генерируются ЛОКАЛЬНО
  (скрипт и так локальный), на VPS едет только StringSession — зафиксировано в runbook.

## Test plan

- Код-тестов нет (кода нет); проверки поведенческие:
- стенд: пул 3, деградация → alert (AC3), битая сессия в CSV (edge), рендер env
  superset прежних ключей (урок task-012).
- прод: AC2 наблюдение + AC5 24h + §B E2E.
- security (5.5): ОБЯЗАТЕЛЬНО — секрет-гигиена сессий (AC4), no_log на ansible-тасках,
  vault-only путь.

## Checkpoints

current_step: 7
baseline_commit: "e859da3"
branch: "gsd/phase-tg-pool-scaleout"
lock: "loop-2026-06-11-launch-gaps"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (runbook + owner-шаги + конфиг)
- [x] 4 verify (G2 = фактчек runbook; live AC1 blocked on owner — 2 TG-номера нужны)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (REQUIRED — session-секреты)
- [x] 6 ship (runbook-часть)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11. Закрывает P1 «сейчас» полностью (TASK-035 дал прибор, 059 даёт
сам пул + процедуру); P1 «навсегда» (TGStat/Telemetr fallback, авто-прогрев, прокси) —
TASK-054/E7. Зависимости: 035 (health), 012 (vault). Не зависит от 057 — пул можно
заполнить до прод-запуска (стенд), но AC2/AC5 финализируются на проде.)

**do-stage 2026-06-11 (отклонение):** `pool_min_healthy` остаётся `"1"` — порог НЕ
переключён в рамках do-стадии. Порядок «сессии → порог» обязателен (Invariant): переключение
на `"3"` — owner-шаг runbook'а (`development/scripts/README.md` §«Поднять порог»), выполняется
ТОЛЬКО после заполнения пула живыми сессиями (иначе алерт-шторм). Изменения do-стадии:
только runbook + комментарий в prod.yml + ссылки в full-system-test/pain-points.

**blocked: owner** — 2 TG-номера (физические SIM / виртуальный оператор) + QR-login
на каждый (AC2/AC3/AC5). До появления сессий AC2/AC3/AC5 не могут быть проверены на проде.

**ship-stage 2026-06-11 (runbook-часть):** После merge: runbook в main; blocked: owner —
2 TG-номера + QR-login (AC1 walkthrough, AC2/AC3/AC5). lock снять при learnings.

**review-stage 2026-06-11 (PASS, no blocking):** adversarial review 5 файлов vs e859da3.
Scope ровно 5 файлов; prod.yml значение остаётся `"1"` (порядок «сессии→порог» соблюдён);
секрет-инвариант в runbook сильный (vault-only, без echo/cat/буфера); ссылки валидны
(full-system-test→README, pain-points P1 строка целостна, 4 колонки). Блокеров нет.
MEDIUM-findings (executability, AC1 dry-run) — устранить в do до ship либо принять осознанно:
- M1 `make deploy` (Шаг 4 / «Поднять порог») в текущем Makefile НЕ существует — он вводится
  TASK-057 (planned). Fallback-строка `ansible-playbook site.yml` дана, и full-system-test.md
  уже канонизирует `make deploy`, поэтому runbook консистентен доку-инварианту. Риск: «чистый
  исполнитель» на dev-стенде до мерджа 057 упрётся в `No rule to make target: deploy`.
  Fix: пометить «требует TASK-057 (make deploy)» или дать прямую ansible-команду как основную.
- M2 Шаг 4 утверждает «перезапускает api/worker … без даунтайма». worker читает
  TELEGRAM_POOL_SESSIONS через `env_file: sensitive.env`; `docker_compose_v2 state: present`
  при изменении ТОЛЬКО содержимого env_file НЕ гарантирует пересоздание контейнера (env_file
  не входит в config-hash compose v2) → новая сессия может быть молча проигнорирована, size не
  вырастет. Fix: добавить явный рестарт/recreate (`docker compose up -d --force-recreate worker`
  или ansible-handler с recreate) и переформулировать «без даунтайма».
- M3 Шаг 5 / чек-лист без failure-ветки (AC1 требует): нет «что делать если pool_health не
  появился / size не вырос / degraded=true / ansible-unpack не показал сессию». Fix: добавить
  ветку диагностики (проверить CSV в vault, force-recreate worker M2, grep auth-reason).
- LOW: Шаг 3 `grep -c ',' sensitive.env | head -1` — артефакт-строка без смысла (счёт запятых
  по всему файлу), вводит в заблуждение; оставить только точную `tr ',' '\n' | wc -l`.
Вердикт: PASS → 5.5 security (REQUIRED). MEDIUM желательно закрыть в do до ship (особенно M2 —
функциональный риск «сессия не подхватилась»).

**security + review/do-stage 2026-06-11 (PASS):** review/security findings (M1-M3, security-M)
исправлены в runbook (`development/scripts/README.md`):
- M1 (make deploy не существует): Шаг 4 и «Поднять порог» теперь используют
  `ansible-playbook ops/ansible/site.yml -l prod --vault-password-file ...` как основную
  команду; `make deploy` упомянут как «после TASK-057 — эквивалент».
- M2 (env_file не пересоздаёт контейнер): добавлен явный `docker compose up -d
  --force-recreate worker` после деплоя; фраза «без даунтайма» убрана из Шага 4.
- M3 (нет failure-ветки): добавлен подраздел «Если что-то пошло не так» с четырьмя
  сценариями: pool_health не появился, size не вырос, degraded=auth, self-alert молчит.
- LOW (grep -c ','): артефактная строка удалена, оставлен только `tr ',' '\n' | wc -l`.
- security-M (grep OPS_TELEGRAM печатает токены): заменён на count-only
  `grep -c '^OPS_TELEGRAM_BOT_TOKEN='` / `grep -c '^OPS_TELEGRAM_CHAT_ID='` (ожидается 1).
- security-LOW (scrollback): добавлено предупреждение после шага 2 о закрытии терминала.
