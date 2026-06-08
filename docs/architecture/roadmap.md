# TrendPulse — Roadmap

Источник истины по продукту: [`../product/overview.md`](../product/overview.md). Архитектура: [`high-level-architecture.md`](./high-level-architecture.md). Фокус сейчас — **Backend core** (детальные таски). Landing (эпик B) и Frontend (эпик C) — эпики-заглушки, детализируются позже. Всё спроектировано так, что Twitter/X подключается как второй источник без переписывания ядра ([ADR-001](./adr-001-source-abstraction.md)).

## Epics

| Epic | Поток | Состояние планирования |
|---|---|---|
| **A** | Backend core | детальные таски (task-002 … task-012) |
| **B** | Landing (design + impl) | эпик-заглушка (ниже), таски позже |
| **C** | Frontend App (dashboard) | эпик-заглушка (ниже), таски позже |

`task-001` (dev environment) — фундамент, не входит в эпики, блокирует всё.

---

## Epic A — Backend core

Порядок отражает зависимости. Каждая задача — отдельный `task-NNN-*.md` (формат как task-001), `status: planned`, готова к `trendpulse-executor`.

| Task | Заголовок | Зависит от | Покрывает (overview / ADR) |
|---|---|---|---|
| task-001 | Dev environment (uv·Docker·make·ruff/pytest) | — | §8 |
| **task-002** | Data model + миграции + multi-tenancy (pgvector) | 001 | §4, §5, ADR-002, ADR-001(`source_kind`) |
| **task-003** | Auth — **fastapi-users** (email/пароль + Google OAuth, JWT) | 002 | §3, ADR-003 |
| **task-004** | Watchlist CRUD API (каналы, топики, alert-config) | 002, 003 | §3 |
| **task-005** | Source abstraction + Telegram collector (пул, FLOOD_WAIT, cross-tenant dedup) | 002 | §2, §7, ADR-001, ADR-002 |
| **task-006** | Celery infra — app, beat, per-user queues, scheduler, locks | 002, 005 | §4, §5, ADR-002 |
| **task-007** | Pipeline — dedup→normalize→embed→cluster + batch_processor | 005, 006 | §4 (pipeline) |
| **task-008** | Scorer — velocity/engagement/cross_channel + alert trigger | 007 | §4 (scorer) |
| **task-009** | Alert delivery — Telegram Bot API + webhook (Team) | 008, 003 | §3, §4, §6 |
| **task-010** | Billing — **крипто (NOWPayments)** Free/Pro/Team + enforcement лимитов | 003, 004 | §6, ADR-004 |
| **task-011** | Compliance & ops — 48h retention, GDPR delete, rate-limit, observability | 002, 005, 009 | §7 |
| **task-012** | Ops / IaC — Terraform (внешние сервисы) + Ansible (prod settings/defaults, доставка секретов) | 001 | ADR-005 |

**Критический путь до первого сигнала:** 001 → 002 → 005 → 006 → 007 → 008 → 009.
**Параллельно после 002:** 003 (auth) и 005 (collector) независимы; 004 после 003; 010 после 003/004.

### MVP «walking skeleton» (минимум до демо)

001 → 002 → 005 (Telegram read) → 006 (очереди/beat) → 007 (кластеры) → 008 (score) → 009 (Telegram-бот алерт). Auth/billing/dashboard можно дотачивать параллельно.

---

## Epic B — Landing (заглушка)

Папка `landing/` (React + Vite, SSG/static). Будущие таски (детализация позже):
- B1: design spec лендинга (бренд, ключевые экраны, copy, pricing-секция) — кандидат на `bmad-ux`.
- B2: scaffold `landing/` (Vite + React + Tailwind/UI-kit), деплой-конфиг.
- B3: реализация секций (hero с примером viral-alert, how-it-works, pricing, CTA/signup).
- B4: SEO/аналитика/метрики конверсии.

Зависимости: B1 после high-level arch (готово); B2+ независимы от backend (моки), интеграция signup → task-003.

## Epic C — Frontend App (заглушка)

Папка `frontend/` (Vite + React SPA). Будущие таски (детализация позже):
- C1: scaffold SPA (Vite+React+TS, роутинг, API-клиент к FastAPI, auth-флоу с JWT/refresh).
- C2: auth + onboarding UI (login/signup, Google OAuth).
- C3: watchlist management UI (каналы, топики, пороги) → task-004 API.
- C4: alerts dashboard + история → task-009 данные.
- C5: billing/upgrade UI (крипто-оплата, NOWPayments) → task-010.

Зависимости: C1 после task-001/ADR-003; C2 после task-003; C3 после task-004; C4 после task-008/009; C5 после task-010.

---

## Distribution (future — учитываем при проектировании)

Боты из `botnet/apps/*` (начиная с `trendPulse`) в будущем публикуются как OCI-артефакты через **ORAS** в `botnet/release`, который собирает один VPS-деплой. Не реализуем сейчас — но task-001/012 и образы держим переносимыми (12-factor, semver). См. [build-and-release.md](./build-and-release.md), [ADR-006](./adr-006-packaging-and-release.md).

## Принципы планирования

- Каждая backend-задача: TDD-якорь, реальная behavioral-проверка (G2), `trendpulse-security` где трогаются auth/secrets/OAuth/input/raw SQL.
- Source-agnostic ядро: pipeline/scorer не знают про платформу ([ADR-001](./adr-001-source-abstraction.md)); провайдеры за абстракциями (`SourceCollector`, `PaymentGateway`).
- Управление окружением — только через root `Makefile` (`make up`/`dev-infra-up`/`down`), сети сегментированы ([network-design.md](./network-design.md)), секреты из Ansible ([ADR-005](./adr-005-infra-provisioning-and-secrets.md)).
