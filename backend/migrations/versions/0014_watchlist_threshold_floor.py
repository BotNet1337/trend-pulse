"""watchlist_threshold_floor — nullable threshold_floor on watchlists (TASK-043).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-10

Adds ``watchlists.threshold_floor FLOAT NULL`` — the user-intent anchor for the
adaptive threshold.  A NULL value means the floor has not been snapshotted yet
(first adapt tick will snapshot current threshold).  A non-NULL value is the
threshold value the user last set manually; adaptation never goes below it (and
never above floor + threshold_adapt_range).

Design decisions
----------------
- Nullable (not NOT NULL with default): NULL sentinel carries meaningful semantics
  (``resolve_floor`` in adaptation.py distinguishes "never snapshotted" from
  "snapshotted at 0.0").  All existing rows start NULL — behaviour before TASK-043
  was no adaptation; the first tick snapshots the floor.
- Float (same type as ``watchlists.threshold``).
- No index: queried alongside ``threshold`` in per-watchlist loops; table is
  small at MVP scale (pain-point P5 — accepted risk).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "watchlists",
        sa.Column("threshold_floor", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watchlists", "threshold_floor")
