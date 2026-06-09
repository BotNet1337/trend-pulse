# TrendPulse — Tasks Index

Surgical-change task docs produced by `trendpulse-plan` / `trendpulse-executor`.
One row per `task-NNN-slug.md`. Newest at the bottom.

Roadmap: [`../architecture/roadmap.md`](../architecture/roadmap.md). Epic A = Backend core (все done); эпики C (frontend SPA, TASK-013..017) и B (landing, TASK-018) — **done**. **Epic D = Hardening & growth** (TASK-019..033) — post-MVP волна: DX/CI, корректность скоринга, надёжность/observability, email/auth-completeness, монетизация (renewal/API-keys), SSR, API-hardening, второй источник (Twitter), security, GDPR-export.

| ID | Title | Epic | Status | Owner | Deps | Updated |
|----|-------|------|--------|-------|------|---------|
| [TASK-001](./task-001-dev-environment.md) | Dev environment — uv · Docker · `development/Makefile` · ruff/pytest | — | done | infra | — | 2026-06-08 |
| [TASK-002](./task-002-data-model.md) | Data model + миграции + multi-tenancy (pgvector) | A | done | backend | 001 | 2026-06-08 |
| [TASK-003](./task-003-auth.md) | Auth — email/пароль + Google OAuth, JWT | A | done | backend | 002 | 2026-06-08 |
| [TASK-004](./task-004-watchlist-api.md) | Watchlist CRUD API (каналы, топики, alert-config) | A | done | backend | 002, 003 | 2026-06-08 |
| [TASK-005](./task-005-collector-telegram.md) | Source abstraction + Telegram collector (пул, FLOOD_WAIT, dedup) | A | done | backend | 002 | 2026-06-08 |
| [TASK-006](./task-006-celery-infra.md) | Celery infra — app, beat, per-user queues, locks | A | done | backend | 002, 005 | 2026-06-08 |
| [TASK-007](./task-007-pipeline.md) | Pipeline — dedup→normalize→embed→cluster + batch | A | done | backend | 005, 006 | 2026-06-08 |
| [TASK-008](./task-008-scorer.md) | Scorer — velocity/engagement/cross_channel + alert trigger | A | done | backend | 007 | 2026-06-08 |
| [TASK-009](./task-009-alert-delivery.md) | Alert delivery — Telegram Bot + webhook | A | done | backend | 008, 003 | 2026-06-08 |
| [TASK-010](./task-010-billing-nowpayments.md) | Billing — крипто (NOWPayments) Free/Pro/Team + limits | A | done | backend | 003, 004 | 2026-06-08 |
| [TASK-011](./task-011-compliance-ops.md) | Compliance & ops — 48h retention, GDPR, rate-limit, observability | A | done | infra | 002, 005, 009 | 2026-06-08 |
| [TASK-012](./task-012-ops-iac.md) | Ops / IaC — Terraform (внешние сервисы) + Ansible (prod/secrets) | A | done | infra | 001 | 2026-06-08 |
| [TASK-013](./task-013-frontend-foundation.md) | Frontend foundation — SPA scaffold (дизайн-система, API-клиент, типы, e2e, Docker) | C | done | frontend | 001, 003 | 2026-06-09 |
| [TASK-014](./task-014-auth-flow-ui.md) | Auth flow UI — register/login/logout, Google OAuth, guard, current_user | C | done | frontend | 013, 003 | 2026-06-09 |
| [TASK-015](./task-015-watchlists-ui.md) | Watchlists UI — CRUD, alert-config, UX лимитов плана | C | done | frontend | 014, 004 | 2026-06-09 |
| [TASK-016](./task-016-alerts-ui.md) | Alerts UI — лента/история + детали (+ тонкий GET /alerts) | C | done | frontend | 014, 008, 009 | 2026-06-09 |
| [TASK-017](./task-017-billing-account-ui.md) | Billing & Account UI — план/инвойс/delivery-config/удаление (GDPR) | C | done | frontend | 014, 010, 009, 011 | 2026-06-09 |
| [TASK-018](./task-018-landing-base.md) | Landing base — hero/how-it-works/features/pricing/CTA/compliance | B | done | frontend | — | 2026-06-09 |
| [TASK-019](./task-019-api-dx-swagger-client-gen.md) | API DX — SWAGGER_ENABLE gating + офлайн OpenAPI-дамп + автоген фронт-клиента + удаление error-codes | D | done | backend | 013 | 2026-06-09 |
| [TASK-020](./task-020-alerts-cursor-pagination.md) | Alerts cursor-пагинация + composite index (user_id, first_seen) | D | done | backend | 016 | 2026-06-09 |
| [TASK-021](./task-021-ci-foundation.md) | CI foundation — корневые workflows + conftest alembic-изоляция + dep-scan + coverage-gate | D | done | infra | 001 | 2026-06-09 |
| [TASK-022](./task-022-scoring-correctness.md) | Scoring correctness — posts.cluster_id FK + per-cluster score + Score retention + горячие индексы | D | done | backend | 007, 008 | 2026-06-09 |
| [TASK-023](./task-023-reliability-pending-sweep.md) | Reliability — pending-sweep Beat + Celery /ready + alerts-by-status метрика | D | done | backend | 008, 009 | 2026-06-09 |
| [TASK-024](./task-024-observability-sentry-trace.md) | Observability — Sentry (FastAPI+Celery) + correlation/trace-id | D | planned | backend | 011 | 2026-06-09 |
| [TASK-025](./task-025-templates-email-service.md) | Templates service (порт из postbridge) + SMTP email-транспорт + mailpit + compose/provisioning | D | planned | infra | 001 | 2026-06-09 |
| [TASK-026](./task-026-auth-verify-reset.md) | Auth completeness — verify + reset-password роутеры + email/templates + фронт-страницы | D | planned | backend | 003, 014, 025 | 2026-06-09 |
| [TASK-027](./task-027-subscription-renewal-notifications.md) | Subscription renewal/expiry-уведомления (Beat + notifier/email) | D | planned | backend | 010, 009, 025 | 2026-06-09 |
| [TASK-028](./task-028-api-keys-team.md) | API-ключи для Team-плана (api_keys, issue/revoke, X-API-Key auth, rate-limit keying) | D | planned | backend | 003, 010 | 2026-06-09 |
| [TASK-029](./task-029-frontend-ssr-enablement.md) | Frontend SSR enablement (TanStack hydration, cookie-forward) + manualChunks | D | planned | frontend | 013, 014 | 2026-06-09 |
| [TASK-030](./task-030-api-hardening-errors-versioning.md) | API hardening — единый error-envelope + machine-readable коды + /api/v1 версионирование | D | planned | backend | 019 | 2026-06-09 |
| [TASK-031](./task-031-twitter-source.md) | Twitter/X source readiness (collector/twitter по ADR-001 + per-source лимиты) | D | planned | backend | 005 | 2026-06-09 |
| [TASK-032](./task-032-security-hardening.md) | Security hardening — per-route rate-limit + CSRF в nginx + at-rest шифрование (app-level, опц.) | D | planned | infra | 011, 012 | 2026-06-09 |
| [TASK-033](./task-033-gdpr-data-export.md) | GDPR data-export (GET /account/export, Art.20 portability) | D | planned | backend | 011 | 2026-06-09 |
