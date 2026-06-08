# TrendPulse — Tasks Index

Surgical-change task docs produced by `trendpulse-plan` / `trendpulse-executor`.
One row per `task-NNN-slug.md`. Newest at the bottom.

Roadmap: [`../architecture/roadmap.md`](../architecture/roadmap.md). Epic A = Backend core (детальные таски ниже); эпики B (landing) / C (frontend) — заглушки в roadmap, детализируются позже.

| ID | Title | Epic | Status | Owner | Deps | Updated |
|----|-------|------|--------|-------|------|---------|
| [TASK-001](./task-001-dev-environment.md) | Dev environment — uv · Docker · `development/Makefile` · ruff/pytest | — | done | infra | — | 2026-06-08 |
| [TASK-002](./task-002-data-model.md) | Data model + миграции + multi-tenancy (pgvector) | A | done | backend | 001 | 2026-06-08 |
| [TASK-003](./task-003-auth.md) | Auth — email/пароль + Google OAuth, JWT | A | done | backend | 002 | 2026-06-08 |
| [TASK-004](./task-004-watchlist-api.md) | Watchlist CRUD API (каналы, топики, alert-config) | A | done | backend | 002, 003 | 2026-06-08 |
| [TASK-005](./task-005-collector-telegram.md) | Source abstraction + Telegram collector (пул, FLOOD_WAIT, dedup) | A | done | backend | 002 | 2026-06-08 |
| [TASK-006](./task-006-celery-infra.md) | Celery infra — app, beat, per-user queues, locks | A | done | backend | 002, 005 | 2026-06-08 |
| [TASK-007](./task-007-pipeline.md) | Pipeline — dedup→normalize→embed→cluster + batch | A | done | backend | 005, 006 | 2026-06-08 |
| [TASK-008](./task-008-scorer.md) | Scorer — velocity/engagement/cross_channel + alert trigger | A | planned | backend | 007 | 2026-06-08 |
| [TASK-009](./task-009-alert-delivery.md) | Alert delivery — Telegram Bot + webhook | A | planned | backend | 008, 003 | 2026-06-08 |
| [TASK-010](./task-010-billing-nowpayments.md) | Billing — крипто (NOWPayments) Free/Pro/Team + limits | A | planned | backend | 003, 004 | 2026-06-08 |
| [TASK-011](./task-011-compliance-ops.md) | Compliance & ops — 48h retention, GDPR, rate-limit, observability | A | planned | infra | 002, 005, 009 | 2026-06-08 |
| [TASK-012](./task-012-ops-iac.md) | Ops / IaC — Terraform (внешние сервисы) + Ansible (prod/secrets) | A | planned | infra | 001 | 2026-06-08 |
