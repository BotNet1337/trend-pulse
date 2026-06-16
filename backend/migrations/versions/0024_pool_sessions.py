"""pool_sessions — dynamic encrypted pool session store + revive (TASK-119).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-16

Schema change (purely additive):
1. CREATE TABLE pool_sessions:
   - id: INTEGER PK
   - tg_user_id: BIGINT NOT NULL UNIQUE (the Telegram account identity; the
     upsert key that distinguishes a REVIVE from an ADD)
   - session_string: VARCHAR(1024) NOT NULL — the Telethon StringSession stored
     ENCRYPTED at rest (ADR-008 Fernet TypeDecorator: the DB column is a VARCHAR
     holding a Fernet token, never the plaintext session). Width is generous for a
     StringSession (~350 chars) + Fernet ciphertext overhead.
   - session_fingerprint: VARCHAR(16) NOT NULL — non-secret sha256[:16] (TASK-102),
     the persistent-quarantine key.
   - display_label: VARCHAR(64) NOT NULL — non-secret masked id / @username for UI.
   - created_at / updated_at: TIMESTAMP WITH TIME ZONE NOT NULL
   - revoked_at: TIMESTAMP WITH TIME ZONE NULL (soft-revoke; NULL = active)
   - UNIQUE(tg_user_id), indexes on tg_user_id and revoked_at.

No downgrade data risk: a brand-new table → downgrade drops it. (The encrypted
column is a plain VARCHAR at the schema level; encryption is the app-layer
TypeDecorator, so no per-row crypto runs in this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column widths — mirror storage/models/pool_sessions.py + collector/constants.py.
_SESSION_STRING_MAX = 1024
_DISPLAY_LABEL_MAX = 64
_FINGERPRINT_LEN = 16


def upgrade() -> None:
    op.create_table(
        "pool_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_string", sa.String(length=_SESSION_STRING_MAX), nullable=False),
        sa.Column("session_fingerprint", sa.String(length=_FINGERPRINT_LEN), nullable=False),
        sa.Column("display_label", sa.String(length=_DISPLAY_LABEL_MAX), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tg_user_id", name="uq_pool_sessions_tg_user_id"),
    )
    op.create_index("ix_pool_sessions_tg_user_id", "pool_sessions", ["tg_user_id"])
    op.create_index("ix_pool_sessions_revoked_at", "pool_sessions", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_pool_sessions_revoked_at", table_name="pool_sessions")
    op.drop_index("ix_pool_sessions_tg_user_id", table_name="pool_sessions")
    op.drop_table("pool_sessions")
