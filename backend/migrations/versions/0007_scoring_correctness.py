"""Scoring correctness — posts↔cluster FK + per-cluster indices + scores upsert.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-09

Adds the infrastructure required for per-cluster scoring (TASK-022):

1. `posts.cluster_id` — nullable FK → `clusters.id` (ON DELETE SET NULL).
   Historical posts keep `NULL`; the batch processor sets `cluster_id` on
   new posts. Deletion of a cluster leaves posts intact with `cluster_id=NULL`.

2. Composite indices on hot query paths:
   - `ix_posts_cluster(cluster_id)` — scorer per-cluster post lookup.
   - `ix_posts_user_channel_posted(user_id, channel_id, posted_at)` — engagement
     aggregation covering tenant + channel + time filters.
   - `ix_clusters_user_updated(user_id, updated_at)` — `_recent_clusters` freshness
     window query.

3. `scores` dedup + unique constraint:
   - Purge duplicate `(user_id, cluster_id)` rows (safety before adding unique).
   - `uq_scores_user_cluster` — enforces upsert idempotency (one score per pair).
   - `ix_scores_cluster(cluster_id)` — supports retention sweep and FK lookups.

`ix_alerts_user_first_seen` was created in migration 0006 (TASK-020) — not
duplicated here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add posts.cluster_id FK (nullable, ON DELETE SET NULL).
    op.add_column("posts", sa.Column("cluster_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_posts_cluster_id",
        "posts",
        "clusters",
        ["cluster_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Composite indices on hot paths.
    op.create_index("ix_posts_cluster", "posts", ["cluster_id"])
    op.create_index("ix_posts_user_channel_posted", "posts", ["user_id", "channel_id", "posted_at"])
    op.create_index("ix_clusters_user_updated", "clusters", ["user_id", "updated_at"])

    # 3. Scores: purge duplicates before adding unique constraint.
    op.execute(
        "DELETE FROM scores a USING scores b "
        "WHERE a.id < b.id AND a.user_id = b.user_id AND a.cluster_id = b.cluster_id"
    )
    op.create_unique_constraint("uq_scores_user_cluster", "scores", ["user_id", "cluster_id"])
    op.create_index("ix_scores_cluster", "scores", ["cluster_id"])


def downgrade() -> None:
    # Reverse in opposite order.
    op.drop_index("ix_scores_cluster", table_name="scores")
    op.drop_constraint("uq_scores_user_cluster", "scores", type_="unique")
    op.drop_index("ix_clusters_user_updated", table_name="clusters")
    op.drop_index("ix_posts_user_channel_posted", table_name="posts")
    op.drop_index("ix_posts_cluster", table_name="posts")
    op.drop_constraint("fk_posts_cluster_id", "posts", type_="foreignkey")
    op.drop_column("posts", "cluster_id")
