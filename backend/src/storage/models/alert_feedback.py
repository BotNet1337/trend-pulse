"""`alert_feedback` — per-user verdict for a delivered alert (TASK-042).

Stores the 👍/👎 tap from a user's Telegram inline button.  The table is keyed
by (alert_id) with a UNIQUE constraint — one verdict per alert, last tap wins
(UPSERT).  ``user_id`` is denormalised from the alert for efficient per-user
precision queries without an extra JOIN.

Verdict encoding:
  1  = "up"   (👍 — useful signal)
  0  = "down" (👎 — not useful)

Using a smallint (0/1) keeps the column minimal and matches the SQL SUM()
pattern used in the precision query (SUM(verdict) = up_count,
COUNT(*) - SUM(verdict) = down_count).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow

# Verdict integer values — named constants, not magic literals (CONVENTIONS).
VERDICT_UP: int = 1
VERDICT_DOWN: int = 0


class AlertFeedback(UserOwnedBase):
    """One 👍/👎 verdict per alert (UNIQUE alert_id), last-write-wins UPSERT."""

    __tablename__ = "alert_feedback"
    __table_args__ = (
        # Unique per alert — only one verdict per alert (upsert on conflict).
        UniqueConstraint("alert_id", name="uq_alert_feedback_alert_id"),
    )

    # FK → alerts.id with CASCADE so feedback is deleted when the alert is purged
    # by retention (edge case: tap after deletion → 404/410 in the router).
    alert_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # verdict: 1=up, 0=down (smallint — efficient SUM() for precision queries).
    verdict: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
