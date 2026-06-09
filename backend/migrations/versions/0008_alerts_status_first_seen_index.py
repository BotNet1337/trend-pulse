"""alerts — composite index (delivery_status, first_seen) for pending-sweep.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-09

Adds `ix_alerts_status_first_seen(delivery_status, first_seen)` to accelerate
the `resweep_pending_alerts` beat task (task-023):

    SELECT id FROM alerts
    WHERE delivery_status = 'pending'
      AND first_seen < :cutoff
    ORDER BY first_seen
    LIMIT :max_batch

The composite index covers the leading `delivery_status` equality predicate
(status filter) followed by `first_seen` (range scan + sort), making the
system-wide sweep O(log N) rather than a full table scan.

The existing `ix_alerts_user_first_seen(user_id, first_seen)` from migration
0006 and `ix_alerts_user_id(user_id)` are kept — the new index is complementary
(cross-tenant sweep vs per-tenant cursor queries).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_alerts_status_first_seen", "alerts", ["delivery_status", "first_seen"])


def downgrade() -> None:
    op.drop_index("ix_alerts_status_first_seen", table_name="alerts")
