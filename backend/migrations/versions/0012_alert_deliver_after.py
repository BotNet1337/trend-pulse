"""alert_deliver_after — nullable deliver_after column on alerts (TASK-040).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-10

Adds ``alerts.deliver_after TIMESTAMPTZ NULL`` — the source-of-truth field for
the Free-plan delivery delay.  A NULL value means "deliver immediately" (all
pre-migration rows and Pro/Team rows), a non-NULL value means "do not deliver
before this UTC instant".

Index decision
--------------
The existing ``ix_alerts_status_first_seen (delivery_status, first_seen)``
already serves the resweep query
``WHERE delivery_status='pending' AND first_seen < :cutoff``.
After TASK-040 the resweep adds a third predicate:
``AND (deliver_after IS NULL OR deliver_after <= now())``.

Table size: the alerts table is small (Free retention is short; low cardinality
on delivery_status='pending').  A partial index on
``deliver_after WHERE delivery_status='pending'`` would be negligible in
practice.  EXPLAIN on dev DB with ~1 k rows confirms the planner uses the
existing ``ix_alerts_status_first_seen`` index and filters deliver_after inline
— a new partial index would not change the plan for this retention size.
Decision: no additional index added now; add one if EXPLAIN shows a problem at
scale (pain-point P5 — accepted risk for this epoch).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "deliver_after")
