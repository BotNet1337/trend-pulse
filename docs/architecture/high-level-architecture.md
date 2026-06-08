# TrendPulse — High-Level Architecture

> Персональный детектор вирусного контента. Мониторит публичные источники (сейчас — Telegram-каналы), кластеризует похожие новости across источников, считает viral score и шлёт сигнал быстрее мейнстрима.

Status: **architecture baseline (Pre-MVP)** · Источник истины: [`../product/overview.md`](../product/overview.md)
ADRs: [001 source-abstraction](./adr-001-source-abstraction.md) · [002 multi-tenancy](./adr-002-multi-tenancy-and-queues.md) · [003 monorepo+auth](./adr-003-monorepo-and-auth.md) · [004 crypto-billing](./adr-004-crypto-billing-nowpayments.md) · [005 infra+secrets](./adr-005-infra-provisioning-and-secrets.md) · [006 packaging/ORAS](./adr-006-packaging-and-release.md)
Связанное: [network-design.md](./network-design.md) · [build-and-release.md](./build-and-release.md) · [roadmap.md](./roadmap.md)

---

## 1. System context (C4 L1)

```mermaid
flowchart LR
    user([User · browser]):::ext
    tg[(Telegram public channels)]:::ext
    tgbot([Telegram bot / user]):::ext
    hook[[Team webhook / Slack]]:::ext
    pay([NOWPayments<br/>Solana · ETH · TON]):::ext

    subgraph TP[TrendPulse]
        landing[landing]
        frontend[frontend SPA]
        backend[backend<br/>API · collector · pipeline · scorer · alerts · billing]
    end

    user -->|HTTPS| landing
    user -->|HTTPS| frontend
    frontend -->|REST| backend
    backend <-->|MTProto · account pool| tg
    backend -->|Bot API| tgbot
    backend -->|webhook| hook
    backend <-->|invoice + IPN| pay

    classDef ext fill:#eee,stroke:#999,color:#333;
```

**Future sources** (Twitter/X и др.) подключаются через единый `SourceCollector` — [ADR-001](./adr-001-source-abstraction.md). Сейчас реализован только Telegram; ядро source-agnostic.

## 2. Apps (monorepo `apps/trendPulse/`)

| App | Stack | Назначение |
|---|---|---|
| `backend/` | Python 3.12 · FastAPI · Celery+Redis · SQLAlchemy+pgvector | API, сбор, pipeline, scoring, alerts, billing |
| `landing/` | React + Vite (SSG/static) | Маркетинговый лендинг, конверсия, pricing |
| `frontend/` | Vite + React SPA | Дашборд: watchlist, история алертов, биллинг |
| `development/` | **root `Makefile`** + per-service compose + provisioning | Единый оркестратор окружения ([ADR-005](./adr-005-infra-provisioning-and-secrets.md)) |
| `ops/` | Terraform + Ansible | IaC внешних сервисов + доставка секретов |

## 3. Component diagram (C4 L2) — backend + инфраструктура

```mermaid
flowchart TB
    nginx["nginx (edge)\nTLS · rate-limit · security headers"]

    subgraph app[Backend — пакет trendpulse]
        api["api/ — FastAPI\nauth · watchlist · alerts · billing · webhook · health"]
        collector["collector/ — SourceCollector\nTelegram (account pool, FLOOD_WAIT rotate)"]
        pipeline["pipeline/ — dedup→normalize→embed→cluster\nbatch_processor"]
        scorer["scorer/ — velocity·engagement·cross_channel\nalert trigger"]
        alerts["alerts/ — Telegram Bot + webhook"]
        billing["billing/ — PaymentGateway (NOWPayments)\nlimits"]
        storage["storage/ — SQLAlchemy models · repos · redis_client"]
    end

    beat["Celery Beat\nenqueue batch:user_id (1m) · scorer tick (5m)"]
    pg[("PostgreSQL + pgvector")]
    redis[("Redis\nbroker · per-source buffers · locks")]

    nginx -->|internal| api
    api --> storage
    billing --> storage
    api -. enqueue .-> redis
    beat --> redis
    redis --> pipeline
    collector --> redis
    pipeline --> storage
    pipeline --> scorer
    scorer --> storage
    scorer --> alerts
    storage --> pg
    collector -. read .-> redis
```

Доменные модули пакета `trendpulse` (src-layout `backend/src/trendpulse/`):

| Module | Отвечает за |
|---|---|
| `api/` | HTTP-роуты, Pydantic-схемы, auth (fastapi-users), зависимости |
| `collector/` | `SourceCollector` + Telegram-реализация, пул аккаунтов |
| `pipeline/` | pure-steps `dedup → normalize → embed → cluster`, `batch_processor` |
| `scorer/` | viral score, alert-триггер по порогу пользователя |
| `alerts/` | доставка (Telegram Bot API, webhook) |
| `billing/` | `PaymentGateway` (NOWPayments), тарифы, лимиты |
| `storage/` | SQLAlchemy-модели, репозитории, Redis-клиент, миграции |
| `config.py` · `celery_app.py` · `scheduler.py` | настройки, Celery app, beat schedule |

## 4. User flow (что делает пользователь)

```mermaid
sequenceDiagram
    actor U as User
    participant F as frontend SPA
    participant A as API (FastAPI)
    participant DB as Postgres
    participant N as alerts/notifier
    participant TG as Telegram bot

    U->>F: регистрация (email / Google OAuth)
    F->>A: POST /auth (fastapi-users)
    A->>DB: create user
    A-->>F: JWT (httpOnly cookie)
    U->>F: создать watchlist (@channels + topic + threshold)
    F->>A: POST /watchlist  (Bearer/cookie)
    A->>DB: watchlist rows (user_id-scoped)
    Note over A,DB: billing/limits проверяет лимиты плана
    U->>F: апгрейд плана (Pro/Team)
    F->>A: POST /billing/invoice → NOWPayments
    Note over A: оплата крипто → IPN → план активирован
    loop фоновые циклы (Celery)
        N->>TG: 🔥 Viral alert [topic] score 94 · 47 каналов
        TG-->>U: уведомление
    end
    U->>F: история алертов / дашборд
    F->>A: GET /alerts
    A->>DB: read (user_id-scoped)
```

## 5. Data flow (как рождается сигнал)

```mermaid
flowchart LR
    chans[(Public channels)] -->|MTProto, pool| C[collector]
    C -->|RawPost, dedup cross-tenant| BUF[(Redis buffer<br/>TTL ≤ 48h)]
    BEAT[Celery Beat · 1m] -->|enqueue batch:user_id| Q{{per-user queue}}
    BUF --> Q
    Q --> B[batch_processor]
    subgraph P[pipeline · pure steps]
      D[dedup MinHash] --> NZ[normalize] --> E[embed sentence-BERT] --> CL[cluster cosine]
    end
    B --> P
    P -->|clusters · user_id| DB[(Postgres + pgvector)]
    SC[scorer · 5m] --> DB
    SC -->|score > threshold & topic match| AL[alert]
    AL --> NOT[notifier]
    NOT -->|Telegram Bot / webhook| OUT([User])
    DB -. retention purge 48h .-> DB
```

**Ключевые свойства потока:** канал читается один раз для всех тенантов (cross-tenant dedup, [ADR-002](./adr-002-multi-tenancy-and-queues.md)); pipeline-шаги работают только с нормализованным `RawPost`/`NormalizedPost` ([ADR-001](./adr-001-source-abstraction.md)) — платформо-независимы; сырой контент живёт ≤ 48h (overview §7).

Формула: `viral_score = velocity·0.4 + engagement·0.35 + cross_channel·0.25`.

## 6. Cross-cutting

- **Multi-tenancy.** Всё пользовательское изолировано по `user_id`; очереди per-user; источники дедуплицируются на уровне пула — [ADR-002](./adr-002-multi-tenancy-and-queues.md).
- **Source abstraction.** Новый источник = новая реализация `SourceCollector` — [ADR-001](./adr-001-source-abstraction.md).
- **Auth.** Библиотека `fastapi-users` (email/пароль + Google OAuth, JWT/cookie) — [ADR-003](./adr-003-monorepo-and-auth.md).
- **Billing.** Крипто через NOWPayments за абстракцией `PaymentGateway` — [ADR-004](./adr-004-crypto-billing-nowpayments.md).
- **Network/secrets.** Наружу только nginx; БД/Redis изолированы; env split + Ansible как источник истины — [network-design.md](./network-design.md), [ADR-005](./adr-005-infra-provisioning-and-secrets.md).
- **Rate limits.** `FLOOD_WAIT` → backoff + ротация аккаунтов пула.
- **Observability.** структурные логи (агрегированные метрики, не содержимое сообщений), health/ready.

## 7. Deployment & build (MVP → future)

Один образ приложения для `api`/`worker`/`beat` (различие — команда), за ним nginx (edge) и изолированные Postgres/Redis. Сборка/провижининг/старт-ордер и **будущая дистрибуция через ORAS в `release`-репо** — отдельный документ [build-and-release.md](./build-and-release.md). Управление — root `Makefile` (`make up` / `make dev-infra-up` / `make down`). Целевая инфра MVP — VPS (~$30–60/мес).

## 8. Tech risks → mitigations

| Риск | Mitigation |
|---|---|
| Telegram rate limits | пул технических аккаунтов, backoff, ротация (ADR-001/002) |
| ML-стек тяжёлый (torch) | dependency-group `ml` только в worker; api лёгкий |
| pgvector dimension drift | фиксированная размерность эмбеддинга в схеме + проверка |
| Гонки старта/тенантов | healthchecks; provisioning-ордер; `max_instances=1` на батч |
| Vendor lock (источник/платёж) | абстракции `SourceCollector` / `PaymentGateway` с первого дня |
| Связность деплоя многих ботов | OCI-артефакты + сборка одного VPS-бандла (ADR-006, build-and-release) |
