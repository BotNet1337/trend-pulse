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
from sqlalchemy.orm import Session

from billing.constants import (
    _SECONDS_PER_DAY,
    CHECK_EXPIRING_SUBSCRIPTIONS_TASK,
    RENEWAL_REMINDER_DAYS,
)
from billing.deps import BillingNotConfiguredError, get_gateway
from billing.gateway.base import PaymentGateway
from billing.notifications import send_renewal_reminder
from billing.service import find_or_create_renewal_invoice
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


def _renewal_gateway() -> PaymentGateway | None:
    """The configured billing gateway, or None when billing is not set up.

    Best-effort (TASK-048): an unconfigured gateway must never break the sweep —
    reminders then fall back to the frontend `/billing` URL (AC3).
    """
    try:
        return get_gateway()
    except BillingNotConfiguredError:
        logger.info("renewal sweep: billing gateway not configured — using /billing fallback")
        return None


def _precreate_renewal_invoice(
    session: Session,
    *,
    subscription: Subscription,
    user: User,
    gateway: PaymentGateway | None,
) -> str | None:
    """Best-effort one-click invoice pre-creation for one subscription (TASK-048).

    Returns the hosted payment-page URL, or None on any failure — the reminder
    is more important than one-click, so errors degrade to the `/billing`
    fallback and the sweep continues (AC3). The invoice row is committed
    immediately so a later email failure cannot roll it back.

    PII-safe: logs ids + exception TYPE only (no URLs, no addresses).
    """
    if gateway is None:
        return None
    try:
        renew_url = find_or_create_renewal_invoice(
            session, user=user, sub=subscription, gateway=gateway
        )
        # Persist the pre-created invoice row independently of the email outcome.
        session.commit()
        return renew_url
    except Exception as exc:  # broad catch: best-effort, never abort the sweep
        session.rollback()
        logger.warning(
            "renewal invoice pre-create failed subscription_id=%s user_id=%s error=%s",
            subscription.id,
            user.id,
            type(exc).__name__,
        )
        return None


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
    gateway = _renewal_gateway()

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

            # One-click renewal (TASK-048): pre-create (or reuse) a pending
            # NOWPayments invoice and link straight to its payment page.
            # Best-effort — None falls back to frontend `/billing` (AC3).
            renew_url = _precreate_renewal_invoice(
                session, subscription=subscription, user=user, gateway=gateway
            )

            try:
                send_renewal_reminder(
                    subscription=subscription,
                    user=user,
                    window_days=current_window,
                    renew_url=renew_url,
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
