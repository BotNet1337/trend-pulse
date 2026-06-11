"""business_metrics_daily + watchlists.created_at (TASK-050).

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-11

Schema changes:
1. CREATE TABLE business_metrics_daily:
   - id: INTEGER PK
   - day: DATE UNIQUE (idempotency anchor for ON CONFLICT upserts)
   - registrations, packs_attached, first_alerts_delivered, first_feedback,
     new_paid, churned, active_paid: INTEGER NOT NULL DEFAULT 0
   - computed_at: TIMESTAMP WITH TIME ZONE NOT NULL
2. ADD COLUMN watchlists.created_at: TIMESTAMP WITH TIME ZONE NOT NULL
   server_default=now() — existing rows get the migration timestamp (acceptable
   for funnel tracking; documented in task Discussion).

No downgrade destructive data risk: both operations are additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add watchlists.created_at (needed for packs_attached aggregate).
    #    server_default=now() so all existing rows get the migration timestamp.
    op.add_column(
        "watchlists",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 2. Create business_metrics_daily — global aggregate (no user FK).
    op.create_table(
        "business_metrics_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("registrations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("packs_attached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_alerts_delivered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_feedback", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_paid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("churned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_paid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", name="uq_business_metrics_daily_day"),
    )


def downgrade() -> None:
    op.drop_table("business_metrics_daily")
    op.drop_column("watchlists", "created_at")
