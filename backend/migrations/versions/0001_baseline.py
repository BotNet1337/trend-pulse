"""Baseline schema — all seven domain tables + pgvector columns.

Revision ID: 0001
Revises:
Create Date: 2026-06-08

Vector columns are declared explicitly via `pgvector.sqlalchemy.Vector`
(autogenerate does not handle them). The `vector` extension is normally
installed by `pg_vector_provisioner` (ADR-005); the leading defensive
`CREATE EXTENSION IF NOT EXISTS vector` is a no-op-safe safety net (also lets
test fixtures bootstrap a DB without the provisioner).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384
_EMAIL_MAX = 320
_HANDLE_MAX = 255
_TOPIC_MAX = 255
_LANG_MAX = 16
_EXTERNAL_ID_MAX = 128


def upgrade() -> None:
    # Defensive: provisioner normally creates this first; no-op when present.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=_EMAIL_MAX), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_kind",
            sa.Enum("TELEGRAM", name="source_kind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("handle", sa.String(length=_HANDLE_MAX), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_kind", "handle", name="uq_channels_source_kind_handle"),
    )

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=_TOPIC_MAX), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("min_channels", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(length=_LANG_MAX), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.UniqueConstraint(
            "user_id", "channel_id", "topic", name="uq_watchlists_user_channel_topic"
        ),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=_EXTERNAL_ID_MAX), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("forwards", sa.Integer(), nullable=False),
        sa.Column("reactions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
    )
    op.create_index("ix_posts_user_id", "posts", ["user_id"])

    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=_TOPIC_MAX), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_clusters_user_id", "clusters", ["user_id"])

    op.create_table(
        "scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("velocity", sa.Float(), nullable=False),
        sa.Column("engagement", sa.Float(), nullable=False),
        sa.Column("cross_channel", sa.Float(), nullable=False),
        sa.Column("viral_score", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"]),
    )
    op.create_index("ix_scores_user_id", "scores", ["user_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("channels_count", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"]),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])


def downgrade() -> None:
    # Drop in reverse FK dependency order. Leave the `vector` extension —
    # it is provisioner-owned (ADR-005), not this migration's to remove.
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_scores_user_id", table_name="scores")
    op.drop_table("scores")
    op.drop_index("ix_clusters_user_id", table_name="clusters")
    op.drop_table("clusters")
    op.drop_index("ix_posts_user_id", table_name="posts")
    op.drop_table("posts")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")
    op.drop_table("channels")
    op.drop_table("users")
