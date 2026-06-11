# TrendPulse — Tasks Index

Surgical-change task docs produced by `trendpulse-plan` / `trendpulse-executor`.
One row per `task-NNN-slug.md`. Newest at the bottom.

Roadmap: [`../architecture/roadmap.md`](../architecture/roadmap.md). Epic A = Backend core, B = landing, C = frontend SPA, D = Hardening & growth (TASK-019..028) — **done**; хвост D: 029 in-progress, 030/032/033 перепривязаны к волне E, 031 — триггер $2k MRR. **Epic E = Path to revenue** (TASK-034..055) — текущая волна: ops-фундамент (E0), первая польза (E1), качество сигнала (E2), витрина (E3), деньги без трения (E4), цены (E5), бизнес-метрики (E6), масштаб (E7), новые рынки (E8). Полные планы: [`../product/epics/`](../product/epics/README.md); болевые точки: [`../architecture/pain-points.md`](../architecture/pain-points.md). Доки E2 (041–043), E3 (044–046), E5 (049) и E6 (050–051) готовы (planned); номера TASK-047..048 (E4) и 052..055 (E7) зарезервированы (док создаётся `trendpulse-plan` при взятии в работу). TASK-057 — прод-запуск на VPS (launch); TASK-058..060 — launch-gaps: боевой платёжный путь, TG-пул ≥3, внешний uptime + support.

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
| [TASK-024](./task-024-observability-sentry-trace.md) | Observability — Sentry (FastAPI+Celery) + correlation/trace-id | D | done | backend | 011 | 2026-06-09 |
| [TASK-025](./task-025-templates-email-service.md) | Templates service (порт из postbridge) + SMTP email-транспорт + mailpit + compose/provisioning | D | done | infra | 001 | 2026-06-09 |
| [TASK-026](./task-026-auth-verify-reset.md) | Auth completeness — verify + reset-password роутеры + email/templates + фронт-страницы | D | done | backend | 003, 014, 025 | 2026-06-09 |
| [TASK-027](./task-027-subscription-renewal-notifications.md) | Subscription renewal/expiry-уведомления (Beat + notifier/email) | D | done | backend | 010, 009, 025 | 2026-06-09 |
| [TASK-028](./task-028-api-keys-team.md) | API-ключи для Team-плана (api_keys, issue/revoke, X-API-Key auth, rate-limit keying) | D | done | backend | 003, 010 | 2026-06-09 |
| [TASK-029](./task-029-frontend-ssr-enablement.md) | Frontend SSR enablement (TanStack hydration, cookie-forward) + manualChunks | D | done | frontend | 013, 014 | 2026-06-09 |
| [TASK-030](./task-030-api-hardening-errors-versioning.md) | API hardening — единый error-envelope + machine-readable коды + /api/v1 версионирование | D | done | backend | 019 | 2026-06-09 |
| [TASK-031](./task-031-twitter-source.md) | Twitter/X source readiness (collector/twitter по ADR-001 + per-source лимиты) | D | planned | backend | 005 | 2026-06-09 |
| [TASK-032](./task-032-security-hardening.md) | Security hardening — per-route rate-limit + CSRF в nginx + at-rest шифрование (app-level, опц.) | D | planned | infra | 011, 012 | 2026-06-09 |
| [TASK-033](./task-033-gdpr-data-export.md) | GDPR data-export (GET /account/export, Art.20 portability) | D | planned | backend | 011 | 2026-06-09 |
| [TASK-034](./task-034-pg-backup-restore-check.md) | Postgres backups — ежедневный дамп в Hetzner Object Storage + restore-check | E0 | done | infra | 056 | 2026-06-10 |
| [TASK-035](./task-035-tg-pool-health.md) | TG-пул: целевой размер ≥3, health-метрика, self-alert опсам | E0 | done | backend | 005, 024 | 2026-06-10 |
| [TASK-036](./task-036-signal-latency-metric.md) | Метрика задержки сигнала p50/p95 «пост→алерт» + Redis memory watch | E0 | done | backend | 008, 009, 022 | 2026-06-10 |
| [TASK-037](./task-037-embedding-cache.md) | Кэш эмбеддингов по SHA-256 хэшу текста (Redis, TTL 48h) | E0 | done | backend | 007 | 2026-06-10 |
| [TASK-038](./task-038-curated-channel-packs.md) | Curated channel packs — каталог, GET /packs, подписка в 1 клик вне лимита CHANNELS | E1 | done | backend | 004, 010 | 2026-06-10 |
| [TASK-039](./task-039-onboarding-instant-value.md) | Onboarding instant value — showcase-тенант + GET /trending + экран после регистрации | E1 | done | backend | 038 | 2026-06-10 |
| [TASK-040](./task-040-free-plan-alert-delay.md) | Free-план: задержка алертов 15–30 мин (deliver_after + resweep-уважение) | E1 | done | backend | 008, 010, 023 | 2026-06-10 |
| [TASK-041](./task-041-historical-engagement-baseline.md) | Historical engagement baseline — channel_avg по скользящему 7d-окну канала | E2 | done | backend | 008, 022 | 2026-06-10 |
| [TASK-042](./task-042-alert-feedback-precision.md) | Фидбек 👍/👎 (URL-кнопки в TG-алерте) + alert_feedback + precision per user | E2 | done | backend | 009, 036 | 2026-06-10 |
| [TASK-043](./task-043-adaptive-threshold-anti-fatigue.md) | Адаптивный порог по доле 👎 + анти-fatigue (N алертов/час, группировка) | E2 | done | backend | 042 | 2026-06-10 |
| [TASK-044](./task-044-showcase-autoposting.md) | Showcase авто-постинг — топ-сигналы в публичный TG-канал (delay + CTA + анти-спам) | E3 | done | backend | 035, 039 | 2026-06-10 |
| [TASK-045](./task-045-proof-of-speed-cases.md) | Proof-of-speed — snapshot-кейсы showcase_cases + GET /cases (сырьё лендинга) | E3 | done | backend | 044 | 2026-06-10 |
| [TASK-046](./task-046-referral-program-usdt.md) | Реферальная программа USDT — ref_code + начисление при первой оплате + «Пригласи» | E3 | done | backend | 003, 010 | 2026-06-10 |
| [TASK-049](./task-049-pricing-rework.md) | Pricing rework — Free=воронка (паки+задержка), Pro $29, Trader $99 (API), grandfathering | E5 | done | backend | 010, 038, 040 | 2026-06-11 |
| [TASK-050](./task-050-activation-funnel-metrics.md) | Воронка активации — funnel log_event-события + дневной Beat-агрегат `business_metrics_daily` | E6 | done | backend | 038, 042, 010 | 2026-06-11 |
| [TASK-051](./task-051-money-dashboard.md) | Дашборд «деньги» — GET /ops/business-metrics (superuser): MRR/подписки/чек/воронка/retention | E6 | done | backend | 050, 049 | 2026-06-11 |
| [TASK-056](./task-056-hetzner-object-storage-infra.md) | Hetzner Object Storage infra — terraform-порт с DO (minio-провайдер, бакет, lifecycle) + S3-env в Ansible | E0 | done | infra | 012 | 2026-06-09 |
| [TASK-057](./task-057-prod-launch-vps.md) | Прод-запуск на VPS — make deploy (provision→TLS→stack→showcase-init→smoke) одной командой | — | planned | infra | 012, 034, 039 | 2026-06-10 |
| [TASK-058](./task-058-billing-live-verification.md) | Боевая проверка платёжного пути — NOWPayments live IPN, raw-HMAC fallback, тестовый платёж | — | in-progress (код merged, live blocked) | backend | 010, 057, 049 | 2026-06-11 |
| [TASK-059](./task-059-tg-pool-scaleout.md) | TG-пул до ≥3 аккаунтов — сессии в vault, prod pool_min_healthy=3, операторский runbook (P1) | — | planned | infra | 035, 012 | 2026-06-11 |
| [TASK-060](./task-060-uptime-monitoring-support.md) | Внешний uptime-мониторинг /api/ready + support@foresignal.biz (email-routing IaC, витрины) | — | planned | infra | 057 | 2026-06-11 |
