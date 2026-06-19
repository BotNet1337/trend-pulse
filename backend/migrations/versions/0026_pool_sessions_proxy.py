"""pool_sessions — add encrypted proxy column per session (TASK-129).

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-19

Schema change (purely additive, backward-compatible):

ADD COLUMN pool_sessions.proxy VARCHAR(512) NULL — the SOCKS5 proxy URI for this
session slot, stored ENCRYPTED at rest (ADR-008 Fernet TypeDecorator: the DB
column is a VARCHAR holding a Fernet token, never the plaintext URI). Width 512
is generous for a Fernet-encrypted `socks5://user:pass@host:port` URI.

NULL means no proxy configured for this slot (behaviour is byte-identical to
today; fail-open regression-guarded by tests). Non-NULL carries user:pass creds
→ treated as a secret exactly like `session_string`.

No downgrade data risk: the column is nullable with no default and no existing
data — downgrade drops it cleanly. (The encrypted column is a plain VARCHAR at
the schema level; encryption is the app-layer TypeDecorator, so no per-row
crypto runs in this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column width — mirror storage/models/pool_sessions.py + collector/constants.py.
_PROXY_MAX = 512


def upgrade() -> None:
    op.add_column(
        "pool_sessions",
        sa.Column("proxy", sa.String(length=_PROXY_MAX), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pool_sessions", "proxy")
