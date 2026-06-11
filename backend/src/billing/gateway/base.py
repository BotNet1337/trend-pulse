"""Payment-gateway abstraction (ADR-004 §1).

The billing core depends ONLY on the `PaymentGateway` Protocol and the domain DTOs
below — never on NOWPayments directly. Swapping to CoinGate is a new Protocol
implementation with no change to `service`/`webhook`/`limits`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from billing.plans import BillingPeriod, Plan
from storage.models.users import User


class GatewayError(Exception):
    """Base class for payment-gateway errors."""


class IpnVerificationError(GatewayError):
    """The IPN signature was missing or did not verify — the body is NOT trusted."""


@dataclass(frozen=True)
class Invoice:
    """A created invoice the user pays. Immutable DTO (CONVENTIONS)."""

    order_id: str
    payment_url: str
    redirect_url: str | None
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class IpnEvent:
    """A verified IPN payload. Only constructed AFTER signature verification."""

    payment_id: str
    order_id: str
    status: str
    amount: Decimal
    currency: str
    # Amount actually paid so far (NOWPayments `actually_paid`, TASK-048) — used
    # by the underpaid notice to compute the remaining balance. Optional with a
    # default so existing constructions keep working; None when the field is
    # absent or unparseable (it never affects signature verification).
    actually_paid: Decimal | None = None


class PaymentGateway(Protocol):
    """Provider-agnostic gateway contract (create invoice + verify IPN)."""

    def create_invoice(
        self, *, plan: Plan, period: BillingPeriod, user: User, order_id: str
    ) -> Invoice:
        """Create a hosted invoice for the plan/period and return its pay URL."""
        ...

    def verify_ipn(self, *, headers: dict[str, str], raw_body: bytes) -> IpnEvent:
        """Verify the IPN HMAC signature and parse the (trusted) body into an event.

        Raises `IpnVerificationError` on a missing/invalid signature; the body must
        NOT be parsed or trusted before verification succeeds (ADR-004 §Security).
        """
        ...
