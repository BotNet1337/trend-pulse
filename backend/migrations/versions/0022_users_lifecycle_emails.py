"""Lifecycle-email state on users (TASK-069).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-11

Additive and backward-compatible (pattern: 0004 delivery-config columns):

- `users.lifecycle_emails_opt_out` (BOOLEAN NOT NULL DEFAULT false) — set by
  the unauthenticated GET /email/unsubscribe endpoint (idempotent); blocks
  welcome/digest/win-back lifecycle emails, never transactional ones.
- `users.digest_last_sent_at` (TIMESTAMPTZ NULL) — weekly-digest frequency
  state; written ONLY on successful send (idempotency via state, TASK-027).
- `users.winback_last_sent_at` (TIMESTAMPTZ NULL) — win-back cycle/cooldown
  state; written ONLY on successful send.

server_default keeps existing rows valid; readers that predate this migration
simply ignore the new columns. Downgrade drops the three columns only.

SQLAlchemy ops only (no f-string SQL — CONVENTIONS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "lifecycle_emails_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("digest_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("winback_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "winback_last_sent_at")
    op.drop_column("users", "digest_last_sent_at")
    op.drop_column("users", "lifecycle_emails_opt_out")
