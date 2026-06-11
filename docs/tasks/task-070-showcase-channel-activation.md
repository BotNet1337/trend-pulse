---
id: TASK-070
title: Активация showcase-канала — публичный TG-канал, бот-админ, chat_id в vault, первый автопост
status: review              # planned → in-progress → review → done
owner: infra
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [launch, ops, runbook, showcase, growth, e3]
---

# TASK-070 — Активация showcase-канала (запуск самого дешёвого канала привлечения)

> Код полностью готов (TASK-044 автопостинг + TASK-045 proof-of-speed), но
> `showcase_channel_chat_id` пуст → beat-задача `showcase-autopost` = no-op
> (осознанный AC4 задачи 044). Витрина — главный органический канал привлечения
> («Узнай за 40 минут до мейнстрима») — НЕ работает, пока owner не создаст канал
> и не впишет chat_id в vault. Это runbook-задача в стиле TASK-059: кода ~0,
> owner-шаги по шагам, финальный AC = первый живой автопост с CTA.

## Context

Автопостинг (TASK-044): beat-задача каждые `showcase_post_interval_seconds=900` берёт
кластеры showcase-тенанта со score ≥ `showcase_post_min_score=85`, возрастом ≥
`showcase_post_delay_seconds=2400`, ≤24h-окна, не чаще `showcase_posts_per_day_max=8`
(defaults: `backend/src/config.py:199-204`); постит в `showcase_channel_chat_id`
через `showcase_bot_token` (`config.py:482-483`); пустые креды → no-op + warn-once
(AC4 044). CTA: `{public_base_url}/?utm_source=tg_showcase&utm_campaign=autopost`
(`backend/src/showcase/formatting.py:32`), `public_base_url=https://foresignal.biz`
(prod group_vars). Wiring проверен НАСКВОЗЬ и полон: vault
`vault_showcase_bot_token`/`vault_showcase_channel_chat_id` →
`ops/ansible/roles/env/templates/sensitive.env.j2:40-41`
(`SHOWCASE_BOT_TOKEN`/`SHOWCASE_CHANNEL_CHAT_ID`) → `release/env/sensitive.env` →
`release/compose/worker.yml:17-19` + `beat.yml:15-17` (`env_file`) → Settings.
Swarm-путь подхватывает смену env БЕЗ force-recreate: `make -C release deploy`
рендерит через `compose config`, который ИНЛАЙНИТ env_file в environment
(`release/Makefile:104-114`) → stack deploy видит новый env (гочча M2 из task-059
здесь не воспроизводится — это swarm, не compose v2 up). Лендинг:
`landing/public/config.json` — поля `showcaseTelegramUrl` НЕТ (проверено grep);
его вводит TASK-067 (planned, landing-хвост); footer
(`landing/src/pages/layouts/root-layout.tsx:155-217`) TG-ссылки не имеет.
MVP-решение 044: бот может быть тем же, что ops-бот (один бот, два чата;
`sensitive.env.j2:39`), конфиг-ключи разные.

## Goal

После задачи: живой публичный TG-канал бренда; бот — админ с правом постинга;
`vault_showcase_channel_chat_id` (и `vault_showcase_bot_token`) заполнены; после
деплоя первый автопост появился в канале с CTA-ссылкой `utm_source=tg_showcase`;
частота/анти-спам соблюдаются; @username канала виден на лендинге
(`showcaseTelegramUrl` из TASK-067). DoD = AC.

## Discussion
<!-- durable record -->
- Q: @username канала? → A: бренд foresignal → Decision: варианты по убыванию
  предпочтения: **@foresignal** (апекс-бренд, дефолт), @foresignal_pulse,
  @foresignal_signals, @foresignal_trends. Финальный выбор — за owner'ом при создании
  (username может быть занят); дефолт = @foresignal. Выбранное имя фиксируется в
  Details на do-стадии и идёт в landing config (showcaseTelegramUrl).
- Q: Свой бот или ops-бот? → A: MVP-решение 044 действует → Decision: переиспользуем
  ops-бота (значение `vault_ops_telegram_bot_token` копируется в
  `vault_showcase_bot_token` — ключи разные, зоны ответственности разойдутся позже).
  Если owner хочет отдельного бота — BotFather, 2 минуты, на runbook не влияет.
- Q: chat_id — численный (-100…) или @username? → A: @username → Decision: канал
  публичный по определению задачи, Bot API принимает `@channelusername` как chat_id —
  не нужен token-bearing вызов getChat для discovery. Численный id надёжнее при
  переименовании канала, но переименование бренд-канала = осознанное событие
  (одна правка vault + deploy). Зафиксировать оба варианта в runbook-шаге.
- Q: Деплой подхватит новый env без пересоздания? → A: да (swarm) → Decision: путь —
  `make deploy` (корневой Makefile:181-188); `compose config` инлайнит env_file →
  stack deploy обновляет сервисы worker/beat с новым env. Проверка после деплоя:
  `docker exec <worker> printenv SHOWCASE_CHANNEL_CHAT_ID` (значение НЕ секрет —
  это публичный @username; токен НЕ печатать).
- Q: Сколько ждать первый автопост? → A: часы, не минуты → Decision: пост требует
  кандидата (score ≥85, возраст ≥40 мин, внутри 24h) — при живом коллекторе это
  0–8 постов/день. «Нет поста за 24h при degraded=false» — повод смотреть кандидатов
  (SQL в runbook-шаге), а не алармить. Не снижать пороги ради демо-поста: лестница
  ценности (delay 2400 > free 1800) — продуктовый инвариант 044.
- Q: Кодовая часть есть? → A: почти нет → Decision: wiring полон (см. Context, проверен
  на locate). Единственный возможный код: `showcaseTelegramUrl` в landing
  `config.json` + ссылка в footer — это вводит TASK-067. Если на момент исполнения
  070 задача 067 ещё не смержена — добавляем поле+ссылку минимальным диффом ЗДЕСЬ
  (по паттерну config-driven полей: contactEmail/signupUrl), и 067 при планировании
  учитывает это. Дублирующую задачу не создаём.
- Q: Зависимость от 057? → A: да → Decision: автопост живёт в worker/beat на проде →
  финальные AC только после живого деплоя. Vault-ключи и канал готовятся до.
- Q: 067 уже смержен (PR #92) — заполнять `showcaseTelegramUrl` здесь? → A: нет →
  Decision: значение зависит от фактически свободного @username, который выбирает
  owner при создании канала; нота TASK-067 в config.json прямо говорит «Filled by
  owner once the channel is created». Кодовая часть лендинга готова (hero+footer
  рендерят ссылку при непустом значении) — заполнение = owner-шаг 6 runbook'а B7,
  правок кода не требует. Консервативный дефолт: пустую строку не трогаем.
- Q: формат поста «обнаружено в HH:MM UTC» — русский, а бренд EN-only? → A: да,
  несоответствие → Decision: НЕ чиним здесь — Scope/Invariants 070 явно запрещают
  правки `showcase/formatting.py` (формат — продуктовое решение 044), и AC2 этого
  дока цитирует русский штамп. Зафиксировано как кандидат на отдельную микро-задачу
  (1 строка + тесты): EN-штамп «detected at HH:MM UTC» для EN-канала.
- Q: имя канала — «TrendPulse — early viral signals» (Plan, шаг 1)? → A: устарело
  после ребрендинга W1/072 → Decision: «Foresignal — early viral signals» (бренд
  Foresignal, EN-only); runbook B7 использует новое имя.

## Scope
> **ops + owner-runbook.** Backend/showcase-код НЕ трогается (готов и протестирован).
> Owner-шаги помечены **[owner]** — как в task-059.

- **Touch ONLY:**
  - vault `ops/ansible/vault/sensitive.vault.yml` — `vault_showcase_bot_token`,
    `vault_showcase_channel_chat_id` **[owner, через `ansible-vault edit` — значения
    не попадают в diff/PR]**.
  - `landing/public/config.json` — значение `showcaseTelegramUrl: "https://t.me/<username>"`
    (поле из TASK-067; если 067 не смержен — добавить поле + footer-ссылку здесь,
    см. Discussion).
  - `docs/full-system-test.md` — §B/§C-чеклист: подраздел «Showcase-канал» (создание,
    бот-админ, vault, проверка первого поста) — runbook живёт здесь, один источник.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `backend/src/showcase/**` (селектор/форматирование/отправка —
  TASK-044, done), `backend/src/config.py` (defaults интервалов/порогов — продуктовые
  значения 044), `scheduler.py`, `sensitive.env.j2` (ключи уже есть, строки 37–41),
  compose-фрагменты, пороги `showcase_post_*` (не снижать ради демо).
- **Blast radius:** env прода (2 значения; пустые → дальше no-op, заполненные →
  beat начинает постить — обратимо: очистить vault-ключ + deploy); публичная витрина
  (контент постов — агрегаты кластеров, компллаенс-санитизация уже в коде 044);
  landing config (1 поле).

## Acceptance Criteria

- [ ] **AC1 — канал и бот готовы.** Given публичный канал с выбранным @username
  When смотрим админов Then бот присутствует с правом «Post messages»; канал имеет
  название/описание/аватар бренда (описание со ссылкой на foresignal.biz).
- [ ] **AC2 — первый автопост живой.** Given vault заполнен и `make deploy` прошёл
  When появляется кандидат (score ≥85, возраст ≥40 мин) Then пост публикуется в
  канале: формат «🔥 … · score N · обнаружено в HH:MM UTC» + CTA-ссылка содержит
  `utm_source=tg_showcase&utm_campaign=autopost`; строка `showcase_posts`
  со status=posted.
- [ ] **AC3 — анти-спам уважается.** Given живой канал ≥48h When считаем посты
  Then ≤8/день (UTC), интервал тиков ~15 мин, ни один кластер не запощен дважды
  (UNIQUE(cluster_id) — наблюдение, код-гарантия из 044).
- [ ] **AC4 — лестница ценности.** Штамп «обнаружено в HH:MM» в посте отстаёт от
  фактического `first_seen` на ≥40 мин (delay 2400 > free 1800) — канал медленнее
  Free-плана (выборочная сверка 2–3 постов с БД).
- [ ] **AC5 — витрина связана.** Лендинг показывает ссылку на канал
  (`showcaseTelegramUrl`); переход t.me/<username> открывает живой канал.
- [ ] **AC6 — секрет-гигиена.** Токен бота НЕ появляется в diff/PR/логах/этом доке
  (chat_id-@username — не секрет, но живёт в vault как задумано 044).

## Plan

1. **[owner]** Создать публичный канал (@foresignal или первый свободный вариант из
   Discussion): название «TrendPulse — early viral signals», описание с
   foresignal.biz, аватар. Зафиксировать @username в Details.
2. **[owner]** Добавить бота админом канала с правом «Post messages» (бот = ops-бот,
   см. Discussion; или новый через BotFather → токен сразу в vault).
3. **[owner]** `ansible-vault edit ops/ansible/vault/sensitive.vault.yml`:
   `vault_showcase_bot_token` (= значение ops-токена или новый),
   `vault_showcase_channel_chat_id: "@<username>"`. → `make ansible-unpack`
   (локальная проверка рендера: `grep -c '^SHOWCASE_' development/env/sensitive.env`
   → 2, значения не печатать).
4. `make deploy` → проверить env у worker (`printenv SHOWCASE_CHANNEL_CHAT_ID`),
   warn-once «showcase disabled» в логах ИСЧЕЗ.
5. Наблюдение первого поста (≤24h при живом коллекторе): worker-логи
   (`log_event` showcase), канал, строка showcase_posts → AC2/AC4.
6. `landing/public/config.json` — showcaseTelegramUrl (если 067 не смержен —
   поле+footer минимальным диффом) → деплой лендинга → AC5.
7. Чек-лист в `docs/full-system-test.md` (воспроизводимость) → 48h-наблюдение AC3 → ship.

## Invariants

- Канал медленнее Free-плана, Free медленнее Pro (delay 2400 > 1800 > 0) — пороги
  044 НЕ снижаются ни для демо, ни для «оживления» канала.
- Токен бота — vault-only (как все секреты; урок task-005); chat_id/username —
  vault по контракту 044, хотя публичен.
- Пустые креды → полный no-op: порядок «канал+vault → deploy» безопасен в любом
  состоянии (деплой без витрины валиден — AC4 задачи 044).
- Контент постов — только агрегаты кластеров (санитизация в коде 044); никаких
  правок формата в этой задаче.
- Один источник процедуры — full-system-test чек-лист (не дублировать в README).

## Edge cases

- @foresignal занят → следующий вариант из Discussion; username фиксируется в
  Details и в landing config (единственные два места).
- Бот не админ / нет права постинга → Bot API 403 → строка showcase_posts остаётся
  pending → ретрай следующим тиком (механика 044 AC3); диагностика: worker-логи →
  починить права → пост уйдёт сам.
- Неверный chat_id (опечатка username) → Bot API 400 «chat not found» → как выше:
  pending+ретрай; правка vault + deploy.
- Нет кандидатов ≥85 за сутки (тихий день/деградация пула) → нет постов = штатно;
  сначала проверить `pool_health` (TASK-059), потом кандидатов SQL'ем; пороги не
  трогать.
- Owner заполнил vault ДО создания канала/прав бота → посты копятся pending и уходят
  после фикса прав — допустимо, но runbook-порядок (канал → бот → vault) избегает
  мусорного ретрая.
- Переименование канала после запуска → @username-chat_id ломается → правка vault +
  deploy + landing config (зафиксировано в чек-листе; численный -100-id избегает
  этого — опция в runbook-шаге 3).

## Test plan

- Кода нет (или 1 config-поле + footer-ссылка) — проверки поведенческие:
- runbook-воспроизводимость: шаги 1–6 проходятся owner'ом без устных подсказок
  (чек-лист full-system-test); рендер env superset прежних ключей (урок task-012).
- live: AC2 (первый пост: формат+utm+штамп), AC3 (48h: cap/interval/no-dup),
  AC4 (сверка штампа с first_seen в БД), AC5 (лендинг-ссылка).
- landing (если поле добавляется здесь): `npm run build` + `seo:validate` зелёные.
- security (5.5): секрет-гигиена токена (AC6) — vault-only путь, vault-значения вне
  diff; skip-кандидат по коду (нового кода с поверхностями нет) — подтвердить на review.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 7
baseline_commit: "c390c4c"
branch: "task/070-showcase-channel-activation"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (runbook-чеклист + owner-шаги + landing-поле при необходимости)
- [x] 4 verify (G2 — код-часть: ci-fast зелёный (ruff+mypy+657 unit); live AC2–AC5 —
  owner-blocked, runbook B7 + MANUAL-TODO §6)
- [x] 5 review (adversarial вычитка диффа: PR-номер 067 исправлен 94→92, формат поста
  сверен с formatting.py (RU-штамп), AC4-семантика уточнена, SQL/таблицы/лог-события
  сверены с кодом, ansible-unpack путь подтверждён)
- [x] 5.5 security (нового кода нет; в диффе только имена vault-ключей и существующие
  публичные паттерны; runbook запрещает печать токена — AC6 для код-части)
- [x] 6 ship (PR в main, ветка task/070-showcase-channel-activation; merge — за owner)
- [ ] 7 learnings (мирror решений — в Discussion/Details; docs/learnings.md в этом
  ране запрещён оркестратором — текст в финальном ответе)
debug_runs: []

## Details

(planned 2026-06-11. Активационный хвост Epic E3: код 044/045 done и смержен, витрина
выключена пустым chat_id. Deps: TASK-044 (механика автопостинга), TASK-057 (живой прод —
worker/beat; AC2–AC5 только после деплоя), TASK-067 (поле showcaseTelegramUrl в landing
config — fallback-решение в Discussion, если 067 позже). Owner-шаги 1–3 могут идти ДО
деплоя 057 — vault-значения безопасны в любом состоянии (no-op инвариант).)

(do 2026-06-11, ветка task/070-showcase-channel-activation. Fallback из Discussion НЕ
понадобился: TASK-067 уже в main — `showcaseTelegramUrl` есть в `landing/public/config.json`
(пустая строка + нота «Filled by owner», hero+footer рендерят ссылку при непустом
значении). Wiring перепроверен насквозь на текущем main: `config.py:482-483` (пустые
дефолты) → `sensitive.env.j2:40-41` → `release/compose/worker.yml`/`beat.yml` env_file →
`showcase/tasks.py` warn-once no-op; beat-расписание `scheduler.py:74-76`. Итоговый дифф =
runbook §B7 в `docs/full-system-test.md` (шаги 1-3,6 [owner]: канал → бот-админ → vault →
landing config; шаги 4-5,7: deploy-проверка env, наблюдение первого поста с SQL/лог-
командами, 48h AC3/AC4, откат) + этот док. Кода ноль — после owner-шагов фича включается
без правок кода. @username фиксируется owner'ом (дефолт @foresignal); имя канала —
«Foresignal — early viral signals» (ребрендинг, см. Discussion). Owner-шаги
продублированы в MANUAL-TODO §6 (внешний файл, вне git).)
