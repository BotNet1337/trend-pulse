"""Persist the hosted payment-page URL on billing_payments (TASK-048).

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-11

Additive and backward-compatible (pattern: 0020 scores.channels_count):

- `billing_payments.payment_url` (VARCHAR(2048) NULL) — the NOWPayments hosted
  invoice URL captured from the create-invoice API response. Enables one-click
  renewal emails to reuse a pre-created pending invoice across the 7/3/1
  reminder windows, and the underpaid notice to link to the same payment page.
  No backfill: rows created before this migration stay NULL and are simply
  never reused (a fresh invoice is created instead).

Downgrade drops the column only — no other data is touched.

SQLAlchemy ops only (no f-string SQL — CONVENTIONS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Width mirrors `storage.models.subscriptions._PAYMENT_URL_MAX`.
_PAYMENT_URL_MAX = 2048

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_payments",
        sa.Column("payment_url", sa.String(length=_PAYMENT_URL_MAX), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_payments", "payment_url")
