"""IPN processing: verify → cross-check → idempotent status machine (ADR-004).

`process_ipn` is the only writer of plan/expiry. It:
1. verifies the HMAC signature (gateway) — invalid/missing → raises, the caller
   returns 4xx and the body is NOT applied (AC4, no client-trust);
2. cross-checks `order_id`/amount/currency against the stored invoice (anti-spoof);
3. is idempotent by NOWPayments `payment_id` — a replay is a no-op 200 (AC5);
4. runs the status machine: `finished`/`confirmed` → activate/extend (AC3);
   `partially_paid`/`expired`/intermediate → logged, no activation (AC6).
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from billing.gateway.base import IpnEvent, PaymentGateway
from billing.plans import BillingPeriod, Plan
from billing.service import activate_or_extend
from storage.models.base import utcnow
from storage.models.subscriptions import BillingPayment
from storage.models.users import User

logger = logging.getLogger(__name__)

# Statuses that activate/extend the plan vs. those acknowledged without activation.
_ACTIVATING_STATUSES = frozenset({"finished", "confirmed"})

_STATUS_PROCESSED = "processed"


class IpnRejected(Exception):
    """The IPN verified but failed a business cross-check (order/amount mismatch)."""


@dataclass(frozen=True)
class IpnResult:
    """Outcome of processing one IPN (for the route to ack/log)."""

    payment_id: str
    status: str
    activated: bool
    idempotent_replay: bool


def process_ipn(
    session: Session, *, headers: dict[str, str], raw_body: bytes, gateway: PaymentGateway
) -> IpnResult:
    """Verify + apply an IPN. Raises on invalid signature / cross-check failure."""
    # 1. Verify HMAC — raises IpnVerificationError on invalid/missing signature.
    event = gateway.verify_ipn(headers=headers, raw_body=raw_body)

    # 2. Locate the invoice we created for this order_id.
    payment = session.scalars(
        select(BillingPayment).where(BillingPayment.order_id == event.order_id)
    ).one_or_none()
    if payment is None:
        raise IpnRejected(f"no invoice for order_id {event.order_id!r}")

    # 3. Idempotency: only a payment we ALREADY ACTIVATED is a replay no-op (AC5).
    # NOWPayments sends several IPNs per payment with the SAME payment_id
    # (waiting→confirming→confirmed→finished); a non-activating intermediate IPN
    # must NOT lock out the later activating one — so we key idempotency on the
    # activated/terminal status, not on merely having seen the payment_id.
    if payment.status == _STATUS_PROCESSED:
        return IpnResult(
            payment_id=event.payment_id,
            status=payment.status,
            activated=False,
            idempotent_replay=True,
        )

    # 4. Cross-check amount/currency vs the created invoice (anti-spoof).
    _assert_invoice_matches(payment, event)

    # 5. Status machine.
    activated = False
    payment.payment_id = event.payment_id  # record the gateway payment id
    if event.status in _ACTIVATING_STATUSES:
        user = session.get(User, payment.user_id)
        if user is None:  # pragma: no cover - FK guarantees presence
            raise IpnRejected(f"user {payment.user_id} not found")
        activate_or_extend(
            session, user=user, plan=Plan(payment.plan), period=BillingPeriod(payment.period)
        )
        activated = True
        payment.status = _STATUS_PROCESSED
        # processed_at marks the TERMINAL activation — set only here so a later
        # activating IPN replay is a no-op while intermediate statuses are not.
        payment.processed_at = utcnow()
    else:
        # partially_paid / expired / waiting / confirming → ack, no activation,
        # no processed_at (a subsequent finished IPN must still activate).
        logger.info(
            "billing.ipn non-activating status=%s order_id=%s", event.status, event.order_id
        )
        payment.status = event.status

    session.flush()

    return IpnResult(
        payment_id=event.payment_id,
        status=event.status,
        activated=activated,
        idempotent_replay=False,
    )


def _assert_invoice_matches(payment: BillingPayment, event: IpnEvent) -> None:
    """Reject when the IPN amount/currency does not match the created invoice."""
    if event.amount != payment.amount:
        raise IpnRejected(
            f"amount mismatch for order {event.order_id}: "
            f"invoice={payment.amount} ipn={event.amount}"
        )
    if event.currency.lower() != payment.currency.lower():
        raise IpnRejected(
            f"currency mismatch for order {event.order_id}: "
            f"invoice={payment.currency} ipn={event.currency}"
        )
