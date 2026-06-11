"""Business-metrics daily aggregate (TASK-050).

`compute_day(session, day)` runs pure SQL aggregates against source-of-truth tables
and returns a `BusinessMetricsRow` dataclass (not an ORM row — easy to test).
`upsert_row(session, row)` performs an ON CONFLICT (day) DO UPDATE upsert into
`business_metrics_daily` (idempotent by construction).

Design invariants (from task Discussion):
- Aggregates are computed FROM TABLES (not from logs).
- All SQL uses bind params only — no f-string SQL (CONVENTIONS).
- `first_alerts_delivered`: users whose MIN(delivered_at) falls on `day` — meaning
  their very first delivered alert ever was on this day.
- `first_feedback`: users whose MIN(created_at) in alert_feedback falls on `day`.
- `new_paid`: users whose first processed billing_payment was on `day`.
- `churned`: subscriptions with expires_at within [day_start, day_end) and no active
  renewal (expires_at <= day_end at computation time — simplification documented in
  task Discussion; re-activation is handled on read in TASK-051).
- `active_paid`: subscriptions with expires_at > day_end (snapshot at end of day).
- Day boundaries are UTC (CONVENTIONS; all datetimes in the codebase are UTC).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy import bindparam, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from storage.models.alert_feedback import AlertFeedback
from storage.models.alerts import DELIVERY_STATUS_DELIVERED, Alert
from storage.models.base import utcnow
from storage.models.business_metrics import BusinessMetricsDaily
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import PLAN_FREE, User
from storage.models.watchlists import Watchlist


@dataclass
class BusinessMetricsRow:
    """Pure-Python DTO for one day's business metrics.

    Decoupled from ORM to make unit tests simple (no DB required for compute_day
    itself; only upsert_row requires a live session).
    """

    day: datetime.date
    registrations: int = 0
    packs_attached: int = 0
    first_alerts_delivered: int = 0
    first_feedback: int = 0
    new_paid: int = 0
    churned: int = 0
    active_paid: int = 0
    computed_at: datetime.datetime = field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Internal SQL helpers — each returns a single integer count.
# All use bind params only (CONVENTIONS: no f-string SQL).
# ---------------------------------------------------------------------------


def _day_bounds(day: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    """Return [day_start, day_end) as UTC datetimes for the given UTC date."""
    from datetime import UTC

    day_start = datetime.datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC)
    day_end = day_start + datetime.timedelta(days=1)
    return day_start, day_end


def _count_registrations(session: Session, day: datetime.date) -> int:
    """Count users whose created_at is within [day_start, day_end)."""
    day_start, day_end = _day_bounds(day)
    stmt = select(func.count()).where(
        User.created_at >= bindparam("day_start", value=day_start),
        User.created_at < bindparam("day_end", value=day_end),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_packs_attached(session: Session, day: datetime.date) -> int:
    """Count DISTINCT users who got at least one pack-watchlist row on day.

    Uses watchlists.created_at (added in migration 0018). Pack rows are identified
    by pack_slug IS NOT NULL (distinguishes packs from manual watchlists).
    """
    day_start, day_end = _day_bounds(day)
    stmt = select(func.count(func.distinct(Watchlist.user_id))).where(
        Watchlist.pack_slug.is_not(None),
        Watchlist.created_at >= bindparam("day_start", value=day_start),
        Watchlist.created_at < bindparam("day_end", value=day_end),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_first_alerts_delivered(session: Session, day: datetime.date) -> int:
    """Count users whose FIRST delivered alert (MIN delivered_at) was on day.

    Subquery: for each user, find their min(delivered_at). Outer query counts
    those whose minimum falls within [day_start, day_end). This correctly
    excludes users who already had an alert on an earlier day (AC4).
    """
    day_start, day_end = _day_bounds(day)
    # CTE: per-user minimum delivered_at across all delivered alerts ever.
    first_delivered_cte = (
        select(Alert.user_id, func.min(Alert.delivered_at).label("first_dt"))
        .where(Alert.delivery_status == DELIVERY_STATUS_DELIVERED)
        .where(Alert.delivered_at.is_not(None))
        .group_by(Alert.user_id)
        .cte("first_delivered")
    )
    stmt = select(func.count()).where(
        first_delivered_cte.c.first_dt >= bindparam("day_start", value=day_start),
        first_delivered_cte.c.first_dt < bindparam("day_end", value=day_end),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_first_feedback(session: Session, day: datetime.date) -> int:
    """Count users whose FIRST alert_feedback row (MIN created_at) was on day."""
    day_start, day_end = _day_bounds(day)
    first_fb_cte = (
        select(AlertFeedback.user_id, func.min(AlertFeedback.created_at).label("first_dt"))
        .group_by(AlertFeedback.user_id)
        .cte("first_feedback")
    )
    stmt = select(func.count()).where(
        first_fb_cte.c.first_dt >= bindparam("day_start", value=day_start),
        first_fb_cte.c.first_dt < bindparam("day_end", value=day_end),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_new_paid(session: Session, day: datetime.date) -> int:
    """Count users whose FIRST processed billing_payment was on day.

    'new_paid' = user made their first ever successful payment on this day.
    """
    day_start, day_end = _day_bounds(day)
    first_pay_cte = (
        select(BillingPayment.user_id, func.min(BillingPayment.processed_at).label("first_dt"))
        .where(BillingPayment.status == bindparam("pay_status", value="processed"))
        .where(BillingPayment.processed_at.is_not(None))
        .group_by(BillingPayment.user_id)
        .cte("first_payment")
    )
    stmt = select(func.count()).where(
        first_pay_cte.c.first_dt >= bindparam("day_start", value=day_start),
        first_pay_cte.c.first_dt < bindparam("day_end", value=day_end),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_churned(session: Session, day: datetime.date) -> int:
    """Count subscriptions with expires_at within [day_start, day_end).

    Simplification (documented in task Discussion): if a subscription expired on
    day D and was renewed on D+1, it is counted as churned on D. Re-activation
    tracking is left to TASK-051 on read.
    Excludes Free-plan subscriptions (free has no expiry semantics).
    """
    day_start, day_end = _day_bounds(day)
    stmt = select(func.count()).where(
        Subscription.expires_at >= bindparam("day_start", value=day_start),
        Subscription.expires_at < bindparam("day_end", value=day_end),
        Subscription.plan != bindparam("free_plan", value=PLAN_FREE),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


def _count_active_paid(session: Session, day: datetime.date) -> int:
    """Count subscriptions with expires_at > day_end (active at end of day).

    Snapshot of paid subscribers at the close of the UTC day.
    Excludes Free-plan (free has no expiry / paid semantics).
    """
    _day_start, day_end = _day_bounds(day)
    stmt = select(func.count()).where(
        Subscription.expires_at > bindparam("day_end", value=day_end),
        Subscription.plan != bindparam("free_plan", value=PLAN_FREE),
    )
    result: int | None = session.scalar(stmt)
    return result if result is not None else 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_day(session: Session, day: datetime.date) -> BusinessMetricsRow:
    """Compute all business-funnel counters for a single UTC calendar day.

    Pure SQL aggregates from source-of-truth tables. Returns a `BusinessMetricsRow`
    dataclass (not persisted). Callers should pass the result to `upsert_row` to
    persist idempotently.

    No side effects beyond SELECTs — safe to call repeatedly (deterministic).
    """
    return BusinessMetricsRow(
        day=day,
        registrations=_count_registrations(session, day),
        packs_attached=_count_packs_attached(session, day),
        first_alerts_delivered=_count_first_alerts_delivered(session, day),
        first_feedback=_count_first_feedback(session, day),
        new_paid=_count_new_paid(session, day),
        churned=_count_churned(session, day),
        active_paid=_count_active_paid(session, day),
        computed_at=utcnow(),
    )


def upsert_row(session: Session, row: BusinessMetricsRow) -> None:
    """Upsert a BusinessMetricsRow into business_metrics_daily (idempotent).

    ON CONFLICT (day) DO UPDATE: any repeated call for the same day overwrites
    the existing counters. This is the idempotency guarantee for the Beat task
    (AC3): a restarted beat or a double-tick simply re-computes and re-writes
    without errors or duplicates.
    """
    stmt = (
        pg_insert(BusinessMetricsDaily)
        .values(
            day=row.day,
            registrations=row.registrations,
            packs_attached=row.packs_attached,
            first_alerts_delivered=row.first_alerts_delivered,
            first_feedback=row.first_feedback,
            new_paid=row.new_paid,
            churned=row.churned,
            active_paid=row.active_paid,
            computed_at=row.computed_at,
        )
        .on_conflict_do_update(
            constraint="uq_business_metrics_daily_day",
            set_={
                "registrations": row.registrations,
                "packs_attached": row.packs_attached,
                "first_alerts_delivered": row.first_alerts_delivered,
                "first_feedback": row.first_feedback,
                "new_paid": row.new_paid,
                "churned": row.churned,
                "active_paid": row.active_paid,
                "computed_at": row.computed_at,
            },
        )
    )
    session.execute(stmt)
