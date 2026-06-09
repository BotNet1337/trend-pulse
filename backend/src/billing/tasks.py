"""Billing Celery tasks (task-027): subscription renewal notifications.

Beat task `check_expiring_subscriptions` scans subscriptions whose `expires_at`
falls within the reminder windows (7/3/1 days before expiry) and sends exactly
one renewal-reminder email per window per subscription (idempotent via
`Subscription.last_reminder_window`).

Invariants:
- Renewal ≠ viral-alert: does NOT write to the `alerts` table, does NOT go
  through scorer/dispatch_alert.
- Idempotent per (subscription, window): the flag is set only on successful
  send; a transient failure means the next tick retries.
- Tenant-scoped: the query joins Subscription → User; each email goes strictly
  to the owning user's address.
- Task args are JSON-serializable (no ORM objects in signatures — CONVENTIONS).
- PII is never logged (only subscription_id/user_id).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from billing.constants import (
    _SECONDS_PER_DAY,
    CHECK_EXPIRING_SUBSCRIPTIONS_TASK,
    RENEWAL_REMINDER_DAYS,
)
from billing.notifications import send_renewal_reminder
from celery_app import celery_app
from storage.database import get_session
from storage.models.subscriptions import Subscription
from storage.models.users import PLAN_FREE, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _current_window(days_left: float) -> int | None:
    """Return the tightest applicable reminder window, or None if outside all.

    The tightest (smallest) window that satisfies ``days_left <= window`` is
    chosen so that as time passes and the subscription gets closer to expiry,
    we naturally progress through 7 → 3 → 1 with a strictly decreasing
    `last_reminder_window`.

    Args:
        days_left: Fractional days until expiry (may be negative if expired,
                   though the query filters those out).

    Returns:
        The smallest ``w`` from ``RENEWAL_REMINDER_DAYS`` for which
        ``days_left <= w``, or ``None`` when ``days_left > max(windows)``
        (subscription renewed / too far away).
    """
    return min(
        (w for w in RENEWAL_REMINDER_DAYS if days_left <= w),
        default=None,
    )


# ---------------------------------------------------------------------------
# Core business logic (testable without Celery)
# ---------------------------------------------------------------------------


def _check_expiring_subscriptions() -> int:
    """Scan expiring subscriptions and send idempotent renewal reminders.

    Opens its own DB session (process-level; safe to call from the Celery
    worker or directly from tests after DB schema is created).

    Returns:
        Number of reminders successfully sent in this run.
    """
    now: datetime = datetime.now(UTC)
    cutoff: datetime = now + timedelta(days=max(RENEWAL_REMINDER_DAYS))

    sent: int = 0

    with get_session() as session:
        rows = (
            session.execute(
                select(Subscription, User)
                .join(User, Subscription.user_id == User.id)
                .where(Subscription.expires_at.is_not(None))
                .where(Subscription.expires_at > now)
                .where(Subscription.expires_at <= cutoff)
                .where(Subscription.plan != PLAN_FREE)
            )
            .unique()
            .all()
        )

        for subscription, user in rows:
            delta = subscription.expires_at - now
            days_left: float = delta.total_seconds() / _SECONDS_PER_DAY

            current_window = _current_window(days_left)
            if current_window is None:
                continue

            # Idempotency: each reminder window fires exactly once. Within a single
            # paid period the window only NARROWS (7→3→1), so a `current_window`
            # different from the last-sent one is a not-yet-reminded window. After a
            # renewal the window WIDENS past the last sent (e.g. current 7 vs last 1),
            # which is also `!=` → a fresh reminder fires for the new period. We skip
            # ONLY the exact window already sent (no bare `>=`, which would wrongly
            # suppress the renewed period — the reset-branch was unreachable since the
            # query only returns rows with `expires_at <= now + max(window)`).
            if subscription.last_reminder_window == current_window:
                logger.debug(
                    "skipping renewal reminder (already sent) subscription_id=%s window=%s",
                    subscription.id,
                    current_window,
                )
                continue

            try:
                send_renewal_reminder(
                    subscription=subscription,
                    user=user,
                    window_days=current_window,
                )
                # Mark sent + persist per-subscription so a later failure in the
                # sweep cannot roll back an already-delivered reminder (exactly-once).
                subscription.last_reminder_window = current_window
                session.commit()
                sent += 1
            except Exception as exc:  # broad catch: best-effort, retry on next tick
                # PII-safe: log the exception TYPE + ids only (no exc_info — the
                # underlying EmailSendError text carries the recipient address).
                session.rollback()
                logger.warning(
                    "renewal reminder failed subscription_id=%s user_id=%s window=%s error=%s",
                    subscription.id,
                    user.id,
                    current_window,
                    type(exc).__name__,
                )
                # Do NOT set last_reminder_window — allow retry on the next tick.

    return sent


# ---------------------------------------------------------------------------
# Celery task wrapper
# ---------------------------------------------------------------------------


@celery_app.task(name=CHECK_EXPIRING_SUBSCRIPTIONS_TASK)
def check_expiring_subscriptions() -> int:
    """Beat task: scan expiring subscriptions and send renewal reminders.

    Unrouted → lands on the default ``celery`` queue the worker already
    consumes (no compose change required).  Scheduled via
    ``scheduler.beat_schedule`` with interval from
    ``settings.renewal_check_interval_seconds``.

    Returns:
        Number of reminders sent.
    """
    return _check_expiring_subscriptions()
