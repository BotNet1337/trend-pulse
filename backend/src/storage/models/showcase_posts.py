"""`showcase_posts` — dedup table for showcase autoposting (TASK-044).

Records whether a showcase-tenant cluster has been posted to the public TG channel.
One row per cluster (UNIQUE cluster_id) — INSERT-first idempotency prevents
double-posting under any race (two beat instances, on_conflict_do_nothing).

This is a SYSTEM-WIDE table (not user-owned): the showcase is a global feed,
not a per-user resource. We base it on `Base` directly (like `Channel`) and use
a direct FK to ``clusters.id`` rather than ``UserOwnedBase``.

Status values (named constants below):
  STATUS_PENDING : row inserted but send not yet confirmed.
  STATUS_POSTED  : cluster delivered to TG channel; not retried.

Lifecycle:
  1. Beat tick INSERTs (cluster_id, status=pending, created_at=now) with
     on_conflict_do_nothing.
  2. If inserted (or row is still pending) → send; on success UPDATE status=posted,
     posted_at=now.
  3. On send failure → leave pending; next tick retries.
  4. Cluster deleted by retention → CASCADE removes this row (no janitor needed).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow

# Status constants — named, not magic literals (CONVENTIONS).
STATUS_PENDING: str = "pending"
STATUS_POSTED: str = "posted"

_STATUS_MAX_LEN: int = 16


class ShowcasePost(Base):
    """One dedup row per cluster for the showcase autopost beat task."""

    __tablename__ = "showcase_posts"
    __table_args__ = (UniqueConstraint("cluster_id", name="uq_showcase_posts_cluster_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # FK → clusters.id: one row per cluster; CASCADE when cluster is purged.
    cluster_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 'pending' | 'posted'  (max 16 chars).
    status: Mapped[str] = mapped_column(
        String(_STATUS_MAX_LEN),
        nullable=False,
        default=STATUS_PENDING,
    )

    # NULL until send succeeds; set to utcnow() on STATUS_POSTED transition.
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Created at INSERT — utcnow() sourced from base helper (CONVENTIONS).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
