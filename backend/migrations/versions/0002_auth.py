"""Auth — align `users` with fastapi-users + add `oauth_accounts`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08

Additive and backward-compatible (does not touch existing `user_id` FKs):
- adds `hashed_password`, `is_active`, `is_superuser`, `is_verified` to `users`
  (booleans get a server_default so the columns are NOT NULL-safe; `hashed_password`
  is added NULLable-safe via a server_default then tightened to NOT NULL — the dev/test
  table is empty, but this keeps the migration safe against any existing rows);
- creates the `oauth_accounts` table (fastapi-users OAuth identities) with an
  integer PK and `user_id` FK into `users` ON DELETE CASCADE, mirroring the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HASHED_PASSWORD_MAX = 1024
_OAUTH_NAME_MAX = 100
_TOKEN_MAX = 1024
_ACCOUNT_ID_MAX = 320
_ACCOUNT_EMAIL_MAX = 320


def upgrade() -> None:
    # --- Align `users` with SQLAlchemyBaseUserTable. ---
    # hashed_password: add with a transient server_default so existing rows fill in,
    # then drop the default so the application is the source of truth going forward.
    op.add_column(
        "users",
        sa.Column(
            "hashed_password",
            sa.String(length=_HASHED_PASSWORD_MAX),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("users", "hashed_password", server_default=None)

    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The mixin indexes `email`; the baseline only had a unique constraint. Add the
    # matching index (idempotent intent: name mirrors the ORM-generated index).
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- fastapi-users OAuth identities. ---
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("oauth_name", sa.String(length=_OAUTH_NAME_MAX), nullable=False),
        sa.Column("access_token", sa.String(length=_TOKEN_MAX), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("refresh_token", sa.String(length=_TOKEN_MAX), nullable=True),
        sa.Column("account_id", sa.String(length=_ACCOUNT_ID_MAX), nullable=False),
        sa.Column("account_email", sa.String(length=_ACCOUNT_EMAIL_MAX), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_oauth_accounts_oauth_name", "oauth_accounts", ["oauth_name"])
    op.create_index("ix_oauth_accounts_account_id", "oauth_accounts", ["account_id"])
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_accounts_user_id", table_name="oauth_accounts")
    op.drop_index("ix_oauth_accounts_account_id", table_name="oauth_accounts")
    op.drop_index("ix_oauth_accounts_oauth_name", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "is_superuser")
    op.drop_column("users", "is_active")
    op.drop_column("users", "hashed_password")
