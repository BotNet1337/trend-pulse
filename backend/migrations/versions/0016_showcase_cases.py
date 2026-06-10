"""showcase_cases — proof-of-speed marketing case snapshots (TASK-045).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-11

Creates ``showcase_cases`` — self-sufficient snapshot of a showcase-tenant cluster
that crossed the ``showcase_case_min_score`` threshold.

Schema decisions
----------------
- No FK to clusters/posts/scores: snapshot is self-sufficient so cases survive
  the 48h retention purge (AC3, Discussion TASK-045 — snapshot vs FK decision).
- ``title``: sanitized display label (textutils.sanitize_topic_label applied
  BEFORE insert). COMPLIANCE: never raw cluster.topic. Only the sanitized output.
- ``topic vs title``: Cluster has no separate watchlist-style "topic" keyword —
  cluster.topic IS the raw post text. Storing a ``topic`` column alongside
  ``title`` would duplicate the same sanitized value with no added semantics.
  Decision: single ``title`` column for the sanitized label.
- UNIQUE ``(title, first_seen)`` — dedup: same sanitized label first detected at
  the same instant → one row. Two clusters with identical label at different times
  → different cases (intentional).
- ``mainstream_at`` nullable: NULL until operator runs ``make case-mainstream``.
  GET /cases returns only rows where mainstream_at IS NOT NULL.
- ``created_at``: fixation timestamp; NOT the cluster's first_seen.
- ``uq_showcase_cases_title_first_seen``: explicit constraint name for
  on_conflict_do_nothing (idempotent fixation — same cluster next tick → no-op).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "showcase_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        # Sanitized display label — NEVER raw cluster.topic (compliance).
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("viral_score", sa.Float(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        # channels_count: MVP = 1; TODO: persist from scorer when available.
        sa.Column("channels_count", sa.Integer(), nullable=False, server_default="1"),
        # Operator-filled: NULL until make case-mainstream. Hidden from GET /cases.
        sa.Column("mainstream_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title", "first_seen", name="uq_showcase_cases_title_first_seen"),
    )


def downgrade() -> None:
    op.drop_table("showcase_cases")
