"""Lifecycle-email constants (TASK-069) — import-cycle-free leaf module.

This module MUST NOT import `celery_app` or any module that imports it.
`scheduler.py` imports this file; if it imported `celery_app` → cycle
(same class of bug as task-023 / billing.constants).  Only stdlib here.
"""

# Celery task name — used by `scheduler.beat_schedule` WITHOUT importing
# celery_app (the name is just a string; Celery looks it up at runtime).
SEND_LIFECYCLE_EMAILS_TASK: str = "notifications.tasks.send_lifecycle_emails"

# Win-back hard frequency cap (days): even a re-armed inactivity cycle may not
# trigger a second win-back sooner than this. Anti-spam invariant (task doc
# Discussion: «win-back ≤ 1 на цикл неактивности и не чаще 1 раза в 30 дней»).
WINBACK_COOLDOWN_DAYS: int = 30

# JWT audience for unsubscribe tokens — distinct from the fastapi-users auth
# audience so an auth JWT can never unsubscribe anyone (and vice versa).
UNSUBSCRIBE_TOKEN_AUDIENCE: str = "trendpulse:unsubscribe"

# Unsubscribe-token lifetime: lifecycle emails live long in inboxes → 90 days.
UNSUBSCRIBE_TOKEN_LIFETIME_SECONDS: int = 90 * 86_400

# API path of the unsubscribe endpoint as seen by the CLIENT (nginx maps
# /api/v1/... → backend /v1/...). Mirrors the feedback-button URL pattern
# (alerts/backends.py: `{public_base_url}/api/v1/feedback/{token}`).
UNSUBSCRIBE_API_PATH: str = "/api/v1/email/unsubscribe"

# Templates + subjects (registry: templates/templates.json). New lifecycle
# templates are EN-only, «Foresignal» brand (TASK-072); `auth/welcome` is a
# pre-existing TrendPulse-branded template — rebranding it is TASK-072 debt.
_WELCOME_TEMPLATE: str = "auth/welcome"
_WELCOME_SUBJECT: str = "Welcome to TrendPulse!"
_DIGEST_TEMPLATE: str = "lifecycle/weekly-digest"
_DIGEST_SUBJECT: str = "Your weekly Foresignal digest"
_WINBACK_TEMPLATE: str = "lifecycle/win-back"
_WINBACK_SUBJECT: str = "Your Foresignal packs have been quiet"

# Frontend deeplink paths for lifecycle CTAs (must match frontend
# app/router/path.ts). Onboarding hosts the curated-pack attach flow
# (TASK-039) → welcome CTA «подключи пак»; win-back points at watchlists.
_WELCOME_CTA_PATH: str = "/onboarding"
_WINBACK_CTA_PATH: str = "/watchlists"
