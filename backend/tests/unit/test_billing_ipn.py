"""AC1 — IPN HMAC verification (RED-first anchor).

NOWPayments signs the IPN with HMAC-SHA512 over the **sorted-by-key JSON** of the
body, using the merchant's IPN secret; the signature rides in `x-nowpayments-sig`.
We verify with `hmac.compare_digest` (constant-time) and refuse to trust the body
when the signature is missing or wrong.

These tests are DB-free (gateway only). They were written before
`billing.gateway.nowpayments` existed (RED), then drove the implementation (GREEN).
"""

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from billing.gateway.base import IpnVerificationError
from billing.gateway.nowpayments import NowPaymentsGateway

_IPN_SECRET = "test-ipn-secret"
_WRONG_SECRET = "wrong-ipn-secret"
_SIG_HEADER = "x-nowpayments-sig"


def _ipn_body() -> dict[str, object]:
    return {
        "payment_id": "5077125051",
        "order_id": "order-abc-123",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }


def _sign(body: dict[str, object], secret: str) -> tuple[bytes, str]:
    """Return (raw_body, signature) the way NOWPayments signs IPNs."""
    sorted_json = json.dumps(body, sort_keys=True, separators=(",", ":"))
    raw = sorted_json.encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()
    return raw, sig


def _gateway() -> NowPaymentsGateway:
    return NowPaymentsGateway(api_key="unused", ipn_secret=_IPN_SECRET, base_url="http://x")


def test_verify_ipn_rejects_wrong_secret_signature() -> None:
    """AC1/AC4: a signature computed with the WRONG secret is rejected; no parse."""
    raw, sig = _sign(_ipn_body(), _WRONG_SECRET)
    with pytest.raises(IpnVerificationError):
        _gateway().verify_ipn(headers={_SIG_HEADER: sig}, raw_body=raw)


def test_verify_ipn_rejects_missing_signature() -> None:
    """AC4: a missing signature header is rejected before any body parsing."""
    raw, _ = _sign(_ipn_body(), _IPN_SECRET)
    with pytest.raises(IpnVerificationError):
        _gateway().verify_ipn(headers={}, raw_body=raw)


def test_verify_ipn_accepts_valid_signature() -> None:
    """A signature computed with the correct secret verifies → typed IpnEvent."""
    raw, sig = _sign(_ipn_body(), _IPN_SECRET)
    event = _gateway().verify_ipn(headers={_SIG_HEADER: sig}, raw_body=raw)
    assert event.payment_id == "5077125051"
    assert event.order_id == "order-abc-123"
    assert event.status == "finished"
    assert event.amount == Decimal("19")
    assert event.currency == "usd"


def test_verify_ipn_signature_is_case_insensitive_header() -> None:
    """Header lookup tolerates capitalization (servers normalize differently)."""
    raw, sig = _sign(_ipn_body(), _IPN_SECRET)
    event = _gateway().verify_ipn(headers={"X-Nowpayments-Sig": sig}, raw_body=raw)
    assert event.status == "finished"


def test_verify_ipn_tampered_body_rejected() -> None:
    """A valid signature over a DIFFERENT body does not verify the delivered body."""
    raw, sig = _sign(_ipn_body(), _IPN_SECRET)
    tampered = raw.replace(b"finished", b"confirmed")
    with pytest.raises(IpnVerificationError):
        _gateway().verify_ipn(headers={_SIG_HEADER: sig}, raw_body=tampered)
