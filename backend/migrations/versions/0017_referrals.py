"""referrals — users.ref_code + users.referred_by + referral_rewards table (TASK-046).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-11

Schema decisions:
- users.ref_code: UNIQUE nullable VARCHAR(32). NULL until first GET /referral/me.
- users.referred_by: nullable FK users.id ON DELETE SET NULL. Set once at
  registration; SET NULL on referrer GDPR delete (award survives, link goes NULL).
- referral_rewards.referred_user_id: UNIQUE, nullable FK users.id ON DELETE SET NULL.
  UNIQUE enforces one reward per referred user; SET NULL on GDPR delete preserves
  the reward row for the referrer.
- referral_rewards.referrer_id: FK users.id ON DELETE CASCADE. Referrer deleted →
  their reward rows are purged (no orphan economic records).
- referral_rewards.payment_id: nullable FK billing_payments.id ON DELETE SET NULL.
  Preserves the reward even if the billing payment row is later purged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER users: add ref_code (UNIQUE nullable) + referred_by (nullable FK).
    op.add_column(
        "users",
        sa.Column("ref_code", sa.String(32), nullable=True),
    )
    op.create_unique_constraint("uq_users_ref_code", "users", ["ref_code"])
    op.add_column(
        "users",
        sa.Column(
            "referred_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # CREATE referral_rewards table.
    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "referrer_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "referred_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("billing_payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_usdt", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name="uq_referral_rewards_referred_user_id"),
    )


def downgrade() -> None:
    op.drop_table("referral_rewards")
    op.drop_constraint("uq_users_ref_code", "users", type_="unique")
    op.drop_column("users", "referred_by")
    op.drop_column("users", "ref_code")
