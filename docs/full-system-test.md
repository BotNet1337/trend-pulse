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

### B4. Billing — живой NOWPayments invoice (опц.)
Нужно: реальные `NOWPAYMENTS_API_KEY` + `NOWPAYMENTS_IPN_SECRET`.
```sh
# создать invoice (за current_user)
curl -s -b $JAR -X POST http://localhost/billing/invoice -H 'Content-Type: application/json' -d '{"plan":"pro","period":"month"}'
# → payment/redirect URL; оплатить тестовой криптой; NOWPayments пришлёт IPN на POST /billing/ipn
#   (IPN-эндпоинт должен быть достижим извне — за nginx/публичным доменом; локально — туннель)
# Проверить: после finished-IPN user.plan=pro, subscriptions.expires_at выставлен; повтор payment_id → без двойного продления.
```
HMAC-верификация IPN и idempotency покрыты integration-тестом (тест-секрет) в A2; живой прогон проверяет реальную доставку IPN от NOWPayments.

### B5. Google OAuth (живой) — опц.
Нужно: реальные `GOOGLE_CLIENT_ID/SECRET` + зарегистрированный redirect `…/auth/google/callback`. Flow в тестах замокан (A2); живой — браузером: `GET /auth/google/authorize` → Google → callback линкует/создаёт юзера.

### B6. Rate-limit вживую
```sh
for i in $(seq 1 130); do curl -s -o /dev/null -w "%{http_code} " http://localhost/health; done; echo
# после превышения RATE_LIMIT_PER_MINUTE (120/min) → 429
```

---

## C. Прод-провижининг (Terraform/Ansible, нужен cloud-аккаунт)

```sh
make tf-validate          # terraform validate (офлайн, без кред)
make ansible-lint         # ansible-lint ops/ansible
make ansible-check        # ansible-playbook --syntax-check / --check
```
Полный live-деплой (вне CI — нужен реальный DigitalOcean-токен + домен + VPS):
```sh
# terraform: настроить ops/terraform/terraform.tfvars (из *.example), TF_VAR_* / -backend-config с кредами
terraform -chdir=ops/terraform init && terraform -chdir=ops/terraform plan   # затем apply вручную
# ansible: реальный inventory prod-хоста + vault с реальными секретами
ansible-playbook ops/ansible/site.yml          # provision + deploy (clone source + version.env + compose up)
```
Firewall: только 443 (+80 redirect) + SSH-allowlist. `group_vars/prod.yml` ставит `auth_cookie_secure=true`.

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
| Prod IaC | `tf-validate`/`ansible-*` (валидация); `apply` (деплой) | DO-токен, домен, VPS |

Долг/ограничения для прода (см. `docs/learnings.md`): ротация засвеченного `api_hash`, пул тех-аккаунтов `POOL_MIN`→3, шифрование Telegram/OAuth токенов at-rest, отдельный rate-limit на `/billing` и `DELETE /account`, post↔cluster FK для точного per-cluster score, re-dispatch sweep для застрявших `pending` алертов, allowlist в лог-гигиене.
