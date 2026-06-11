"""`business_metrics_daily` — daily business funnel aggregate (TASK-050).

Global aggregate table: NOT UserOwnedBase (no per-user scope; one row per UTC day).
Each row is a snapshot of the day's funnel counters, computed by
`analytics.tasks.aggregate_business_metrics` and idempotently upserted on conflict
(ON CONFLICT (day) DO UPDATE) so repeated task runs are safe.

Schema decisions:
- `day` DATE UNIQUE: one row per UTC calendar day; the uniqueness constraint is
  the idempotency anchor for ON CONFLICT upserts.
- All counters INTEGER NOT NULL: zero rows (empty day) are always written, so
  TASK-051 does not need to interpolate missing days on the dashboard.
- `computed_at`: timestamp of the last aggregate run for this row (audit trail).
- No user_id FK: this is a global aggregate (not per-user); GDPR deletes do NOT
  retroactively alter historical snapshots (snapshot = fact of the day).
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow


class BusinessMetricsDaily(Base):
    """One row per UTC calendar day holding funnel + billing snapshot counters."""

    __tablename__ = "business_metrics_daily"
    __table_args__ = (UniqueConstraint("day", name="uq_business_metrics_daily_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # UTC calendar date — the idempotency / conflict key.
    day: Mapped[date] = mapped_column(Date, nullable=False)

    # Funnel top-of-funnel
    registrations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    packs_attached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # first_alerts_delivered: users whose VERY FIRST delivered alert fell on this day.
    first_alerts_delivered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # first_feedback: users who gave their FIRST 👍/👎 on this day.
    first_feedback: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Billing snapshot
    # new_paid: users whose FIRST processed payment was on this day.
    new_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # churned: subscriptions whose expires_at falls within this day and were NOT
    # renewed by the time of computation (simplification — see task Discussion).
    churned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # active_paid: count of subscriptions with expires_at > end-of-day (snapshot).
    active_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Audit — when this row was last computed.
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
