"""Lifecycle-email Celery task (TASK-069): daily digest / win-back sweep.

Beat task `send_lifecycle_emails` scans verified, active, non-opted-out users
and sends at most one weekly digest and/or one win-back per user, gated by the
pure due-functions in `notifications.lifecycle` and the persisted
`digest_last_sent_at` / `winback_last_sent_at` state.

Invariants (task doc):
- Lifecycle ≠ transactional: verify/reset/renewal flows are untouched.
- Idempotent per user: `*_last_sent_at` is set ONLY on successful send and
  committed per user, so a failure for one user neither aborts the sweep nor
  rolls back another user's already-delivered email (TASK-027 pattern).
- Empty digest (0 delivered alerts in the window) is NEVER sent (AC2).
- Opt-out is re-read immediately before each send (edge case: user
  unsubscribes between due-selection and send).
- Task args/return are JSON-serializable (CONVENTIONS).
- PII is never logged — only user_id and exception TYPE.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from celery_app import celery_app
from config import get_settings
from notifications.constants import SEND_LIFECYCLE_EMAILS_TASK, WINBACK_COOLDOWN_DAYS
from notifications.lifecycle import (
    collect_digest_items,
    is_digest_due,
    is_winback_due,
    send_weekly_digest,
    send_winback,
)
from storage.database import get_session
from storage.models.alerts import DELIVERY_STATUS_DELIVERED, Alert
from storage.models.users import User
from storage.models.watchlists import Watchlist

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _last_delivered_at(session: Session, user_id: int) -> datetime | None:
    """MAX(alerts.delivered_at) over the user's delivered alerts (or None)."""
    return session.scalar(
        select(func.max(Alert.delivered_at))
        .where(Alert.user_id == user_id)
        .where(Alert.delivery_status == DELIVERY_STATUS_DELIVERED)
    )


def _has_watchlist(session: Session, user_id: int) -> bool:
    """Whether the user has at least one watchlist row (pack or manual)."""
    first_id = session.scalar(select(Watchlist.id).where(Watchlist.user_id == user_id).limit(1))
    return first_id is not None


def _opted_out_now(session: Session, user: User) -> bool:
    """Re-read the opt-out flag right before a send (race with unsubscribe)."""
    session.refresh(user)
    return user.lifecycle_emails_opt_out


def _try_send_digest(session: Session, user: User, now: datetime) -> bool:
    """Send the weekly digest to one user if due and non-empty. True = sent."""
    settings = get_settings()
    if not is_digest_due(
        now=now,
        is_verified=user.is_verified,
        opt_out=user.lifecycle_emails_opt_out,
        digest_last_sent_at=user.digest_last_sent_at,
        period_days=settings.digest_period_days,
    ):
        return False
    items = collect_digest_items(
        session,
        user_id=user.id,
        now=now,
        top_k=settings.digest_top_k,
        period_days=settings.digest_period_days,
    )
    if not items:
        # Empty week → no digest at all (an email without content is spam, AC2).
        # `digest_last_sent_at` stays untouched so the next tick re-evaluates.
        return False
    if _opted_out_now(session, user):
        return False
    send_weekly_digest(user=user, items=items, settings=settings)
    user.digest_last_sent_at = now
    session.commit()
    return True


def _try_send_winback(session: Session, user: User, now: datetime) -> bool:
    """Send the win-back email to one user if due. True = sent."""
    settings = get_settings()
    if not is_winback_due(
        now=now,
        is_verified=user.is_verified,
        opt_out=user.lifecycle_emails_opt_out,
        has_watchlist=_has_watchlist(session, user.id),
        last_delivered_at=_last_delivered_at(session, user.id),
        winback_last_sent_at=user.winback_last_sent_at,
        inactive_days=settings.winback_inactive_days,
        cooldown_days=WINBACK_COOLDOWN_DAYS,
    ):
        return False
    if _opted_out_now(session, user):
        return False
    send_winback(user=user, settings=settings)
    user.winback_last_sent_at = now
    session.commit()
    return True


# ---------------------------------------------------------------------------
# Core business logic (testable without Celery)
# ---------------------------------------------------------------------------


def _send_lifecycle_emails() -> dict[str, int]:
    """Scan eligible users and send due lifecycle emails (digest + win-back).

    Opens its own DB session (process-level; callable from the Celery worker
    or directly from tests once the schema exists).

    Returns:
        JSON-serializable counters: ``{"digests": int, "winbacks": int}``.
    """
    now = datetime.now(UTC)
    digests = 0
    winbacks = 0

    with get_session() as session:
        # Anti-spam gate at the query level: verified, active, not opted out.
        # The pure due-functions re-check verification/opt-out defensively.
        users = (
            session.scalars(
                select(User)
                .where(User.is_verified.is_(True))
                .where(User.is_active.is_(True))
                .where(User.lifecycle_emails_opt_out.is_(False))
            )
            .unique()
            .all()
        )

        for user in users:
            # Best-effort per user: one failure never aborts the sweep, and the
            # untouched `*_last_sent_at` means the next tick retries (e.g. a
            # temporarily down templates service → EmailRenderError → skip).
            try:
                if _try_send_digest(session, user, now):
                    digests += 1
            except Exception as exc:
                # PII-safe: exception TYPE + user_id only (EmailSendError text
                # carries the recipient address — never log it).
                session.rollback()
                logger.warning(
                    "lifecycle digest failed user_id=%s error=%s",
                    user.id,
                    type(exc).__name__,
                )
            try:
                if _try_send_winback(session, user, now):
                    winbacks += 1
            except Exception as exc:
                session.rollback()
                logger.warning(
                    "lifecycle win-back failed user_id=%s error=%s",
                    user.id,
                    type(exc).__name__,
                )

    logger.info("lifecycle tick done digests=%s winbacks=%s", digests, winbacks)
    return {"digests": digests, "winbacks": winbacks}


# ---------------------------------------------------------------------------
# Celery task wrapper
# ---------------------------------------------------------------------------


@celery_app.task(name=SEND_LIFECYCLE_EMAILS_TASK)
def send_lifecycle_emails() -> dict[str, int]:
    """Beat task: send due lifecycle emails (weekly digest + win-back).

    Unrouted → lands on the default ``celery`` queue the worker already
    consumes (no compose change). Scheduled via ``scheduler.beat_schedule``
    with the interval from ``settings.lifecycle_email_interval_seconds``.

    Returns:
        Counters dict (JSON-serializable): digests / winbacks sent.
    """
    return _send_lifecycle_emails()
