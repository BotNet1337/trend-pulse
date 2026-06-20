# development/ — окружение разработки

Dev-окружение управляется через `make up` (корневой `Makefile`). Compose-поверхность
собирается через `include:` в `development/docker-compose.yml` из per-service файлов
`development/compose/*`. Переменные — только из Ansible:
`make ansible-unpack` рендерит `development/env/deploy.env` и расшифровывает
`development/env/sensitive.env` из vault (ADR-005).

## Сервисы

| Сервис          | Compose-файл              | Назначение                                               |
|-----------------|---------------------------|----------------------------------------------------------|
| `postgres`      | `compose/postgres.yml`    | PostgreSQL + pgvector (база данных)                      |
| `redis`         | `compose/redis.yml`       | Redis (брокер Celery + кэш)                              |
| `api`           | `compose/api.yml`         | FastAPI-приложение (HTTP, edge → internal → api)         |
| `worker`        | `compose/worker.yml`      | Celery worker — очереди `celery,batch,score:global`      |
| `beat`          | `compose/beat.yml`        | Celery beat — планировщик периодических задач            |
| `account-factory` | `compose/account-factory.yml` | Celery worker — провижининг TG-аккаунтов (Layer B) |
| `frontend`      | `compose/frontend.yml`    | Next.js SPA (SSR)                                        |
| `nginx`         | `compose/nginx.yml`       | Reverse-proxy (edge, публикует 80/443)                   |
| `templates`     | `compose/templates.yml`   | Сервис email-шаблонов (internal, порт 3100)              |
| `mailpit`       | `compose/mailpit.yml`     | Catch-all SMTP для dev (не отправляет реальных писем)    |

Provisioning (one-shot перед стартом app):
- `provisioning/pg_vector_provisioner/` — `CREATE EXTENSION IF NOT EXISTS vector`
- `provisioning/migration_runner/` — `alembic upgrade head`

## account-factory (Layer B)

Отдельный Celery-worker, потребляющий очередь `celery` по умолчанию (ту же, что
и основной `worker`). Celery доставляет каждую задачу ровно одному потребителю —
дублирования нет. Воркер исполняет Beat-задачу `factory_tick` (раз в час по умолчанию):
проверяет уровень пула технических TG-аккаунтов и докупает новые при нехватке.

### Модель безопасности

- **USD hard-cap** (`ACCOUNT_FACTORY_BUDGET_USD`): кумулятивный лимит расходов.
  Значение `"0.00"` отклоняет любую покупку, даже если провайдер настроен.
- **Испытательный срок** (`ACCOUNT_FACTORY_PROBATION_DAYS`): новый аккаунт проходит
  warm-up перед попаданием в live-пул. Значение по умолчанию — 14 дней.

### Provider-gating — управление через ACCOUNT_FACTORY_PROVIDER

| Значение   | Поведение                                                      |
|------------|----------------------------------------------------------------|
| `""` / не задан | **No-op tick** — задача завершается мгновенно без вызовов SMSPVA. Дефолт в prod. |
| `fake`     | **Dev-режим** — полная логика тика без сетевых запросов (CI-friendly). Дефолт в dev. |
| `smspva`   | **Реальный провижининг** — требует `SMSPVA_API_KEY` в vault и `ACCOUNT_FACTORY_BUDGET_USD > 0`. |

### Переменные окружения

| Переменная                              | Где задаётся  | Описание                                          |
|-----------------------------------------|---------------|---------------------------------------------------|
| `ACCOUNT_FACTORY_PROVIDER`              | `deploy.env`  | Провайдер: `""` / `fake` / `smspva`              |
| `ACCOUNT_FACTORY_BUDGET_USD`            | `deploy.env`  | Кумулятивный лимит расходов (USD)                 |
| `ACCOUNT_FACTORY_PROBATION_DAYS`        | `deploy.env`  | Дней испытательного срока перед входом в пул      |
| `ACCOUNT_FACTORY_COUNTRY`              | `deploy.env`  | Страна для номера телефона (SMSPVA, напр. `RU`)   |
| `ACCOUNT_FACTORY_PRICE_USD`            | `deploy.env`  | Ожидаемая цена за аккаунт (USD, проверка)         |
| `ACCOUNT_FACTORY_TICK_INTERVAL_SECONDS` | `deploy.env`  | Период тика в секундах (по умолчанию `3600`)      |
| `ACCOUNT_FACTORY_PROXY_POOL`           | `deploy.env`  | Прокси для регистрации (пусто = прямое соединение)|
| `SMSPVA_API_KEY`                        | `sensitive.env` / vault | API-ключ SMSPVA — **секрет**          |

Реальный провижининг (`smspva`) требует egress: SMSPVA HTTPS + Telegram MTProto
для регистрации. В dev и без провайдера egress не используется.

### Включение proxy-провайдера (TASK-142)

По умолчанию account-factory использует **статический пул прокси** (`ACCOUNT_FACTORY_PROXY_POOL`
из deploy.env, пусто = прямое соединение). Для активации **динамического выделения proxy**
(Mobileproxy.space — мобильный SOCKS5, low-ban, sticky weeks):

1. В `ops/ansible/inventory/group_vars/prod.yml` выставить:
   ```yaml
   account_factory_proxy_provider: "mobileproxy"
   account_factory_proxy_price_usd: "33.00"   # бюджет-guard за 1 прокси (USD)
   account_factory_health_probe_channel: "@telegram"  # канал для health-probe перед promote
   ```
2. Добавить API-токен Mobileproxy.space в vault:
   ```bash
   ansible-vault edit ops/ansible/vault/sensitive.vault.yml
   # добавить: vault_mobileproxy_api_token: "<токен>"
   ```
3. Задеплоить: `make deploy`.

Таблица провайдеров:

| Значение | Поведение |
|---|---|
| `""` / не задан | **Статический пул** / no-op (дефолт в prod). `ACCOUNT_FACTORY_PROXY_POOL` используется напрямую. |
| `fake` | **Dev-режим** — полная логика без сетевых вызовов (CI-safe). Дефолт в dev. |
| `mobileproxy` | **Mobileproxy.space** — `buyProxy`/`refundProxy` API; требует `MOBILEPROXY_API_TOKEN` в vault. |

**Взаимодействие с бюджетом:** `ACCOUNT_FACTORY_PROXY_PRICE_USD` — guard на стоимость одного
прокси-слота. `"0.00"` отклоняет каждое выделение даже при включённом провайдере. Dev-дефолт
намеренно `"0.00"`. Raise выше реальной цены ($33+ для Mobileproxy.space) для активации.

**Sticky / один-proxy-per-account:** провайдер выделяет один мобильный IP per аккаунт на весь
срок жизни (probation + live-пул). `changeIp` НЕ вызывается — IP меняется только при
явном `release`/`refund`. Это обязательное условие — смена IP в середине сессии разрушает MTProto.

**Misconfig fail-fast:** `ACCOUNT_FACTORY_PROXY_PROVIDER=mobileproxy` без токена →
`FactoryError` при первом `allocate()`. Задокументировано в edge-cases TASK-142.

### Переменные окружения (полная таблица с proxy)

| Переменная | Где задаётся | Описание |
|---|---|---|
| `ACCOUNT_FACTORY_PROVIDER` | `deploy.env` | SMS-провайдер: `""` / `fake` / `smspva` |
| `ACCOUNT_FACTORY_BUDGET_USD` | `deploy.env` | Кумулятивный лимит расходов (USD, SMS) |
| `ACCOUNT_FACTORY_PROBATION_DAYS` | `deploy.env` | Дней испытательного срока |
| `ACCOUNT_FACTORY_COUNTRY` | `deploy.env` | Страна для номера телефона (напр. `RU`) |
| `ACCOUNT_FACTORY_PRICE_USD` | `deploy.env` | Ожидаемая цена за аккаунт (USD, проверка) |
| `ACCOUNT_FACTORY_TICK_INTERVAL_SECONDS` | `deploy.env` | Период тика (сек, дефолт `3600`) |
| `ACCOUNT_FACTORY_PROXY_POOL` | `deploy.env` | Статический SOCKS5 прокси (пусто = прямое) |
| `ACCOUNT_FACTORY_PROXY_PROVIDER` | `deploy.env` | Proxy-провайдер: `""` / `fake` / `mobileproxy` |
| `ACCOUNT_FACTORY_PROXY_PRICE_USD` | `deploy.env` | Guard-цена за 1 прокси-слот (USD) |
| `ACCOUNT_FACTORY_HEALTH_PROBE_CHANNEL` | `deploy.env` | TG-канал для pre-promote health probe |
| `SMSPVA_API_KEY` | `sensitive.env` / vault | API-ключ SMSPVA — **секрет** |
| `MOBILEPROXY_API_TOKEN` | `sensitive.env` / vault | Bearer-токен Mobileproxy.space — **секрет** |
