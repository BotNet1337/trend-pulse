"""Billing orchestration: invoice creation + plan activation/extension.

`create_invoice` prices the plan (plans.py), persists a pending `billing_payments`
row keyed by a generated `order_id`, and asks the gateway to create the hosted
invoice. `activate_or_extend` sets the user's plan + the subscription `expires_at`,
extending from `max(now, current expiry)` so a renewal never loses the remaining
period (ADR-004 §4). It is idempotent via the `billing_payments` store (the webhook
guards replay before calling it).
"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from billing.gateway.base import Invoice, PaymentGateway
from billing.plans import PERIOD_DAYS, PRICE_CURRENCY, BillingPeriod, Plan, price_for
from storage.models.base import utcnow
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import User

_STATUS_PENDING = "pending"


def _new_order_id() -> str:
    """Generate a unique, opaque order id for an invoice (echoed back in the IPN)."""
    return f"tp-{uuid4().hex}"


def create_invoice(
    session: Session,
    *,
    user: User,
    plan: Plan,
    period: BillingPeriod,
    gateway: PaymentGateway,
) -> Invoice:
    """Persist a pending payment + create the gateway invoice for `plan`/`period`."""
    amount = price_for(plan, period)
    order_id = _new_order_id()
    payment = BillingPayment(
        user_id=user.id,
        order_id=order_id,
        payment_id=None,
        plan=plan.value,
        period=period.value,
        amount=amount,
        currency=PRICE_CURRENCY,
        status=_STATUS_PENDING,
    )
    session.add(payment)
    session.flush()
    return gateway.create_invoice(plan=plan, period=period, user=user, order_id=order_id)


def _period_end(start: datetime, period: BillingPeriod) -> datetime:
    """Compute the new expiry by extending `start` by the period length."""
    return start + timedelta(days=PERIOD_DAYS[period])


def activate_or_extend(
    session: Session, *, user: User, plan: Plan, period: BillingPeriod
) -> Subscription:
    """Set the user's plan + extend the subscription expiry (renewal-safe).

    Extends from `max(now, current expiry)` so paying before the current period
    ends keeps the remaining time (ADR-004 §4). The verified IPN handler is the
    only caller (no client-trust).
    """
    now = utcnow()
    sub = session.scalars(select(Subscription).where(Subscription.user_id == user.id)).one_or_none()

    current_end = now
    if sub is not None and sub.expires_at is not None and sub.expires_at > now:
        current_end = sub.expires_at
    new_expiry = _period_end(current_end, period)

    if sub is None:
        sub = Subscription(user_id=user.id, plan=plan.value, expires_at=new_expiry)
        session.add(sub)
    else:
        sub.plan = plan.value
        sub.expires_at = new_expiry
    user.plan = plan.value
    session.flush()
    return sub
