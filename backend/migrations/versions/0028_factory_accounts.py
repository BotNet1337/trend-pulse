"""factory_accounts — account-factory provisioning lifecycle table (TASK-132, B3).

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-20

Schema change (purely additive):
CREATE TABLE factory_accounts — the factory's OWN source-of-truth for accounts it is
provisioning through a state machine (`purchased → registered → probation → promoted`,
with `failed`/`banned` off-ramps), SEPARATE from `pool_sessions` (promotion COPIES the
session into the pool).
   - id: INTEGER PK
   - phone_masked: VARCHAR(32) NOT NULL — a MASKED phone (e.g. `+79*****1234`); the full
     number is NEVER persisted (compliance + minimise secret surface).
   - provider / provider_order_id: VARCHAR NOT NULL — the upstream SMS provider + its
     order/activation id (non-secret).
   - proxy: VARCHAR(512) NULL — a SOCKS5 URI stored ENCRYPTED at rest (ADR-008 Fernet
     TypeDecorator: the column is a VARCHAR holding a Fernet token, never plaintext).
   - tg_user_id: BIGINT NULL — the Telegram account identity, set after registration.
   - session_string: VARCHAR(1024) NULL — the Telethon StringSession stored ENCRYPTED at
     rest (same Fernet TypeDecorator), set after registration. Width is generous for a
     StringSession (~350 chars) + Fernet ciphertext overhead.
   - state: VARCHAR(16) NOT NULL — the lifecycle state (validated in the app layer).
   - probation_until: TIMESTAMP WITH TIME ZONE NULL — when the warming window ends.
   - cost_usd: NUMERIC(10, 2) NOT NULL — the provisioning cost, summed for budgeting.
   - last_error: VARCHAR(512) NULL — a non-secret diagnostic on a failed/banned move.
   - created_at / updated_at: TIMESTAMP WITH TIME ZONE NOT NULL.
   - indexes on `state` and `probation_until` (the factory loop's hot lookups).

No downgrade data risk: a brand-new table → downgrade drops it. (The encrypted columns
are plain VARCHAR at the schema level; encryption is the app-layer TypeDecorator, so no
per-row crypto runs in this migration.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations do not import app constants — mirror 0024/0027's local-constant pattern.
# Keep in sync with factory/constants.py + storage/models/factory_accounts.py.
_PHONE_MASKED_MAX = 32
_PROVIDER_MAX = 32
_PROVIDER_ORDER_ID_MAX = 128
_PROXY_MAX = 512
_SESSION_STRING_MAX = 1024
_STATE_MAX = 16
_LAST_ERROR_MAX = 512
_COST_PRECISION = 10
_COST_SCALE = 2


def upgrade() -> None:
    op.create_table(
        "factory_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_masked", sa.String(length=_PHONE_MASKED_MAX), nullable=False),
        sa.Column("provider", sa.String(length=_PROVIDER_MAX), nullable=False),
        sa.Column("provider_order_id", sa.String(length=_PROVIDER_ORDER_ID_MAX), nullable=False),
        sa.Column("proxy", sa.String(length=_PROXY_MAX), nullable=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("session_string", sa.String(length=_SESSION_STRING_MAX), nullable=True),
        sa.Column("state", sa.String(length=_STATE_MAX), nullable=False),
        sa.Column("probation_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_usd", sa.Numeric(_COST_PRECISION, _COST_SCALE), nullable=False),
        sa.Column("last_error", sa.String(length=_LAST_ERROR_MAX), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_factory_accounts_state", "factory_accounts", ["state"])
    op.create_index("ix_factory_accounts_probation_until", "factory_accounts", ["probation_until"])


def downgrade() -> None:
    op.drop_index("ix_factory_accounts_probation_until", table_name="factory_accounts")
    op.drop_index("ix_factory_accounts_state", table_name="factory_accounts")
    op.drop_table("factory_accounts")
