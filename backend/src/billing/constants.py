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

# Grace period after subscription expiry (TASK-048, epic E4): the paid plan is
# FULLY retained for 72h past `expires_at` before `effective_plan` falls back to
# Free. Time in seconds as a named constant (CONVENTIONS).
GRACE_PERIOD_SECONDS: int = 259_200  # 72h

# Internal helpers — not exported; callers import from this module directly.
_SECONDS_PER_DAY: int = 86_400

_RENEWAL_SUBJECT: str = "Your TrendPulse subscription is expiring soon"
_RENEWAL_TEMPLATE: str = "billing/renewal"

# Underpaid notice (TASK-048): sent once on the partially_paid IPN transition.
# EN-only copy, Foresignal brand (TASK-072).
_UNDERPAID_SUBJECT: str = "Complete your Foresignal payment"
_UNDERPAID_TEMPLATE: str = "billing/underpaid"

# Path on the frontend for the CTA button in the renewal email.
_BILLING_PATH: str = "/billing"

# Reuse window for a pre-created renewal invoice (TASK-048): a pending invoice
# older than the widest reminder window may have expired on the NOWPayments
# side, so the lookup is bounded by `created_at` and a fresh one is created.
_RENEWAL_INVOICE_MAX_AGE_DAYS: int = max(RENEWAL_REMINDER_DAYS)
