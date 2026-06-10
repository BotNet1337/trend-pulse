"""alert_feedback — 👍/👎 verdict table (TASK-042).

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-10

Creates ``alert_feedback`` — one verdict row per alert (UNIQUE alert_id),
last-write-wins UPSERT.  Stores the user's 👍/👎 tap from the Telegram
inline button.

Schema decisions
----------------
- ``alert_id`` FK → alerts.id ON DELETE CASCADE: feedback disappears with
  the alert when retention purges it.  A tap after deletion → 404/410 in the
  router (the FK row is gone; the token still verifies but the lookup fails).
- ``user_id`` FK → users.id ON DELETE CASCADE: GDPR-safe — account deletion
  removes all feedback.  Denormalized from the alert for efficient per-user
  precision queries (avoid JOIN on every precision tick).
- ``verdict`` SMALLINT NOT NULL: 1=up, 0=down.  Enables SUM(verdict) for
  up_count without a WHERE clause (micro-optimization for the metric query).
- ``uq_alert_feedback_alert_id`` UNIQUE(alert_id): enforces one-per-alert at
  the DB level; the UPSERT in the router uses this constraint name.
- No index on ``user_id`` beyond the FK: the precision query aggregates over a
  7d window and the table will be small at MVP scale.  Add if EXPLAIN shows a
  problem (accepted risk per pain-point P5).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", name="uq_alert_feedback_alert_id"),
    )


def downgrade() -> None:
    op.drop_table("alert_feedback")
