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
