"""cluster_feature_snapshots — forward early-window feature capture (TASK-109, B1).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-15

Schema change (purely additive):
1. CREATE TABLE cluster_feature_snapshots:
   - id: INTEGER PK
   - user_id: INTEGER FK users.id ON DELETE CASCADE (tenant isolation)
   - cluster_id: INTEGER FK clusters.id ON DELETE CASCADE
   - window_label: VARCHAR(16) NOT NULL ("15m" / "30m" / "1h")
   - age_seconds: INTEGER NOT NULL (observed cluster age at capture)
   - post_count / views / forwards / reactions / distinct_channels: INTEGER NOT NULL
     DEFAULT 0 (cumulative-since-birth metrics; NO raw text — compliance)
   - breadth_velocity: DOUBLE PRECISION NOT NULL DEFAULT 0 (channels/hr)
   - captured_at: TIMESTAMP WITH TIME ZONE NOT NULL
   - UNIQUE(user_id, cluster_id, window_label) — idempotent capture anchor for the
     ON CONFLICT DO NOTHING write in scorer.tasks._capture_feature_snapshots
   - indexes on user_id and cluster_id

No downgrade data risk: a brand-new table → downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cluster_feature_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("window_label", sa.String(length=16), nullable=False),
        sa.Column("age_seconds", sa.Integer(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forwards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_channels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("breadth_velocity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "cluster_id",
            "window_label",
            name="uq_cluster_feature_snapshots_user_cluster_window",
        ),
    )
    op.create_index(
        "ix_cluster_feature_snapshots_user_id", "cluster_feature_snapshots", ["user_id"]
    )
    op.create_index(
        "ix_cluster_feature_snapshots_cluster", "cluster_feature_snapshots", ["cluster_id"]
    )
    # captured_at index for future time-ranged B2/C1 reads + retention pruning.
    op.create_index(
        "ix_cluster_feature_snapshots_captured_at", "cluster_feature_snapshots", ["captured_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cluster_feature_snapshots_captured_at", table_name="cluster_feature_snapshots"
    )
    op.drop_index("ix_cluster_feature_snapshots_cluster", table_name="cluster_feature_snapshots")
    op.drop_index("ix_cluster_feature_snapshots_user_id", table_name="cluster_feature_snapshots")
    op.drop_table("cluster_feature_snapshots")
