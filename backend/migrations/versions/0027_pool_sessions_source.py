"""pool_sessions — add `source` provenance column per session (TASK-130).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-20

Schema change (purely additive, backward-compatible):

ADD COLUMN pool_sessions.source VARCHAR(16) NOT NULL DEFAULT 'manual' — the provenance
of this pool account: `manual` (the owner onboarded it via QR) vs `auto` (the
account-factory promoted it, TASK-134). The `server_default='manual'` backfills every
existing row to `manual` (the safe assumption — all current accounts are owner-added),
and a NOT NULL column with a default means no row can be left without a provenance.

Non-secret: `source` is surfaced in the pool-health snapshot + the pool-admin UI badge.

No downgrade data risk: `downgrade()` drops the column cleanly (the provenance is a
derived/observability field, not load-bearing for ingest).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations do not import app constants — mirror 0026's local-constant pattern.
# Column width + the backfill default — keep in sync with collector/constants.py
# (POOL_SOURCE_MAX / POOL_SOURCE_MANUAL) and storage/models/pool_sessions.py.
_SOURCE_MAX = 16
_DEFAULT_SOURCE = "manual"


def upgrade() -> None:
    op.add_column(
        "pool_sessions",
        sa.Column(
            "source",
            sa.String(length=_SOURCE_MAX),
            nullable=False,
            server_default=_DEFAULT_SOURCE,
        ),
    )


def downgrade() -> None:
    op.drop_column("pool_sessions", "source")
