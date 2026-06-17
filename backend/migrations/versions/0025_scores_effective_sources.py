"""Scores carry the source-independence signal (TASK-126).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-17

Additive and backward-compatible (pattern: 0020 scores.channels_count):

- `scores.effective_sources` (FLOAT, NULL) — `exp(source-entropy)` over the
  cluster's in-window per-channel post distribution, the "effective number" of
  independent sources (REUSE `eval.science_features.effective_independent_sources`).
  An organic-spread / independence signal, NOT a coordination detector. It is a
  badge + observed shadow signal and is NOT folded into `viral_score` (D4 deferred).

nullable=True with NO server_default: pre-migration `scores` rows read gracefully as
NULL (the read path / API surface them as `None`/`null`) — no backfill, no regress.

Downgrade drops the column only — no other data is touched.

SQLAlchemy ops only (no f-string SQL — CONVENTIONS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column("effective_sources", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scores", "effective_sources")
