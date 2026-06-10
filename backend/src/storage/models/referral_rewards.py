"""`referral_rewards` — reward rows created on a referred user's first payment (TASK-046).

Schema decisions:
- `referred_user_id` UNIQUE: one reward per referred user; this is the structural
  idempotency guard against IPN replay and double-processing.
- `referred_user_id` ON DELETE SET NULL: if the referred user is GDPR-deleted the
  reward is preserved for the referrer (reward already earned), with a NULL FK.
- `referrer_id` ON DELETE CASCADE: if the referrer is deleted, their rewards go too
  (no orphan rows, referrer is the economic actor).
- `payment_id` ON DELETE SET NULL: preserves the reward record even if the billing
  payment row is purged; the integer snapshot is sufficient for audit trails.
- `amount_usdt` as Float (matches BillingPayment.amount approach for USDT amounts);
  the fixed-amount design (not percentage) makes Float precision acceptable for MVP.
- `status` values: 'pending' (default) | 'paid' (operator sets via make referral-paid).
- `paid_at` nullable: NULL until operator marks paid.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow

# Column width for status values.
_STATUS_MAX = 16

# Status constants — named, not magic literals (CONVENTIONS).
REWARD_STATUS_PENDING = "pending"
REWARD_STATUS_PAID = "paid"


class ReferralReward(Base):
    """One reward row per referred user's first activated payment."""

    __tablename__ = "referral_rewards"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_referral_rewards_referred_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Referrer — the user who shared the ref_code and earns the reward.
    # CASCADE: referrer deleted → reward deleted (no orphans).
    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Referred user — UNIQUE (one reward per referred user) + SET NULL on GDPR delete.
    referred_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Billing payment that triggered the reward — SET NULL if payment row is purged.
    payment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("billing_payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Fixed USDT reward amount from settings.referral_reward_usdt.
    amount_usdt: Mapped[float] = mapped_column(Float, nullable=False)
    # Lifecycle status: 'pending' until operator marks paid.
    status: Mapped[str] = mapped_column(
        String(_STATUS_MAX),
        nullable=False,
        default=REWARD_STATUS_PENDING,
        server_default=REWARD_STATUS_PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # NULL until the operator runs `make referral-paid ID=...`.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
