"""Billing router: create invoice (auth'd) + receive IPN (raw body, no auth).

- `POST /billing/invoice` — behind `current_user`; body {plan, period} → Invoice.
- `POST /billing/ipn` — NO `current_user`; reads the RAW body bytes for HMAC, so
  an invalid signature is rejected before the body is parsed/trusted. The endpoint
  is reachable only behind nginx (network-design).

Domain errors map to HTTP at this boundary: invalid IPN signature → 401, business
cross-check failure → 400, billing unconfigured → 503.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import current_user
from billing import service
from billing.deps import get_db_session, get_gateway, get_ipn_gateway
from billing.gateway.base import IpnVerificationError
from billing.gateway.nowpayments import NowPaymentsGateway
from billing.plans import BillingPeriod, Plan
from billing.webhook import IpnRejected, process_ipn
from storage.models.users import User

router = APIRouter(prefix="/billing", tags=["billing"])

_SIG_HEADER = "x-nowpayments-sig"
_IPN_ACK = {"status": "ok"}


class InvoiceRequest(BaseModel):
    """Create-invoice request body (validated at the boundary)."""

    plan: Plan
    period: BillingPeriod = BillingPeriod.MONTH


class InvoiceResponse(BaseModel):
    """Invoice response: where to pay + the order id to reconcile the IPN."""

    order_id: str
    payment_url: str
    redirect_url: str | None
    amount: str
    currency: str


class IpnAck(BaseModel):
    """Ack body returned for any handled IPN (200)."""

    status: str


@router.post("/invoice", response_model=InvoiceResponse)
def create_invoice(
    data: InvoiceRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
    gateway: NowPaymentsGateway = Depends(get_gateway),
) -> InvoiceResponse:
    """Create a NOWPayments invoice for the caller's chosen plan/period."""
    if data.plan is Plan.FREE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the free plan has no invoice")
    invoice = service.create_invoice(
        session, user=user, plan=data.plan, period=data.period, gateway=gateway
    )
    return InvoiceResponse(
        order_id=invoice.order_id,
        payment_url=invoice.payment_url,
        redirect_url=invoice.redirect_url,
        amount=str(invoice.amount),
        currency=invoice.currency,
    )


@router.post("/ipn", response_model=IpnAck)
async def receive_ipn(
    request: Request,
    session: Session = Depends(get_db_session),
    gateway: NowPaymentsGateway = Depends(get_ipn_gateway),
) -> IpnAck:
    """Receive a NOWPayments IPN: verify HMAC over the RAW body, then apply."""
    raw_body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    try:
        process_ipn(session, headers=headers, raw_body=raw_body, gateway=gateway)
    except IpnVerificationError as exc:
        # Invalid/missing signature → 401, body NOT applied (AC4, no client-trust).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid IPN signature") from exc
    except IpnRejected as exc:
        # Verified but failed a business cross-check (order/amount mismatch).
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return IpnAck(**_IPN_ACK)
