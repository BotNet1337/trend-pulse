"""`scores` — per-tenant viral-score components for a cluster (task-008)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow


class Score(UserOwnedBase):
    __tablename__ = "scores"
    __table_args__ = (Index("ix_scores_user_id", "user_id"),)

    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), nullable=False)
    velocity: Mapped[float] = mapped_column(Float, nullable=False)
    engagement: Mapped[float] = mapped_column(Float, nullable=False)
    cross_channel: Mapped[float] = mapped_column(Float, nullable=False)
    viral_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
