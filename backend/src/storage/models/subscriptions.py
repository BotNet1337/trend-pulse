"""Billing tables (task-010): `subscriptions` + `billing_payments`.

- `subscriptions` — one row per user (unique `user_id`) holding the paid plan and
  its `expires_at`. The IPN handler (verified HMAC) is the ONLY writer of
  `plan`/`expires_at`; the client never sets a plan (ADR-004, no client-trust).
- `billing_payments` — the idempotency + invoice store. An invoice row is created
  pending at `POST /billing/invoice`; the IPN handler keys idempotency on the
  UNIQUE NOWPayments `payment_id`, so a replayed IPN with the same id is a no-op
  (AC5). `order_id`/`amount`/`currency` let the webhook cross-check the IPN
  against the created invoice before activating (ADR-004 §Security).

`user_id` FKs `users.id ON DELETE CASCADE` (tenant root, task-002). All timestamps
are timezone-aware (never naive).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow

# Column widths — named constants, not magic literals (CONVENTIONS).
_PLAN_MAX = 16
_ORDER_ID_MAX = 128
_PAYMENT_ID_MAX = 128
_STATUS_MAX = 32
_CURRENCY_MAX = 32
# Hosted payment-page URL (TASK-048). 2048 covers any practical URL length.
_PAYMENT_URL_MAX = 2048
# Monetary precision for the invoice amount (NOWPayments price_amount). Crypto
# amounts can carry many decimals; store as exact Numeric, never float.
_AMOUNT_PRECISION = 38
_AMOUNT_SCALE = 18


class Subscription(Base):
    """A user's current paid plan + expiry. One row per user (unique `user_id`)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
        # Partial index for the renewal sweep (task-027): expires_at within window.
        Index(
            "ix_subscriptions_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[str] = mapped_column(String(_PLAN_MAX), nullable=False)
    # NULL = no active paid period (the effective plan falls back to Free).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Renewal-reminder idempotency (task-027): NULL initially; set to the current
    # window (days) after a successful reminder send. The beat task skips only when
    # this EQUALS the current window, so a renewed period (window widens past the
    # last sent, e.g. 7 vs 1) re-triggers reminders without needing an explicit reset.
    last_reminder_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class BillingPayment(Base):
    """Invoice + processed-IPN idempotency store (keyed on NOWPayments `payment_id`)."""

    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_billing_payments_order_id"),
        UniqueConstraint("payment_id", name="uq_billing_payments_payment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Our generated invoice id, echoed back by NOWPayments as `order_id` in the IPN.
    order_id: Mapped[str] = mapped_column(String(_ORDER_ID_MAX), nullable=False)
    # NOWPayments payment id — NULL until the first IPN; UNIQUE so a replayed IPN
    # with the same id can't be processed twice (AC5).
    payment_id: Mapped[str | None] = mapped_column(String(_PAYMENT_ID_MAX), nullable=True)
    plan: Mapped[str] = mapped_column(String(_PLAN_MAX), nullable=False)
    period: Mapped[str] = mapped_column(String(_STATUS_MAX), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=_AMOUNT_PRECISION, scale=_AMOUNT_SCALE), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(_CURRENCY_MAX), nullable=False)
    status: Mapped[str] = mapped_column(String(_STATUS_MAX), nullable=False)
    # Hosted payment-page URL from the gateway response (TASK-048, migration 0021):
    # persisted so a pre-created renewal invoice can be REUSED across the 7/3/1
    # reminder windows and the underpaid notice can link to the same page. The URL
    # comes ONLY from the NOWPayments API response — never from an IPN body.
    # NULL for rows created before 0021 (such rows are never reused).
    payment_url: Mapped[str | None] = mapped_column(String(_PAYMENT_URL_MAX), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
