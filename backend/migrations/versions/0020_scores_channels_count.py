"""Scores carry the real per-cluster channel count (TASK-066).

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-11

Additive and backward-compatible (pattern: 0004 alerts.delivery_status):

- `scores.channels_count` (INTEGER NOT NULL, server_default `1`) — the number of
  unique channels in the cluster at scoring time, persisted by the scorer's
  upsert (`_persist_score`). Existing rows backfill via the server default `1`,
  which equals the value the trending/cases consumers were faking before this
  migration — no regress for old rows (AC4).

Downgrade drops the column only — no other data is touched.

SQLAlchemy ops only (no f-string SQL — CONVENTIONS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column(
            "channels_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("scores", "channels_count")
