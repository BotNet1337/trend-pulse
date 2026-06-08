"""`alerts` — per-tenant alert records for a cluster crossing its threshold."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow


class Alert(UserOwnedBase):
    __tablename__ = "alerts"
    # An alert is unique per `(user_id, cluster_id)` so a repeated scorer tick (or a
    # race between two ticks) never creates a duplicate — idempotency at the DB
    # level (task-008 AC6; migration 0003).
    __table_args__ = (
        UniqueConstraint("user_id", "cluster_id", name="uq_alerts_user_cluster"),
        Index("ix_alerts_user_id", "user_id"),
    )

    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    channels_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
