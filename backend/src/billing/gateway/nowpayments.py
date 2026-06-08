"""NOWPayments implementation of `PaymentGateway` (ADR-004).

`create_invoice` POSTs to the NOWPayments invoice endpoint with the API key header
and maps the response to our `Invoice` DTO. `verify_ipn` recomputes the IPN HMAC
and refuses to trust the body unless it matches.

IPN signature (NOWPayments): **HMAC-SHA512** over the JSON of the body with keys
sorted recursively and dumped compactly, keyed by the merchant IPN secret; the hex
digest rides in the `x-nowpayments-sig` header. We compare with
`hmac.compare_digest` (constant-time) and only parse the body after the signature
verifies. The API key and IPN secret are NEVER logged.
"""

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from billing.gateway.base import GatewayError, Invoice, IpnEvent, IpnVerificationError
from billing.plans import PRICE_CURRENCY, BillingPeriod, Plan, price_for
from storage.models.users import User

_SIG_HEADER = "x-nowpayments-sig"
_API_KEY_HEADER = "x-api-key"
_INVOICE_PATH = "/invoice"
# Bounds a hung NOWPayments API call (seconds) — named, not a magic literal.
_HTTP_TIMEOUT_SECONDS = 15


def _canonical_json(payload: dict[str, Any]) -> bytes:
    """Recursively key-sorted, compact JSON — the bytes NOWPayments signs."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _to_decimal(value: object, *, field: str) -> Decimal:
    """Parse a numeric field into Decimal; reject anything non-numeric."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise IpnVerificationError(f"IPN field {field!r} is not numeric")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IpnVerificationError(f"IPN field {field!r} is not a valid amount") from exc


class NowPaymentsGateway:
    """`PaymentGateway` over the NOWPayments REST API."""

    def __init__(self, *, api_key: str, ipn_secret: str, base_url: str) -> None:
        self._api_key = api_key
        self._ipn_secret = ipn_secret
        self._base_url = base_url.rstrip("/")

    def create_invoice(
        self, *, plan: Plan, period: BillingPeriod, user: User, order_id: str
    ) -> Invoice:
        """Create a NOWPayments invoice and map the response to our `Invoice`."""
        amount = price_for(plan)
        request_body = {
            "price_amount": str(amount),
            "price_currency": PRICE_CURRENCY,
            "order_id": order_id,
            "order_description": f"TrendPulse {plan.value} ({period.value})",
        }
        response = httpx.post(
            f"{self._base_url}{_INVOICE_PATH}",
            headers={_API_KEY_HEADER: self._api_key, "Content-Type": "application/json"},
            json=request_body,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        payment_url = data.get("invoice_url")
        if not isinstance(payment_url, str) or not payment_url:
            raise GatewayError("NOWPayments response missing invoice_url")
        returned_order = data.get("order_id")
        return Invoice(
            order_id=returned_order if isinstance(returned_order, str) else order_id,
            payment_url=payment_url,
            redirect_url=payment_url,
            amount=amount,
            currency=PRICE_CURRENCY,
        )

    def verify_ipn(self, *, headers: dict[str, str], raw_body: bytes) -> IpnEvent:
        """Verify the IPN HMAC-SHA512 signature (constant-time) → typed event.

        The body is parsed ONLY after the signature verifies (no trust on invalid).
        """
        provided = self._signature_header(headers)
        if provided is None:
            raise IpnVerificationError("missing x-nowpayments-sig header")

        # Parse first into a Python object so we can recompute the canonical form
        # NOWPayments signed (sorted-key compact JSON), independent of byte layout.
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise IpnVerificationError("IPN body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise IpnVerificationError("IPN body is not a JSON object")

        expected = hmac.new(
            self._ipn_secret.encode("utf-8"), _canonical_json(parsed), hashlib.sha512
        ).hexdigest()
        if not hmac.compare_digest(expected, provided):
            raise IpnVerificationError("IPN signature mismatch")

        return self._to_event(parsed)

    @staticmethod
    def _signature_header(headers: dict[str, str]) -> str | None:
        """Case-insensitive lookup of the signature header value."""
        for key, value in headers.items():
            if key.lower() == _SIG_HEADER:
                return value
        return None

    @staticmethod
    def _to_event(body: dict[str, Any]) -> IpnEvent:
        """Map a verified NOWPayments IPN body to our `IpnEvent` DTO."""
        payment_id = body.get("payment_id")
        order_id = body.get("order_id")
        status = body.get("payment_status")
        if not isinstance(payment_id, (str, int)) or payment_id == "":
            raise IpnVerificationError("IPN missing payment_id")
        if not isinstance(order_id, str) or order_id == "":
            raise IpnVerificationError("IPN missing order_id")
        if not isinstance(status, str) or status == "":
            raise IpnVerificationError("IPN missing payment_status")
        return IpnEvent(
            payment_id=str(payment_id),
            order_id=order_id,
            status=status,
            amount=_to_decimal(body.get("price_amount"), field="price_amount"),
            currency=str(body.get("price_currency", "")),
        )
