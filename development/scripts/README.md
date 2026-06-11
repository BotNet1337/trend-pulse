# development/scripts

Operational helper scripts for the TrendPulse dev/ops environment.

| Script | Purpose |
|---|---|
| [`ansible-unpack.sh`](./ansible-unpack.sh) | Render `development/env/{deploy,sensitive}.env` from `ops/ansible/group_vars` (stub; real ansible-vault → task-012). Run via `make ansible-unpack`. |
| [`gen_telegram_session.py`](./gen_telegram_session.py) | Generate a Telethon `StringSession` for ONE technical pool account (interactive). See below. |

---

## `gen_telegram_session.py` — get Telegram pool session strings

Session strings are **generated**, not downloaded: you log into each **technical**
account once (phone → code → optional 2FA) and Telethon prints a `StringSession`
you paste into `sensitive.env`. Run it **once per account** (3–10 accounts).

### Prerequisites
1. `api_id` + `api_hash` from **https://my.telegram.org** → *API development tools*
   (one pair for the whole app; see the app-description guidance in the TASK-005
   thread / `docs/learnings.md`).
2. `uv` installed and `backend/` synced (`telethon` is a backend dependency):
   ```sh
   make ansible-unpack   # if you haven't materialized env yet (optional here)
   ```

### Run (interactive — needs phone + code input)
From `apps/trendPulse`:

```sh
TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=your_api_hash \
  uv run --directory backend python ../development/scripts/gen_telegram_session.py
```

> Inside Claude Code, prefix with `!` so the interactive prompts work in-session:
> `! TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=your_api_hash uv run --directory backend python ../development/scripts/gen_telegram_session.py`

It will prompt:
1. `Please enter your phone (or bot token):` → the technical account's number, e.g. `+1234567890`
2. `Please enter the code you received:` → the login code Telegram sends to that account
3. *(if 2FA is on)* `Please enter your password:` → the account's cloud password

Then it prints a long `StringSession` line (starts like `1ApWap...`). **That is the session string.**

### Where to put the output
Collect all accounts' strings, comma-separated, into **`development/env/sensitive.env`** (gitignored):

```dotenv
TELEGRAM_API_ID=12345
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_POOL_SESSIONS=1ApWap...acc1...,1BxYz...acc2...,1CqRs...acc3...
```

(The exact env keys are finalized in `config.py` during TASK-005. The real source
of truth for secrets is the Ansible vault — task-012; `sensitive.env` is the
locally-rendered copy and is `.gitignore`d.)

### Compliance & anti-ban (READ)
- Use **only dedicated technical accounts** (their own SIMs) — **never** your personal
  account's session. **Public channels only.** (overview §2/§7, CONVENTIONS.)
- Generate from the **same IP/proxy/region** you'll later operate the account on
  (IP consistency is the #1 anti-takeover/anti-ban signal).
- Keep the device fingerprint consistent (the script pins one).
- A session string is **as sensitive as a password** — only in `sensitive.env`,
  never in git or logs. Enable 2FA on each technical account.
- Full anti-ban operating guide: see the TASK-005 thread / `docs/learnings.md`.

### Troubleshooting
- `env var TELEGRAM_API_ID is required` → you didn't pass the env vars; prepend them as shown.
- `PhoneNumberBannedError` / `AuthKeyDuplicatedError` → that account/number is already
  banned or the session was used from another IP; use a different technical account.
- `FloodWaitError` during login → wait the indicated seconds and retry (don't hammer).

---

## Пул технических аккаунтов: добавить / заменить / отозвать аккаунт

> **TASK-059 runbook.** Процедура полностью основана на `ansible-vault` — StringSession
> никогда не проходит через промежуточные файлы, буфер обмена, чат или переменные
> оболочки.  Выполняется **локально** (не на VPS).

### Секрет-инвариант (READ FIRST)

```
StringSession = пароль уровня доступа к аккаунту.
Существует ТОЛЬКО в двух местах:
  1. Ansible vault (ops/ansible/vault/sensitive.vault.yml — зашифрован)
  2. Памяти запущенного процесса collector'а на VPS
НЕ в: git-diff / PR / логах / Sentry / чате / файлах / буфере обмена / этом документе.
Урок: task-005. Нарушение = компрометация аккаунта → ротировать немедленно.
```

---

### Добавить аккаунт в пул

#### Предусловия

1. `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` заполнены в
   `development/env/sensitive.env` (рендерится `make ansible-unpack`; если ещё не
   материализовано — выполни `make ansible-unpack` сначала).
2. Vault-пароль доступен в `ops/ansible/.vault-pass` (gitignored).
3. `uv` установлен (`~/.local/bin/uv`).
4. Телефон ВЛАДЕЛЬЦА добавляемого аккаунта рядом (скрипт выводит QR — нужно отсканировать).

#### Шаг 1. Запустить QR-логин (генерация сессии — ЛОКАЛЬНО)

Из корня `apps/trendPulse`:

```sh
sh development/scripts/get-telegram-session.sh
```

Скрипт читает `TELEGRAM_API_ID/HASH` из `sensitive.env`, запускает `gen_telegram_session_qr.py`.
В терминале появится QR-код (ASCII).

**ВЛАДЕЛЕЦ** телефона добавляемого аккаунта открывает Telegram →
Settings → Devices → Link Desktop Device → сканирует QR.

Скрипт выводит StringSession в терминал (строка вида `1ApWap...`).

> Не копируй сессию — сразу выполни шаг 2.

#### Шаг 2. Записать сессию в vault (НЕ ЗАКРЫВАЯ терминал)

```sh
ansible-vault edit ops/ansible/vault/sensitive.vault.yml \
  --vault-password-file ops/ansible/.vault-pass
```

Внутри файла найди ключ `vault_telegram_pool_sessions`.
Добавь новую сессию через запятую к существующему CSV:

```yaml
# ДО:
vault_telegram_pool_sessions: "1ApWap...acc1..."
# ПОСЛЕ (пример с 2 аккаунтами):
vault_telegram_pool_sessions: "1ApWap...acc1...,1BxYz...acc2..."
```

Сохрани файл и выйди из редактора.
Vault автоматически пересохраняет файл в зашифрованном виде.

> **Никаких `echo` / `cat` / заметок / коммитов значения.**
> Если случайно вывел сессию в лог/чат — считать скомпрометированной, ротировать.

#### Шаг 2.5. Предупреждение о scrollback

> **ВАЖНО:** После сохранения в vault закрой окно терминала — StringSession остаётся
> в scrollback-буфере. Не используй терминал с логированием в файл для этих шагов.

#### Шаг 3. Проверить рендер локально

```sh
make ansible-unpack
# Убедиться что TELEGRAM_POOL_SESSIONS содержит N сессий:
grep 'TELEGRAM_POOL_SESSIONS' development/env/sensitive.env | tr ',' '\n' | wc -l
```

Ожидаемо: количество сессий выросло на 1.

#### Шаг 4. Задеплоить на прод

```sh
# Основная команда (до появления TASK-057):
ansible-playbook ops/ansible/site.yml -l prod --vault-password-file ops/ansible/.vault-pass

# После TASK-057 — эквивалент:
# make deploy
```

Ansible рендерит `sensitive.env.j2` → `/app/sensitive.env` на хосте.

> **Внимание:** изменение `env_file` НЕ пересоздаёт контейнер worker автоматически
> (`docker_compose_v2 state: present` не хеширует содержимое env_file). После деплоя
> **обязательно** выполни явный пересоздание worker'а:
>
> ```sh
> ssh deploy@foresignal.biz \
>   "docker compose -f /app/docker-compose.yml up -d --force-recreate worker"
> ```

#### Шаг 5. Проверить пул в логах worker'а

```sh
ssh deploy@foresignal.biz \
  "docker logs --since=2m \$(docker ps -qf name=worker) 2>&1 | grep pool_health"
```

Ожидаемо: `pool_health` event с `size=N, healthy=N, degraded=false`.

---

### Чек-лист проверки после добавления

- [ ] `vault_ops_telegram_bot_token` и `vault_ops_telegram_chat_id` заполнены в vault
      (иначе self-alert молчит и AC3 невозможен). Проверка — ТОЛЬКО счётчиком (не печатать значения!):
      ```sh
      make ansible-unpack
      grep -c '^OPS_TELEGRAM_BOT_TOKEN=' development/env/sensitive.env   # ожидается 1
      grep -c '^OPS_TELEGRAM_CHAT_ID=' development/env/sensitive.env     # ожидается 1
      ```
- [ ] `pool_health` в логах: `degraded=false`.
- [ ] Счётчик `size` == числу сессий в CSV vault-ключа.
- [ ] Ни одного `pool_below_target` алерта в ops-чате (если `pool_min_healthy` уже поднят).

---

### Если что-то пошло не так

**`pool_health` не появился в логах:**
Скорее всего, worker не был пересоздан после деплоя. Выполни явный force-recreate
(см. Шаг 4) и повтори проверку логов:
```sh
ssh deploy@foresignal.biz \
  "docker compose -f /app/docker-compose.yml up -d --force-recreate worker && \
   docker logs --since=2m \$(docker ps -qf name=worker) 2>&1 | grep pool_health"
```

**`size` не вырос (меньше ожидаемого):**
1. Проверь CSV в vault — ТОЛЬКО через `ansible-vault edit` (не печатай в терминал):
   ```sh
   ansible-vault edit ops/ansible/vault/sensitive.vault.yml \
     --vault-password-file ops/ansible/.vault-pass
   ```
   Убедись, что новая сессия добавлена к CSV в `vault_telegram_pool_sessions`.
2. Сделай force-recreate worker (см. Шаг 4) — env_file не подхватывается без пересоздания.

**`degraded=true` / `reason=auth`:**
Одна или несколько сессий битые или отозванные. Замени их по разделу «Заменить / отозвать
аккаунт» ниже.

**Self-alert молчит при `degraded=true`:**
Проверь наличие OPS-ключей count-проверкой из чек-листа:
```sh
grep -c '^OPS_TELEGRAM_BOT_TOKEN=' development/env/sensitive.env   # ожидается 1
grep -c '^OPS_TELEGRAM_CHAT_ID=' development/env/sensitive.env     # ожидается 1
```
Если 0 — заполни `vault_ops_telegram_bot_token` / `vault_ops_telegram_chat_id` в vault
и задеплой заново.

---

### Поднять порог pool_min_healthy до 3 (ТОЛЬКО после заполнения пула)

**Когда живых сессий ≥ 3:**

1. В `ops/ansible/group_vars/prod.yml` выставить:
   ```yaml
   pool_min_healthy: "3"
   ```
2. Задеплоить:
   ```sh
   # Основная команда (до появления TASK-057):
   ansible-playbook ops/ansible/site.yml -l prod --vault-password-file ops/ansible/.vault-pass

   # После TASK-057 — эквивалент:
   # make deploy
   ```
   Затем force-recreate worker (см. Шаг 4 выше).
3. Убедиться что `pool_below_target` алерт **не** приходит в ops-чат
   (логи: `pool_health` → `degraded=false`, `target=3`).

> Порог поднимается **только** после того, как сессии уже живые.
> Порядок «сессии → порог» обязателен — иначе алерт-шторм на каждый health-тик.

---

### Заменить / отозвать аккаунт

1. Добавить новую сессию нового аккаунта по процедуре выше (шаги 1–5).
2. В `ansible-vault edit` удалить старую сессию из CSV (оставить только новые).
3. Задеплоить (основная команда до TASK-057):
   ```sh
   ansible-playbook ops/ansible/site.yml -l prod --vault-password-file ops/ansible/.vault-pass
   ```
   Затем force-recreate worker (см. Шаг 4) → проверить `pool_health`.
4. На телефоне **старого** аккаунта:
   Telegram → Settings → Devices → найти сессию → Terminate Session.

---

### Анти-бан гигиена

- **Номера:** не из одноразовых SMS-сервисов (аккаунты банятся чаще, ре-логин теряется).
  Используй физические SIM или надёжного виртуального оператора — решает владелец.
- **Прогрев:** новый аккаунт должен быть не «только что созданным» — возраст несколько дней,
  заполненный профиль (имя, аватар); без массовых действий в первые дни.
- **Нагрузка:** не добавлять 2 новых аккаунта в один день под нагрузкой
  (FLOOD_WAIT на «холодных» аккаунтах выше — pool справится, но лучше постепенно).
- **Только чтение:** аккаунты читают ТОЛЬКО публичные каналы. Не вступают в группы массово,
  не пишут сообщения (ToS §2/§7, ADR-001).
- **FLOOD_WAIT:** норма при активном чтении — backoff (2s→300s exponential) разрулит сам.
  Не паниковать, не ротировать аккаунт из-за одного FLOOD_WAIT.
- **Сессии локально:** скрипт запускается локально (не на VPS). На VPS едет только
  зашифрованный vault → StringSession в env процесса. Так обходится datacenter-IP ban
  при первичном логине.
- **Осознанный риск:** collector работает с одного VPS-IP (без per-account прокси).
  Для READ-ONLY MTProto это штатно (так работают TGStat и аналоги).
  Per-account прокси — TASK-054 (P1 «навсегда»).
</content>
