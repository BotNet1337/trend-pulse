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

from billing.constants import _RENEWAL_INVOICE_MAX_AGE_DAYS
from billing.gateway.base import Invoice, PaymentGateway
from billing.plans import (
    PERIOD_DAYS,
    PLAN_PERIOD_PRICES_USD,
    PRICE_CURRENCY,
    BillingPeriod,
    Plan,
    price_for,
)
from storage.models.base import utcnow
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import User

_STATUS_PENDING = "pending"
_STATUS_PROCESSED = "processed"


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
    """Persist a pending payment + create the gateway invoice for `plan`/`period`.

    The gateway's hosted payment-page URL is persisted on the row (TASK-048) so
    renewal emails can reuse the invoice and the underpaid notice can link to it.
    """
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
    invoice = gateway.create_invoice(plan=plan, period=period, user=user, order_id=order_id)
    payment.payment_url = invoice.payment_url
    session.flush()
    return invoice


def _last_paid_period(session: Session, *, user_id: int) -> BillingPeriod:
    """Period of the user's LAST processed payment — «extend as they paid».

    Fallback `MONTH` when there are no processed payments (manually granted
    subscription) or the stored period no longer parses (TASK-048 Decision).
    """
    last = session.scalars(
        select(BillingPayment)
        .where(BillingPayment.user_id == user_id)
        .where(BillingPayment.status == _STATUS_PROCESSED)
        .order_by(BillingPayment.processed_at.desc())
        .limit(1)
    ).first()
    if last is None:
        return BillingPeriod.MONTH
    try:
        return BillingPeriod(last.period)
    except ValueError:
        return BillingPeriod.MONTH


def find_or_create_renewal_invoice(
    session: Session, *, user: User, sub: Subscription, gateway: PaymentGateway
) -> str | None:
    """Return the payment URL of a (possibly pre-existing) renewal invoice.

    Find-or-create for the one-click renewal email (TASK-048): look up a fresh
    pending invoice for (user, plan, period) that already carries a persisted
    `payment_url`; otherwise create one via the gateway. Reuse across the 7/3/1
    reminder windows avoids one invoice per window. Returns None for a
    non-priceable plan (free / unknown) — the caller falls back to `/billing`.

    Reuse rules (Edge cases, task doc):
    - rows with `payment_url IS NULL` (pre-0021) are never reused;
    - rows older than `_RENEWAL_INVOICE_MAX_AGE_DAYS` may have expired on the
      NOWPayments side — a fresh invoice is created instead.
    """
    try:
        plan = Plan(sub.plan)
    except ValueError:
        return None
    if plan not in PLAN_PERIOD_PRICES_USD:
        return None

    period = _last_paid_period(session, user_id=user.id)
    freshness_cutoff = utcnow() - timedelta(days=_RENEWAL_INVOICE_MAX_AGE_DAYS)
    pending = session.scalars(
        select(BillingPayment)
        .where(BillingPayment.user_id == user.id)
        .where(BillingPayment.status == _STATUS_PENDING)
        .where(BillingPayment.plan == plan.value)
        .where(BillingPayment.period == period.value)
        .where(BillingPayment.payment_url.is_not(None))
        .where(BillingPayment.created_at >= freshness_cutoff)
        .order_by(BillingPayment.created_at.desc())
        .limit(1)
    ).first()
    if pending is not None and pending.payment_url:
        return pending.payment_url

    invoice = create_invoice(session, user=user, plan=plan, period=period, gateway=gateway)
    return invoice.payment_url


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
