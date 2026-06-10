"""showcase_posts — dedup table for showcase autoposting (TASK-044).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-10

Creates ``showcase_posts`` — one row per cluster; records whether the cluster
has been posted to the public showcase TG channel.

Schema decisions
----------------
- ``cluster_id`` UNIQUE FK → clusters.id ON DELETE CASCADE: ensures one post
  per cluster at the DB level (INSERT-first idempotency — Discussion TASK-044).
  CASCADE deletes the dedup row when the cluster is purged by retention (no
  orphan cleanup needed).
- ``status`` String(16) default 'pending': 'pending' = queued for send,
  'posted' = successfully delivered; pending rows retry on next beat tick.
- ``posted_at`` nullable: NULL until the cluster is delivered; set on success.
- ``created_at``: utcnow() at INSERT — used by the selection filter to scope
  pending rows (age-based retry guard is handled by the selection window, not
  by this table directly).
- ``uq_showcase_posts_cluster_id``: explicit constraint name for
  on_conflict_do_nothing (dialect-safe, matches the INSERT-first pattern of
  _create_alert_idempotent).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "showcase_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", name="uq_showcase_posts_cluster_id"),
    )


def downgrade() -> None:
    op.drop_table("showcase_posts")
