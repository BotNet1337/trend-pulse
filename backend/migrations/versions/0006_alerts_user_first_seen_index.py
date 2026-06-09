"""alerts — add composite index (user_id, first_seen) for cursor keyset.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-09

Adds `ix_alerts_user_first_seen(user_id, first_seen)` to support the keyset
cursor query introduced in TASK-020:

    ORDER BY first_seen DESC, id DESC
    WHERE (first_seen, id) < (:cursor_fs, :cursor_id)

The composite index covers the leading `user_id` equality predicate (tenant-
scope) followed by `first_seen` (range scan), making the keyset query O(log N)
instead of a full tenant-partition scan.

The existing `ix_alerts_user_id` is kept (it is referenced by other queries
and the composite index does not auto-replace it in Postgres).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_alerts_user_first_seen", "alerts", ["user_id", "first_seen"])


def downgrade() -> None:
    op.drop_index("ix_alerts_user_first_seen", table_name="alerts")
