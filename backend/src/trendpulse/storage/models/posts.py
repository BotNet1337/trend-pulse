"""`posts` — per-tenant post metrics + optional cached embedding.

Raw `text` is nullable and TTL'd (≤48h, task-011) — NOT a long-term field
(ADR-002 §4). The persistent value is metrics + optional vector + references.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trendpulse.storage.models.base import UserOwnedBase, utcnow
from trendpulse.storage.models.clusters import EMBEDDING_DIM

_EXTERNAL_ID_MAX = 128


class Post(UserOwnedBase):
    __tablename__ = "posts"
    __table_args__ = (Index("ix_posts_user_id", "user_id"),)

    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(_EXTERNAL_ID_MAX), nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forwards: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Optional per-post vector cache (re-clustering aid); centroid lives on clusters.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # Raw content — nullable, TTL'd by retention; never relied on long-term.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
