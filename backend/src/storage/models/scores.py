"""`scores` — per-tenant viral-score components for a cluster (task-008)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow


class Score(UserOwnedBase):
    __tablename__ = "scores"
    __table_args__ = (
        Index("ix_scores_user_id", "user_id"),
        UniqueConstraint("user_id", "cluster_id", name="uq_scores_user_cluster"),
        Index("ix_scores_cluster", "cluster_id"),
    )

    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), nullable=False)
    velocity: Mapped[float] = mapped_column(Float, nullable=False)
    engagement: Mapped[float] = mapped_column(Float, nullable=False)
    cross_channel: Mapped[float] = mapped_column(Float, nullable=False)
    # Real number of unique channels in the cluster at scoring time (TASK-066).
    # server_default=1 backfills pre-migration rows with the value consumers
    # used to fake — no regress for old data (migration 0020).
    channels_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    viral_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
