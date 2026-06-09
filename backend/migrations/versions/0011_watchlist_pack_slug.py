"""watchlist_pack_slug — nullable pack_slug column + composite index (TASK-038).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-10

Adds `watchlists.pack_slug VARCHAR(64) NULL` to mark rows that belong to a
curated channel pack (vs. manually created watchlists whose pack_slug IS NULL).

Indexes:
  - ix_watchlists_user_pack  — composite (user_id, pack_slug), enables efficient
    "all packs for a user" queries (GET /packs subscriptions, DELETE unsubscribe).

Migration is additive-only (NULL default) — all existing rows stay valid with
pack_slug=NULL (no back-fill needed). The _channel_usage counter in billing/limits.py
filters `pack_slug IS NULL` so existing per-user channel counts are unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column width — mirrors storage/models/watchlists.py `_PACK_SLUG_MAX` (named, not magic).
_PACK_SLUG_MAX: int = 64


def upgrade() -> None:
    op.add_column(
        "watchlists",
        sa.Column("pack_slug", sa.String(_PACK_SLUG_MAX), nullable=True),
    )
    op.create_index(
        "ix_watchlists_user_pack",
        "watchlists",
        ["user_id", "pack_slug"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlists_user_pack", table_name="watchlists")
    op.drop_column("watchlists", "pack_slug")
