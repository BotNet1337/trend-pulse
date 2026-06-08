"""Billing — subscriptions + billing_payments (task-010).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09

Single head 0001→0002→0003→0004→0005. Creates the two billing tables:

- `subscriptions` — one row per user (unique `user_id`) with `plan` + `expires_at`
  (nullable). The verified IPN handler is the only writer (ADR-004, no client-trust).
- `billing_payments` — invoice + idempotency store; `order_id` and `payment_id`
  are UNIQUE so a replayed IPN with the same NOWPayments `payment_id` is a no-op
  (AC5) and the webhook can cross-check `order_id`/amount/currency vs the invoice.

`users.plan` already exists (migration 0004). SQLAlchemy ops only (no f-string SQL).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column widths — named constants, mirror storage/models/subscriptions.py.
_PLAN_MAX = 16
_ORDER_ID_MAX = 128
_PAYMENT_ID_MAX = 128
_STATUS_MAX = 32
_CURRENCY_MAX = 32
_AMOUNT_PRECISION = 38
_AMOUNT_SCALE = 18


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(length=_PLAN_MAX), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )
    op.create_table(
        "billing_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_id", sa.String(length=_ORDER_ID_MAX), nullable=False),
        sa.Column("payment_id", sa.String(length=_PAYMENT_ID_MAX), nullable=True),
        sa.Column("plan", sa.String(length=_PLAN_MAX), nullable=False),
        sa.Column("period", sa.String(length=_STATUS_MAX), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(precision=_AMOUNT_PRECISION, scale=_AMOUNT_SCALE),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=_CURRENCY_MAX), nullable=False),
        sa.Column("status", sa.String(length=_STATUS_MAX), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_id", name="uq_billing_payments_order_id"),
        sa.UniqueConstraint("payment_id", name="uq_billing_payments_payment_id"),
    )


def downgrade() -> None:
    op.drop_table("billing_payments")
    op.drop_table("subscriptions")
