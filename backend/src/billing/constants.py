"""Billing notification constants (task-027) — import-cycle-free leaf module.

This module MUST NOT import `celery_app` or any module that imports it.
`scheduler.py` imports this file; if it imported `celery_app` → cycle
(same class of bug as task-023).  Only stdlib / constants here.
"""

# Renewal reminder windows: send a reminder when days_left <= each of these
# values (in descending order so we can find the tightest applicable window).
RENEWAL_REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)

# Celery task name — used by `scheduler.beat_schedule` WITHOUT importing
# celery_app (the name is just a string; Celery looks it up at runtime).
CHECK_EXPIRING_SUBSCRIPTIONS_TASK: str = "billing.tasks.check_expiring_subscriptions"

# Internal helpers — not exported; callers import from this module directly.
_SECONDS_PER_DAY: int = 86_400

_RENEWAL_SUBJECT: str = "Your TrendPulse subscription is expiring soon"
_RENEWAL_TEMPLATE: str = "billing/renewal"

# Path on the frontend for the CTA button in the renewal email.
_BILLING_PATH: str = "/billing"
