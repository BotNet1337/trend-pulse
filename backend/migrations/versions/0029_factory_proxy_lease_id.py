"""factory_accounts.proxy_lease_id — dynamic-proxy lease id column (TASK-140, B-proxy).

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-20

Schema change (purely additive):
ADD COLUMN factory_accounts.proxy_lease_id VARCHAR(128) NULL — the dynamic
ProxyProvider's opaque port id (NON-secret), persisted so a later failure off-ramp can
`release(lease_id)` the leased port after the row was written. It is NOT a secret (unlike
`proxy`, which carries user:pass creds and is an EncryptedString), so this is a PLAIN
VARCHAR — no Fernet TypeDecorator, no per-row crypto in this migration.

NULL for every existing row + every static-pool / no-proxy row (release no-ops on NULL).
Downgrade simply drops the column (no data risk — additive nullable column).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations do not import app constants — mirror 0028's local-constant pattern.
# Keep in sync with factory/constants.py (FACTORY_PROXY_LEASE_ID_MAX) +
# storage/models/factory_accounts.py.
_PROXY_LEASE_ID_MAX = 128


def upgrade() -> None:
    op.add_column(
        "factory_accounts",
        sa.Column("proxy_lease_id", sa.String(length=_PROXY_LEASE_ID_MAX), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("factory_accounts", "proxy_lease_id")
