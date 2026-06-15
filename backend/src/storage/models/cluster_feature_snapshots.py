"""`cluster_feature_snapshots` — forward, metrics-only early-window features (TASK-109, B1).

Per cluster, at fixed early observation windows after first-seen (15m / 30m / 1h), the
scorer logs a snapshot of cumulative-since-birth METRICS (views/forwards/reactions,
post count, distinct channels reached, breadth velocity, age) — never raw text, which
is purged at 48h (ADR-002 §4 retention). This builds TrendPulse's OWN labeled dataset
from the live stream going forward (self-supervised): the future label (eventual
engagement / spread) is computed LATER by joining a snapshot to the cluster's eventual
outcome (B2), so this table is deliberately LEAK-FREE — it stores no outcome/label.

One row per `(user_id, cluster_id, window_label)` (idempotent capture via the unique
constraint + ON CONFLICT DO NOTHING), so re-running a scorer tick never duplicates a
snapshot and a missed earlier tick is backfilled the first time a later tick sees the
window already crossed.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow


class ClusterFeatureSnapshot(UserOwnedBase):
    __tablename__ = "cluster_feature_snapshots"
    __table_args__ = (
        Index("ix_cluster_feature_snapshots_user_id", "user_id"),
        Index("ix_cluster_feature_snapshots_cluster", "cluster_id"),
        # Time-ranged reads (B2/C1 training extracts) and retention pruning filter on
        # captured_at on this ever-growing, insert-only table — index it now (cheap on a
        # small table) so those scans stay index-backed as it grows.
        Index("ix_cluster_feature_snapshots_captured_at", "captured_at"),
        UniqueConstraint(
            "user_id",
            "cluster_id",
            "window_label",
            name="uq_cluster_feature_snapshots_user_cluster_window",
        ),
    )

    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False
    )
    # Observation window label ("15m" / "30m" / "1h") — the early-window tag this
    # snapshot was captured at. Validated against the named windows in scorer.tasks.
    window_label: Mapped[str] = mapped_column(String(16), nullable=False)
    # Age of the cluster (now - first_seen) at capture time, in seconds — the actual
    # observed age, which is >= the window's nominal seconds (captured at the first
    # tick past the window).
    age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cumulative-since-birth metrics (sum over the cluster's posts with
    # posted_at >= first_seen, up to capture time). NOT the score's 24h rolling window.
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forwards: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Distinct channels the story had reached by capture time (cross-channel breadth).
    distinct_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Breadth velocity = distinct_channels / age_hours (clamped denominator), channels/hr.
    breadth_velocity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
