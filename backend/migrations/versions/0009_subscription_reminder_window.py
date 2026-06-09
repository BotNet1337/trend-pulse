"""subscriptions — add last_reminder_window for renewal-notification idempotency.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-09

Adds `subscriptions.last_reminder_window` (nullable Integer, default NULL).

The column tracks the smallest reminder-window (days) for which a renewal
notification was already sent for a given subscription.  The Beat task
`check_expiring_subscriptions` (task-027) reads this before sending and sets
it after a successful send, guaranteeing exactly-once delivery per window.

NULL = no reminder sent yet (or subscription was renewed, resetting tracking).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("last_reminder_window", sa.Integer(), nullable=True),
    )
    # Partial index for the renewal sweep query (expires_at within the window,
    # non-NULL) so it never seq-scans the whole table as subscriptions grow.
    op.create_index(
        "ix_subscriptions_expires_at",
        "subscriptions",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_expires_at", table_name="subscriptions")
    op.drop_column("subscriptions", "last_reminder_window")
