# TrendPulse — Network Design (Docker, local + prod)

> Цель: безопасная сегментация. Наружу торчит **только** reverse-proxy (nginx); приложение и инфраструктура изолированы по отдельным сетям; БД/Redis недоступны из интернета и не публикуют порты.

Связано: [high-level-architecture.md](./high-level-architecture.md), [adr-005-infra-provisioning-and-secrets.md](./adr-005-infra-provisioning-and-secrets.md).

## Принципы

1. **Edge — единственная точка входа.** Только `nginx` слушает публичные порты (80/443) и сидит в сети `edge`. Всё остальное портов наружу не публикует.
2. **API не в edge.** `api` (FastAPI) — в `internal`; доступен только из `nginx`. Снаружи к нему не достучаться напрямую.
3. **У каждого инфра-компонента своя сеть.** `postgres` → `postgres_net`, `redis` → `redis_net`. Доступ к БД/Redis имеет только тот, кому нужно (api/worker/beat/провижинеры), и только через соответствующую сеть.
4. **Least privilege.** Сервис подключён ровно к тем сетям, которые ему нужны. worker/beat не в `edge`. Провижинеры — только в `postgres_net`.
5. **Инфра поднимается отдельно** (`make dev-infra-up`) и переживает рестарты приложения.

## Сети

| Network | Кто в ней | Назначение | Внешний доступ |
|---|---|---|---|
| `edge` | `nginx` | приём трафика из интернета | **да** (80/443 published) |
| `internal` | `nginx`, `api` | proxy → api | нет |
| `postgres_net` | `postgres`, `api`, `worker`, `beat`, `migration_runner`, `pg_vector_provisioner` | доступ к БД | нет |
| `redis_net` | `redis`, `api`, `worker`, `beat` | брокер/буфер | нет |

`internal`, `postgres_net`, `redis_net` создаются как `internal: true` где возможно (без egress-маршрута наружу). Только `edge` публикует порты.

## Топология

```
                 Internet
                    │  :80 / :443
            ┌───────▼────────┐
            │     nginx      │   networks: edge, internal
            │ reverse proxy  │   (TLS termination, rate-limit, security headers)
            └───────┬────────┘
                    │ internal  (proxy_pass http://api:8000)
            ┌───────▼────────┐
            │      api       │   networks: internal, postgres_net, redis_net
            │   (FastAPI)    │   НЕ публикует порты
            └───┬────────┬───┘
       postgres_net   redis_net
            │              │
   ┌────────▼───┐    ┌─────▼─────┐        ┌──────────────┐  ┌──────────────┐
   │  postgres  │    │   redis   │        │   worker     │  │    beat      │
   │ (pgvector) │    │           │        │ (Celery)     │  │ (Celery)     │
   └────▲───────┘    └─────▲─────┘        └──┬────────┬──┘  └──┬───────────┘
        │ postgres_net      │ redis_net      │postgres│redis   │ postgres/redis
        │                                    └────────┴────────┘
   ┌────┴───────────────────────┐
   │ pg_vector_provisioner →    │  one-shot, postgres_net only, exit 0
   │ migration_runner           │
   └────────────────────────────┘
```

## Старт-ордер (depends_on + healthchecks)

```
redis (healthy) ─┐
postgres (healthy) ─► pg_vector_provisioner (completed) ─► migration_runner (completed) ─► api / worker / beat ─► nginx
```

- `postgres`, `redis` — с `healthcheck` (`pg_isready`, `redis-cli ping`).
- провижинеры — one-shot контейнеры; зависящие сервисы ждут `condition: service_completed_successfully`.
- `api`/`worker`/`beat` ждут healthy-инфру + успешные провижинеры; `nginx` ждёт `api`.

## Безопасность

- БД и Redis **никогда** не публикуют порты на хост (только внутри своих сетей).
- nginx: TLS-терминация, security-заголовки (HSTS, X-Content-Type-Options, frame-deny), rate-limit на уровне proxy (доп. к app-level из task-011), таймауты, ограничение размера тела.
- Секреты (пароли БД, ключи) — из `sensitive.env` (см. ADR-005), не в образах.
- prod: тот же сетевой дизайн; внешние порты только 443 (+80 redirect). Внешние сервисы (DNS, VPS, firewall) — через `ops/terraform`.

## Влияет на задачи

- **task-001** — определяет сети, nginx-сервис, изоляцию портов, старт-ордер.
- **task-003 / task-009 / task-010** — публичные эндпоинты только за nginx (edge), webhook-приёмники (NOWPayments IPN) — через proxy.
- **task-011** — rate-limit (proxy + app), без утечек.
