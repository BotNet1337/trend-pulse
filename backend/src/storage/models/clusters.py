"""`clusters` — per-tenant topic clusters + centroid embedding (overview §4).

`EMBEDDING_DIM` is the single source of truth for the pgvector dimension
(all-MiniLM-L6-v2 → 384). The pipeline (task-007) MUST match it (CONVENTIONS,
arch §7 "pgvector dimension drift").
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow

EMBEDDING_DIM = 384

_TOPIC_MAX = 255


class Cluster(UserOwnedBase):
    __tablename__ = "clusters"
    __table_args__ = (
        Index("ix_clusters_user_id", "user_id"),
        Index("ix_clusters_user_updated", "user_id", "updated_at"),
    )

    topic: Mapped[str] = mapped_column(String(_TOPIC_MAX), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
