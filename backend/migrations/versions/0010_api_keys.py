"""api_keys — table for hashed Team-plan API keys (TASK-028).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-09

Creates `api_keys (id, user_id, key_hash, name, prefix, created_at,
last_used_at, revoked_at)`.  Only the SHA-256 hex digest (`key_hash`) and a
short display prefix (`prefix`) are stored; the plaintext is shown to the user
exactly once on creation and never persisted.

Indexes:
  - ix_api_keys_user_id   — narrow by tenant (user_id)
  - ix_api_keys_prefix    — narrow lookup before constant-time compare
  - uq_api_keys_key_hash  — unique key_hash (one row per distinct key)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column widths — mirrored from storage/models/api_keys.py (named, not magic).
_KEY_HASH_LEN: int = 64
_NAME_MAX: int = 255
_PREFIX_MAX: int = 32


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(_KEY_HASH_LEN), nullable=False),
        sa.Column("name", sa.String(_NAME_MAX), nullable=False),
        sa.Column("prefix", sa.String(_PREFIX_MAX), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
