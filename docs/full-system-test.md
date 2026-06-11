# TrendPulse — Full System Test Runbook

Что нужно сделать для **полного** (end-to-end) теста всей системы — поверх того, что
гоняется в CI. Делится на 3 уровня:

- **A. Автоматика без внешних кред** — `make ci-fast` + локальный стек + integration против реальных Postgres/Redis. Покрывает ~всё, кроме живых внешних API.
- **B. Живые внешние интеграции** — требуют реальных кред (Telegram-пул, NOWPayments, Google OAuth) и/или ML-стека.
- **C. Прод-провижининг** — Terraform `plan/apply` против реального провайдера (нужен VPS/cloud-аккаунт).

> Всё — через root `make` из `apps/trendPulse`. Инструменты: `uv`, Docker, (для ops) `terraform`/`ansible` (brew). Секреты — только в `development/env/sensitive.env` (материализуется Ansible, gitignored).

---

## 0. Предусловия

```sh
# 1. Материализовать env из Ansible (нужен ops/ansible/.vault-pass — dev vault-пароль, gitignored)
make ansible-unpack            # → development/env/{deploy.env,sensitive.env}

# 2. Реальные секреты для уровня B — вписать в development/env/sensitive.env (НЕ коммитить):
#    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_POOL_SESSIONS (см. development/scripts/README.md)
#    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET  (только для живого Google OAuth; flow в тестах замокан)
#    NOWPAYMENTS_API_KEY, NOWPAYMENTS_IPN_SECRET  (только для живого invoice; IPN в тестах подписывается тест-секретом)
#    JWT_SECRET / OAUTH_STATE_SECRET — для prod сгенерировать ≥32 байт высокоэнтропийные
```

---

## A. Автоматика (без внешних кред)

### A1. Статика + юнит-тесты (быстро, без БД/сети)
```sh
make ci-fast        # ruff format --check + ruff check + mypy --strict + pytest -m 'not integration'
```
Ожидаемо: всё зелёное (~230 unit), mypy strict без ошибок, `# type: ignore` нет.

### A2. Integration-тесты против реальных Postgres + Redis
В CI часть из них скипается без Redis/ML/Telegram. Для полного прогона подними инфру и прокинь её на хост:

```sh
make dev-infra-up   # postgres(healthy) + redis(healthy) + pg_vector_provisioner + migration_runner
make up             # полный стек (api/worker/beat/nginx)
```
Затем integration с реальными зависимостями. Postgres/Redis в compose **не публикуют host-портов** (изоляция), поэтому для host-прогона нужен либо эфемерный exposed Postgres/Redis, либо запуск pytest внутри сети. Самый простой путь — эфемерные контейнеры с проброшенным портом:

```sh
docker run -d --name tp-pg  -e POSTGRES_USER=trendpulse -e POSTGRES_PASSWORD=trendpulse -e POSTGRES_DB=trendpulse -p 55432:5432 pgvector/pgvector:pg16
docker run -d --name tp-rd  -p 56379:6379 redis:7
export POSTGRES_HOST=localhost POSTGRES_PORT=55432 POSTGRES_USER=trendpulse POSTGRES_PASSWORD=trendpulse POSTGRES_DB=trendpulse
export REDIS_URL=redis://localhost:56379/0
export JWT_SECRET=test-jwt-secret-at-least-32-bytes-xxxx OAUTH_STATE_SECRET=test-state-32-bytes-xxxx
export GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=x NOWPAYMENTS_IPN_SECRET=test NOWPAYMENTS_API_KEY=test

uv run --directory backend pytest -m integration --deselect tests/integration/test_run_batch.py
docker rm -f tp-pg tp-rd
```
Покрывает (без внешних кред): миграции 0001→0005 + pgvector, репозитории/каскад, auth-flow (register→login→cookie→logout, Google callback с моком), watchlist CRUD, scorer→alert (порог/topic/идемпотентность), alert delivery (фейк-webhook + мок Bot API), billing IPN (HMAC/replay/partial), GDPR account-cascade (no-orphans). `test_run_batch.py` (ML) — в уровне B.

### A3. Behavioral через nginx (живой стек)
При поднятом `make up`:
```sh
curl -s http://localhost/health        # 200 {"status":"ok"} (liveness)
curl -s http://localhost/ready         # 200 {"db":"ok","redis":"ok"} (readiness; 503 если зависимость недоступна)
# Auth: register → login (cookie) → protected → logout
JAR=$(mktemp)
curl -s -X POST http://localhost/auth/register -H 'Content-Type: application/json' -d '{"email":"e2e@example.com","password":"s3cret-pass-w0rd"}'
curl -s -c $JAR -X POST http://localhost/auth/jwt/login -d "username=e2e@example.com&password=s3cret-pass-w0rd"
curl -s -b $JAR http://localhost/users/me/tenant            # 200 {"user_id":N}
# Watchlist (за cookie): создать, лимит плана, чужой id → 404
curl -s -b $JAR -X POST http://localhost/watchlists -H 'Content-Type: application/json' \
  -d '{"topic":"ai","channel":{"handle":"@technews"},"alert_config":{"score_threshold":70,"min_channels":2,"notification_lang":"en"}}'
# GDPR: удалить аккаунт (каскад)
curl -s -b $JAR -X DELETE http://localhost/account          # 204
# Изоляция портов (AC task-001): только nginx публикует 80
make ps    # api/postgres/redis/worker/beat — без host-портов
```
Логи воркера/beat: `make logs` → `celery@… ready`, `beat: Starting`, `Sending due task enqueue-active-user-batches`.

---

## B. Живые внешние интеграции (нужны реальные креды/ML)

### B1. Telegram-коллектор (живое чтение публичного канала) — AC3 task-005
> **Prereq для live-TG прогона:** пул аккаунтов заполнен по runbook'у →
> [`development/scripts/README.md`](../development/scripts/README.md) §«Пул технических аккаунтов».

Нужно: `TELEGRAM_API_ID/HASH` + ≥1 session-строка тех-аккаунта в `TELEGRAM_POOL_SESSIONS` (см. `development/scripts/README.md`, `get-telegram-session.sh`).
```sh
# с пробросом креды из sensitive.env (POOL_MIN=1 — хватает одной dev-сессии)
TELEGRAM_API_ID=… TELEGRAM_API_HASH=… TELEGRAM_POOL_SESSIONS=… \
  uv run --directory backend pytest tests/integration/collector/ -v
```
Ожидаемо: `validate_ref(@telegram)`=True, `read` отдаёт ≥1 RawPost с норм. метриками. ⚠️ Compliance: только публичные каналы, только тех-аккаунты, уважать FLOOD_WAIT.

### B2. Pipeline с реальной моделью эмбеддингов — AC3/4/6 task-007
Нужно: ml-группа (torch + sentence-transformers, ~2GB; качает модель MiniLM ~90MB).
```sh
cd backend && uv sync --group ml && cd ..
# против реального Postgres (эфемерный, как в A2)
uv run --group ml --directory backend pytest tests/integration/test_run_batch.py -v
```
Ожидаемо: real embed→cluster→persist кластеров scoped по user_id; пустой буфер → no-op.

### B3. Celery worker гоняет ML-pipeline в проде
Воркер использует **отдельный ml-образ** (`APP_IMAGE_ML`, `INSTALL_ML=true`) — `make build` собирает его. Проверка, что воркер реально может эмбеддить:
```sh
make build && make up
docker exec development-worker-1 python -c "import sentence_transformers, torch; print('ml in worker OK')"
# Засеять буфер + триггернуть батч (нужен пользователь с watchlist; см. сценарий E2E ниже)
docker exec development-api-1 python -c "from pipeline.tasks import run_user_batch; print(run_user_batch.delay(<user_id>).id)"
make logs   # worker: run_user_batch start … succeeded
```

### B4. Billing — живой NOWPayments IPN + боевой платёж

> **Статус:** sandbox- и live-шаги выполняются владельцем после TASK-057 (HTTPS).
> Код-страховка (dual-verify + диагностика) реализована и покрыта тестами в рамках TASK-058.
> Шаги ниже — операционный runbook для владельца.

#### Предусловия

- TASK-057 выполнен: домен `foresignal.biz` с HTTPS, nginx проксирует `/api/billing/ipn`.
- Vault-пароль доступен в `ops/ansible/.vault-pass`.
- Vault-ключи уже объявлены: `vault_nowpayments_api_key`, `vault_nowpayments_ipn_secret`
  (`ops/ansible/roles/env/templates/sensitive.env.j2`).

#### Шаг 1. Создать NOWPayments-аккаунт и получить ключи

1. Зарегистрироваться на <https://nowpayments.io> (или <https://sandbox.nowpayments.io> для sandbox).
2. В дашборде: **Settings → API Keys** → создать API key → скопировать.
3. **Settings → IPN → IPN Secret** → создать/скопировать IPN secret.
4. IPN Callback URL: `https://foresignal.biz/api/v1/billing/ipn`
   (путь фиксирован: `/api` — nginx-префикс, `/v1/billing/ipn` — FastAPI-router).
   > **Найти IPN**: поддерживает ли `create_invoice`-payload поле `ipn_callback_url`?
   > По API-доке NOWPayments v1 (`/v1/invoice`) такого поля нет — callback задаётся
   > глобально в дашборде **Settings → IPN**. Если в будущем NOWPayments добавит
   > per-invoice callback — передавать через `nowpayments_ipn_callback_url` в settings.
5. KYC/верификация: при необходимости — пройти (может занять 1–2 дня).

#### Шаг 2. Записать секреты в Ansible Vault

```sh
# Редактировать vault (вводить vault-пароль из .vault-pass):
ansible-vault edit ops/ansible/group_vars/prod/vault.yml \
  --vault-password-file ops/ansible/.vault-pass

# Внутри файла — добавить/обновить (no_log: значения не печатать в логах!):
#   vault_nowpayments_api_key: "<api_key_из_dashboard>"
#   vault_nowpayments_ipn_secret: "<ipn_secret_из_dashboard>"

# Сохранить файл и выйти. Vault переписывает файл в зашифрованном виде.
```

> **no_log дисциплина**: никогда не echo/print секретов в терминале.
> Если случайно вывел — считать скомпрометированным, ротировать в дашборде.

#### Шаг 3. Задеплоить новые секреты на прод

```sh
make deploy
# или: ansible-playbook ops/ansible/site.yml --vault-password-file ops/ansible/.vault-pass
# Ansible рендерит sensitive.env.j2 → /app/sensitive.env на сервере, перезапускает api/worker.
```

Проверить, что переменные попали в контейнер (БЕЗ вывода значений):

```sh
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=api) env | grep -c NOWPAYMENTS"
# Ожидаем: 2 (NOWPAYMENTS_API_KEY + NOWPAYMENTS_IPN_SECRET)
```

#### Шаг 4. Sandbox-прогон (без реальных денег)

> **выполняется владельцем после TASK-057** — нужен HTTPS для IPN-доставки.

```sh
# 4.1 Временно переключить nowpayments_base_url на sandbox в vault:
#     vault_nowpayments_base_url: "https://api-sandbox.nowpayments.io/v1"
# (или передать через переменную окружения, если settings.py поддерживает override)

# 4.2 Залогиниться и создать invoice:
JAR=$(mktemp)
curl -s -X POST https://foresignal.biz/auth/jwt/login \
  -d "username=<email>&password=<pass>" -c $JAR
curl -s -b $JAR -X POST https://foresignal.biz/api/v1/billing/invoice \
  -H 'Content-Type: application/json' -d '{"plan":"pro","period":"month"}' | jq .

# 4.3 Перейти по payment_url → оплатить sandbox-монетой (NOWPayments sandbox UI).
# 4.4 В дашборде sandbox можно имитировать смену статуса: waiting → confirming → finished.

# 4.5 Смотреть: логи на сервере
ssh deploy@foresignal.biz "docker logs --since=5m \$(docker ps -qf name=api) | grep billing"
# Ожидаем: billing.ipn_received, (опц.) billing.ipn_canonical_mismatch, billing.plan_activated.

# 4.6 Проверить активацию:
curl -s -b $JAR https://foresignal.biz/api/v1/users/me | jq '{plan:.plan}'
# Ожидаем: {"plan":"pro"}

# 4.7 Replay — повторный finished IPN: 200, expires_at не меняется (idempotency).
```

#### Шаг 5. Боевой платёж

> **выполняется владельцем после TASK-057** — нужен HTTPS + боевой аккаунт NOWPayments.

```sh
# 5.1 Переключить vault_nowpayments_base_url обратно на prod:
#     vault_nowpayments_base_url: "https://api.nowpayments.io/v1"
# make deploy

# 5.2 Создать боевой invoice (оплатит реальной криптой — деньги придут на payout-кошелёк):
curl -s -b $JAR -X POST https://foresignal.biz/api/v1/billing/invoice \
  -H 'Content-Type: application/json' -d '{"plan":"pro","period":"month"}' | jq .

# 5.3 Перейти по payment_url, оплатить. Ожидать последовательность IPN:
#     waiting → confirming → finished (может занять 1–30 мин в зависимости от сети/монеты).

# 5.4 Что смотреть:
#   Логи (структурированный JSON):
ssh deploy@foresignal.biz "docker logs --follow --since=0m \$(docker ps -qf name=api) 2>&1 | grep -E 'billing\.(ipn|plan)'"
#   Sentry: Events → billing.ipn_canonical_mismatch (должен отсутствовать ИЛИ присутствовать — норма).
#   БД:
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=postgres) psql -U trendpulse -c \
  \"SELECT u.email, u.plan, s.expires_at, bp.status FROM users u \
    LEFT JOIN subscriptions s ON s.user_id=u.id \
    LEFT JOIN billing_payments bp ON bp.user_id=u.id \
    ORDER BY bp.created_at DESC LIMIT 5;\""

# 5.5 Replay idempotency: повторно POST того же IPN-тела с той же подписью:
#     Результат: 200, expires_at не изменился.
```

#### Шаг 6. Снятие redacted IPN-сэмпла (для AC4 / byte-fixture)

> **выполняется владельцем после боевого платежа** — нужны точные байты реального IPN.

```sh
# 6.1 В nginx access-логе или через sidecar-dump (tcpdump) перехватить тело POST /api/v1/billing/ipn.
# Или добавить временный debug-дамп в receive_ipn (ТОЛЬКО в dev-ветке, НЕ на проде без ревью):
#   logger.debug("raw_ipn_hex=%s", raw_body.hex())  — только hex, не base64, чтобы не было printable секретов

# 6.2 Redact: заменить чувствительные значения:
#   - payment_id: оставить структуру, заменить значение → "redacted-payment-id"
#   - order_id: оставить → значение реальное (наш internal id)
#   - адреса кошельков (pay_address, payin_extra_id): → "REDACTED"
#   - суммы price_amount/pay_amount: ОСТАВИТЬ (нужны для byte-fixture)
#   - payment_status: ОСТАВИТЬ ("finished")

# 6.3 Сохранить ТОЧНЫЕ байты (не re-dump!) в:
#   backend/tests/fixtures/nowpayments_ipn_finished.json
# Проверить, что sha256 совпадает с sha256 из canonical_mismatch-события в логах (если было).

# 6.4 Добавить integration-тест в test_billing_ipn_route.py:
#   def test_byte_fixture_ipn_accepted(client, ...):
#       raw = (FIXTURE_PATH / "nowpayments_ipn_finished.json").read_bytes()
#       sig = <подпись из реального IPN-запроса, также redacted-сохранить>
#       resp = client.post("/v1/billing/ipn", content=raw, headers={SIG_HEADER: sig})
#       assert resp.status_code == 200
# Если сигнатура canonical-path → тест зелёный; если fallback-path → тест зелёный И
# в логах billing.ipn_canonical_mismatch — документируем фактуру в Details TASK-058.
```

> **Все live-шаги (4–6) заблокированы: ждут NOWPayments-аккаунт владельца + прод (TASK-057).**

### B5. Google OAuth (живой) — опц.
Нужно: реальные `GOOGLE_CLIENT_ID/SECRET` + зарегистрированный redirect `…/auth/google/callback`. Flow в тестах замокан (A2); живой — браузером: `GET /auth/google/authorize` → Google → callback линкует/создаёт юзера.

### B6. Rate-limit вживую
```sh
for i in $(seq 1 130); do curl -s -o /dev/null -w "%{http_code} " http://localhost/health; done; echo
# после превышения RATE_LIMIT_PER_MINUTE (120/min) → 429
```

### B7. Showcase-канал — активация витрины и первый автопост (TASK-070)

> **Предусловие: TASK-057 (живой прод — worker/beat в swarm).** Код автопостинга
> (TASK-044) и proof-of-speed (TASK-045) уже в main; витрина выключена пустыми
> `SHOWCASE_BOT_TOKEN`/`SHOWCASE_CHANNEL_CHAT_ID` (no-op + warn-once — это штатно).
> Порядок шагов **канал → бот → vault** обязателен: vault до прав бота = мусорные
> pending-ретраи (допустимо, но грязно). Шаги 1–3 и 6 — **[owner]**.
> **Секрет-гигиена:** токен бота НИКОГДА не печатать (echo/printenv/логи) — vault-only.

#### Шаг 1 [owner]. Создать публичный канал

```
1. Telegram → New Channel → Public.
2. @username: @foresignal (дефолт); занят → @foresignal_pulse → @foresignal_signals
   → @foresignal_trends (по убыванию предпочтения, Discussion TASK-070).
3. Название: «Foresignal — early viral signals» (EN-only, бренд Foresignal).
4. Описание (EN, со ссылкой на сайт), например:
   "Early viral Telegram signals — detected up to 40 minutes before mainstream.
    Live feed by https://foresignal.biz"
5. Аватар бренда.
Выбранный @username зафиксировать: он идёт в vault (шаг 3) и в landing config (шаг 6) —
единственные два места.
```

#### Шаг 2 [owner]. Добавить бота админом

```
Бот = ops-бот (MVP-решение TASK-044: один бот, два чата; токен уже в vault как
vault_ops_telegram_bot_token). Отдельный бот — опционально (BotFather, 2 мин).

Канал → Administrators → Add Admin → выбрать бота → включить право «Post messages»
(остальные права не нужны).
```

#### Шаг 3 [owner]. Заполнить vault и проверить рендер

```sh
ansible-vault edit ops/ansible/vault/sensitive.vault.yml   # пароль из ops/ansible/.vault-pass
# Внутри (значения не печатать в логах):
#   vault_showcase_bot_token: "<значение vault_ops_telegram_bot_token или токен нового бота>"
#   vault_showcase_channel_chat_id: "@<username>"   # например "@foresignal"
#
# Альтернатива @username — численный id ("-100…"): переживает переименование канала,
# но требует discovery (переслать пост канала боту @userinfobot или getChat API).
# Для бренд-канала достаточно @username: переименование = осознанное событие
# (одна правка vault + deploy + landing config — см. шаг 6).

# Локальная проверка рендера (значения НЕ печатать):
make ansible-unpack
grep -c '^SHOWCASE_' development/env/sensitive.env
# Ожидаем: 2 (SHOWCASE_BOT_TOKEN + SHOWCASE_CHANNEL_CHAT_ID)
```

#### Шаг 4. Деплой и проверка env

```sh
make deploy   # swarm: compose config инлайнит env_file → stack deploy обновит worker/beat
              # без force-recreate (гочча M2 task-059 здесь не воспроизводится)

# chat_id — публичный @username, НЕ секрет; токен НЕ печатать:
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=worker) printenv SHOWCASE_CHANNEL_CHAT_ID"
# Ожидаем: @<username>

# Warn-once «showcase_autopost disabled — missing …» в логах worker ИСЧЕЗ после рестарта:
ssh deploy@foresignal.biz "docker logs --since=10m \$(docker ps -qf name=worker) 2>&1 | grep 'showcase_autopost disabled'"
# Ожидаем: пусто
```

#### Шаг 5. Первый автопост (AC2) — часы, не минуты

Beat тикает каждые 15 мин (`showcase_post_interval_seconds=900`), но пост требует
кандидата: score ≥85, возраст ≥40 мин, внутри 24h-окна, ≤8 постов/день (UTC).
При живом коллекторе это 0–8 постов/день — ждать до 24h это штатно.

```sh
# Лог-события тиков (log_event JSON): showcase_post_sent | showcase_autopost_skip | showcase_send_failed
ssh deploy@foresignal.biz "docker logs --since=1h \$(docker ps -qf name=worker) 2>&1 | grep -E 'showcase_(post_sent|autopost_skip|send_failed)'"

# Строка в БД (AC2): status=posted, posted_at заполнен
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=postgres) psql -U trendpulse -c \
  \"SELECT id, cluster_id, status, posted_at, created_at FROM showcase_posts ORDER BY id DESC LIMIT 5;\""

# В канале: пост «🔥 … · score N · обнаружено в HH:MM UTC» + CTA-ссылка содержит
# utm_source=tg_showcase&utm_campaign=autopost (кликнуть и проверить URL).
```

Нет поста за 24h при `degraded=false` — смотреть кандидатов, НЕ алармить и НЕ снижать
пороги (лестница ценности: delay 2400 > free 1800 — продуктовый инвариант TASK-044):
```sh
# 1) Здоровье пула коллектора (TASK-059): /api/ready + pool_health.
# 2) Кандидаты showcase-тенанта за 24h:
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=postgres) psql -U trendpulse -c \
  \"SELECT c.id, c.topic, s.viral_score, c.first_seen FROM clusters c \
    JOIN scores s ON s.cluster_id=c.id AND s.user_id=c.user_id \
    JOIN users u ON u.id=c.user_id AND u.email='showcase@internal' \
    WHERE c.first_seen >= now() - interval '24 hours' \
    ORDER BY s.viral_score DESC LIMIT 10;\""
# Пусто/все <85 → тихий день или деградация пула — чинить сбор, не пороги.
```

Диагностика ошибок отправки (механика ретраев TASK-044: pending остаётся, следующий
тик повторит сам — после фикса прав пост уйдёт без ручных действий):
- Bot API 403 → бот не админ / нет права «Post messages» (шаг 2);
- Bot API 400 «chat not found» → опечатка в `vault_showcase_channel_chat_id` →
  правка vault + `make deploy`.

#### Шаг 6 [owner]. Связать лендинг (AC5)

```sh
# Поле введено TASK-067; пустая строка = ссылки не рендерятся.
# В landing/public/config.json вписать:
#   "showcaseTelegramUrl": "https://t.me/<username>"
# Коммит (значение публичное, не секрет) → make deploy (пересборка landing-образа).

# Проверка: https://foresignal.biz — ссылка в hero («See live detections in Telegram»)
# и в footer (Product → «Telegram showcase»); переход t.me/<username> открывает канал.
```

#### Шаг 7. 48h-наблюдение — анти-спам (AC3) и лестница ценности (AC4)

```sh
# AC3: ≤8 постов/день (UTC), ни один кластер дважды (UNIQUE(cluster_id) — гарантия кода):
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=postgres) psql -U trendpulse -c \
  \"SELECT date_trunc('day', posted_at) AS day_utc, count(*) FROM showcase_posts \
    WHERE status='posted' GROUP BY 1 ORDER BY 1 DESC;\""
# Ожидаем: count ≤ 8 в каждом дне; интервал между постами ≥ ~15 мин (тик beat).

# AC4: штамп «обнаружено в HH:MM» в посте = first_seen кластера; сам пост публикуется
# на ≥40 мин позже (posted_at − first_seen ≥ 40 мин) — канал медленнее Free-плана.
# Выборочно сверить 2–3 поста (lag + штамп в канале == first_seen из БД):
ssh deploy@foresignal.biz "docker exec \$(docker ps -qf name=postgres) psql -U trendpulse -c \
  \"SELECT sp.cluster_id, c.first_seen, sp.posted_at, sp.posted_at - c.first_seen AS lag \
    FROM showcase_posts sp JOIN clusters c ON c.id=sp.cluster_id \
    WHERE sp.status='posted' ORDER BY sp.posted_at DESC LIMIT 3;\""
# Ожидаем: lag ≥ 40 минут у каждого.
```

**Откат:** очистить `vault_showcase_bot_token`/`vault_showcase_channel_chat_id`
(`ansible-vault edit`) → `make deploy` → автопостинг = no-op (пустые креды валидны,
AC4 TASK-044); ссылку на лендинге убрать пустой строкой в `showcaseTelegramUrl`.

---

## C. Прод-провижининг (Terraform/Ansible, нужен cloud-аккаунт)

```sh
make tf-validate          # terraform validate (офлайн, без кред)
make ansible-lint         # ansible-lint ops/ansible
make ansible-check        # ansible-playbook --syntax-check / --check
```
Офлайн-валидация прод-бандла (TASK-057, без VPS):
```sh
make -C release validate          # env-файлы есть, docker жив, swarm active (падает с подсказкой)
make -C release render | docker compose -f - config -q   # рендер парсится (метод валидации; --dry-run у stack deploy нет)
make deploy                       # без inventory/prod.yml → падает с «скопируй prod.example.yml»
```
Полный live-деплой (вне CI — нужен реальный VPS + домен + заполненный vault):
```sh
# 1. terraform создаёт VPS (ops/terraform/environments/prod), отдаёт server_ip
# 2. впиши IP/домен/ssh-ключ в inventory:
cp ops/ansible/inventory/prod.example.yml ops/ansible/inventory/prod.yml   # → отредактировать
# 3. одна команда: provision (Docker + swarm init + ufw) → release-бандл через
#    docker stack deploy → миграции (swarm jobs) → TLS (certbot) → showcase-init → smoke
make deploy                       # = ansible-playbook site.yml -l prod -i inventory/prod.yml
# CD: то же самое по git-тегу — git tag vX.Y.Z && git push origin vX.Y.Z → deploy-tag.yml
```
Прод = swarm-стек `trendpulse`: `docker stack services trendpulse` (replicated running
+ jobs Complete), `docker stack ps trendpulse` (образы `:vX.Y.Z`). Повторный
`make deploy` идемпотентен (декларативная сходимость, не re-up); rolling-update с
автооткатом (`update_config: order: start-first` / `failure_action: rollback`).
Firewall: только 22/80/443 (ufw). `group_vars/prod.yml` ставит `auth_cookie_secure=true`,
`swagger_enable=false`. Smoke: `make smoke HOST=https://foresignal.biz` (или последняя
таска playbook — фейл = фейл деплоя).

---

### C1. Внешний uptime-мониторинг (TASK-060)

> **Предусловие: TASK-057 (живой домен foresignal.biz с HTTPS) должен быть выполнен.**
> Создавать монитор до деплоя смысла нет — будет красным с первого дня.
> Email-routing (Terraform) применяется сразу, независимо от 057.

#### C1.1 Email Routing — применить Terraform

```sh
# 1. Заполнить ops/terraform/environments/org/terraform.tfvars (из *.example):
#    email_routes = {
#      support  = "owner@your-real-mailbox.com"
#      privacy  = "owner@your-real-mailbox.com"
#      abuse    = "owner@your-real-mailbox.com"
#      security = "owner@your-real-mailbox.com"
#    }
#    email_catch_all_destination = "owner@your-real-mailbox.com"
#    cloudflare_api_token  = "<token>"
#    cloudflare_account_id = "<account_id>"
#
# 2. Применить:
export PATH=/opt/homebrew/bin:$PATH
cd ops/terraform/environments/org
terraform init
terraform plan   # убедиться: только additive (add), без destroy/change в существующих ресурсах
terraform apply -target=module.email_routing

# 3. После apply — подтвердить destination-адрес:
#    Cloudflare Email Routing требует верификацию destination-адреса по email.
#    Откройте почту владельца → найдите письмо от Cloudflare → нажмите "Verify email address".
#    Без верификации routing не работает.

# 4. Проверить идемпотентность:
terraform plan   # Ожидаемо: "No changes."
```

#### C1.2 Создать монитор UptimeRobot

> Выполняется один раз после TASK-057. Описание сохраняется как runbook для воспроизведения.

```
1. Зарегистрироваться / войти: https://uptimerobot.com
2. Dashboard → "+ Add New Monitor"
3. Monitor Type: HTTP(s)
4. Friendly Name: foresignal.biz /api/ready
5. URL: https://foresignal.biz/api/ready
   (nginx strips /api/ → backend видит GET /ready; ответ 200 = all deps ok, 503 = degraded)
6. Monitoring Interval: 5 minutes (free tier)
7. Alert Contacts: добавить email владельца + Telegram (см. C1.3)
8. Save → монитор должен перейти в "Up" (зелёный) в течение 5 мин.
```

#### C1.3 Alert contacts — email + Telegram

```
Email:
  Dashboard → "Alert Contacts" → "+ Add Alert Contact"
  → Type: E-mail → введите email владельца → Save → подтвердить письмо.

Telegram:
  Dashboard → "Alert Contacts" → "+ Add Alert Contact"
  → Type: Telegram
  → Следовать инструкции: найти @UptimeRobot в Telegram → /start → получить chat_id
  → Ввести chat_id → Save.
```

#### C1.4 Тест down/recovery — AC1/AC2

> Выполняется в окне деплоя (допустим кратковременный down).

```sh
# Контролируемый останов стека на прод-сервере:
ssh deploy@foresignal.biz "cd /app && make -C release down"

# Ожидаемо в течение ≤10 мин: алерт "DOWN" в Telegram и на email.

# Поднять обратно:
ssh deploy@foresignal.biz "cd /app && make -C release up"

# Ожидаемо: алерт "UP (Recovery)" в Telegram и на email.
```

**AC2 — 503 (деградация зависимости):**
```sh
# Остановить Redis на сервере (контейнер):
ssh deploy@foresignal.biz "docker stop \$(docker ps -qf name=redis)"

# GET /api/ready → 503 → монитор считает down → алерт.
# Восстановить:
ssh deploy@foresignal.biz "docker start \$(docker ps -aqf name=redis)"
```

#### C1.5 Тест email-routing — AC3

```sh
# Отправить письмо с внешнего ящика (не owner@) на каждый адрес:
#   support@foresignal.biz
#   privacy@foresignal.biz
#   abuse@foresignal.biz
#   security@foresignal.biz
#
# Ожидаемо: письмо приходит на ящик владельца в течение ≤5 мин.
# Если письмо не пришло — проверить шаг верификации destination (C1.1 п.3).
```

#### C1.6 Обновление destination-адреса владельца

Если адрес назначения меняется:
```sh
# 1. Обновить ops/terraform/environments/org/terraform.tfvars:
#    email_routes = { support = "new-owner@mailbox.com", ... }
#    email_catch_all_destination = "new-owner@mailbox.com"
# 2. terraform apply -target=module.email_routing  (только email-routing — additive)
# 3. Подтвердить новый destination-адрес по email от Cloudflare (см. C1.1 п.3).
```

> **Заметка для TASK-032 (rate-limit):** `/api/ready` должен оставаться вне жёстких rate-limit правил
> (UptimeRobot шлёт с пула IP; 1 запрос/5 мин — ничтожно против глобального лимита 120/min).

---

## Полный E2E-сценарий «один пользователь от регистрации до алерта»
1. `make ansible-unpack && make dev-infra-up && make up` (+ ml-worker-образ для эмбеддинга).
2. register → login (cookie).
3. создать watchlist на реальный публичный канал + topic + порог.
4. (B1 креды) collector прочитал канал → RawPost'ы в Redis-буфере (beat дёргает сбор).
5. beat → `run_user_batch` → pipeline (dedup→normalize→embed→cluster) → кластеры в Postgres.
6. beat → `score_tick` → score > порога + topic-match → строка `alert` (идемпотентно).
7. `dispatch_alert` → доставка в Telegram-бот юзера и/или webhook; `delivery_status=delivered`.
8. (опц. B4) апгрейд плана через NOWPayments invoice → IPN → `plan=pro`, лимиты выросли.
9. retention: спустя 48h sweep обнуляет сырой текст постов; `DELETE /account` каскадно чистит всё.

---

## Что покрыто чем (резюме)
| Слой | Команда | Внешние креды |
|---|---|---|
| Static + unit | `make ci-fast` | нет |
| Integration (Postgres+Redis) | `pytest -m integration` (+ эфемерные БД) | нет (Google/NOWPayments замоканы) |
| Behavioral через nginx | `make up` + curl | нет |
| Telegram live read | `pytest tests/integration/collector` | TELEGRAM_* |
| ML pipeline | `pytest test_run_batch.py` (`--group ml`) | нет (качает модель) |
| Billing live IPN | `/billing/invoice` + реальный IPN | NOWPAYMENTS_* |
| Google OAuth live | браузер | GOOGLE_CLIENT_* |
| Showcase-канал live | runbook §B7 (vault → deploy → наблюдение) | SHOWCASE_* (vault) |
| Prod IaC | `tf-validate`/`ansible-*` (валидация); `apply` (деплой) | DO-токен, домен, VPS |

Долг/ограничения для прода (см. `docs/learnings.md`): ротация засвеченного `api_hash`, пул тех-аккаунтов `POOL_MIN`→3, шифрование Telegram/OAuth токенов at-rest, отдельный rate-limit на `/billing` и `DELETE /account`, post↔cluster FK для точного per-cluster score, re-dispatch sweep для застрявших `pending` алертов, allowlist в лог-гигиене.
