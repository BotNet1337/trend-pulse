"""Alert idempotency — unique `(user_id, cluster_id)` on `alerts` (task-008 AC6).

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09

Additive and backward-compatible: adds ONLY the unique constraint
`uq_alerts_user_cluster` to `alerts` so the scorer's alert insert is idempotent and
race-safe (a duplicate insert raises `IntegrityError`, which the scorer catches and
skips). No other table is touched. The dev/test table is empty; in a populated DB
any pre-existing duplicate `(user_id, cluster_id)` rows would have to be collapsed
first, but none can exist before the scorer ships.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "uq_alerts_user_cluster"


def upgrade() -> None:
    op.create_unique_constraint(_CONSTRAINT_NAME, "alerts", ["user_id", "cluster_id"])


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "alerts", type_="unique")
