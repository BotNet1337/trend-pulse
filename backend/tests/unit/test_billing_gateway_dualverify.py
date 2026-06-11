"""AC1 — dual-verify: canonical-primary + raw-body fallback in verify_ipn.

Three branches:
1. Signature over CANONICAL (sorted-key JSON) → accepted silently (no mismatch event).
2. Signature over RAW bytes (body whose canonical form differs from raw) → accepted
   AND `billing.ipn_canonical_mismatch` log_event emitted with aggregate-only fields
   (raw_len, canonical_len, sha256 prefixes — no body content, no secret).
3. Signature invalid for both → IpnVerificationError.

NOWPayments canonicalises by sort_keys+compact; raw bytes can diverge on
non-ASCII unicode: raw body {"k":"é"} → raw bytes \xc3\xa9 (no escaping) vs
canonical bytes \\u00e9 (ensure_ascii=True default of json.dumps).

We use the non-ASCII case to reliably trigger canonical≠raw divergence.
"""

import hashlib
import hmac as _hmac
import json
from unittest.mock import patch

import pytest

from billing.gateway.base import IpnVerificationError
from billing.gateway.nowpayments import (
    IPN_CANONICAL_MISMATCH_EVENT,
    NowPaymentsGateway,
    _canonical_json,
)

_SECRET = "test-ipn-secret"
_SIG_HEADER = "x-nowpayments-sig"


def _gateway() -> NowPaymentsGateway:
    return NowPaymentsGateway(api_key="k", ipn_secret=_SECRET, base_url="http://np")


def _sign(data: bytes) -> str:
    return _hmac.new(_SECRET.encode("utf-8"), data, hashlib.sha512).hexdigest()


def _headers(sig: str) -> dict[str, str]:
    return {_SIG_HEADER: sig}


def _minimal_ipn_dict(**extra: object) -> dict[str, object]:
    """Minimal valid IPN body dict (passes _to_event parsing)."""
    body: dict[str, object] = {
        "payment_id": "pay-42",
        "order_id": "order-42",
        "payment_status": "finished",
        "price_amount": "29",
        "price_currency": "usd",
    }
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Helper: build raw bytes with non-ASCII value (ensure_ascii=False) whose
# canonical re-dump (ensure_ascii=True) differs.
# ---------------------------------------------------------------------------


def _diverging_raw_and_canonical() -> tuple[bytes, bytes]:
    """Return (raw_bytes, canonical_bytes) where raw ≠ canonical.

    The dict value contains a non-ASCII character (é = U+00E9).
    json.dumps with ensure_ascii=False keeps the utf-8 literal bytes;
    _canonical_json uses ensure_ascii=True (default), escaping to \\u00e9.
    """
    body = _minimal_ipn_dict(note="é")  # é → U+00E9
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    canonical = _canonical_json(body)
    assert raw != canonical, "Test precondition: raw must differ from canonical"
    return raw, canonical


# ---------------------------------------------------------------------------
# AC1-A: signature over canonical → accepted silently, no mismatch event
# ---------------------------------------------------------------------------


def test_canonical_sig_accepted_no_mismatch_event() -> None:
    """Canonical-path: signature over sorted-key JSON → OK, no log_event emitted."""
    body = _minimal_ipn_dict()
    canonical = _canonical_json(body)
    sig = _sign(canonical)

    gw = _gateway()
    with patch("billing.gateway.nowpayments.log_event") as mock_log:
        event = gw.verify_ipn(headers=_headers(sig), raw_body=canonical)

    assert event.payment_id == "pay-42"
    # No mismatch event must be emitted
    for c in mock_log.call_args_list:
        assert c.args[0] != IPN_CANONICAL_MISMATCH_EVENT, (
            f"Unexpected mismatch event emitted on canonical path: {c}"
        )


# ---------------------------------------------------------------------------
# AC1-B: signature over RAW bytes (diverges from canonical) → accepted +
#         mismatch log_event with aggregate-only fields
# ---------------------------------------------------------------------------


def test_raw_sig_accepted_and_mismatch_event_emitted() -> None:
    """Raw-body fallback: sig over raw accepted; mismatch event emitted."""
    raw, canonical = _diverging_raw_and_canonical()
    sig = _sign(raw)  # sign raw, NOT canonical

    gw = _gateway()
    with patch("billing.gateway.nowpayments.log_event") as mock_log:
        event = gw.verify_ipn(headers=_headers(sig), raw_body=raw)

    assert event.payment_id == "pay-42"

    # Exactly one mismatch event must be emitted
    mismatch_calls = [
        c for c in mock_log.call_args_list if c.args[0] == IPN_CANONICAL_MISMATCH_EVENT
    ]
    assert len(mismatch_calls) == 1, (
        f"Expected exactly 1 mismatch event; got {len(mismatch_calls)}: {mock_log.call_args_list}"
    )

    # Validate the kwargs: aggregate-only fields present, no forbidden content
    kwargs = mismatch_calls[0].kwargs
    assert "raw_len" in kwargs, "raw_len must be in mismatch event"
    assert "canonical_len" in kwargs, "canonical_len must be in mismatch event"
    assert "raw_sha256_prefix" in kwargs, "raw_sha256_prefix must be in mismatch event"
    assert "canonical_sha256_prefix" in kwargs, "canonical_sha256_prefix must be in mismatch event"

    # Sizes must be correct integers
    assert kwargs["raw_len"] == len(raw)
    assert kwargs["canonical_len"] == len(canonical)

    # sha256 prefix must be a hex string (at most 16 chars of hex)
    raw_prefix: str = kwargs["raw_sha256_prefix"]  # type: ignore[assignment]
    assert isinstance(raw_prefix, str) and len(raw_prefix) <= 16

    # NO body content must leak (no secret, no raw body text)
    forbidden_keys = {"body", "raw", "secret", "ipn_secret", "api_key", "text", "content"}
    for key in kwargs:
        assert key.lower() not in forbidden_keys, f"Forbidden key in mismatch event: {key!r}"


def test_mismatch_event_aggregate_only_no_body_content() -> None:
    """Security: mismatch event fields must be scalars, no nested objects."""
    raw, _ = _diverging_raw_and_canonical()
    sig = _sign(raw)

    gw = _gateway()
    with patch("billing.gateway.nowpayments.log_event") as mock_log:
        gw.verify_ipn(headers=_headers(sig), raw_body=raw)

    mismatch_calls = [
        c for c in mock_log.call_args_list if c.args[0] == IPN_CANONICAL_MISMATCH_EVENT
    ]
    assert mismatch_calls, "Expected mismatch event"
    kwargs = mismatch_calls[0].kwargs
    for key, value in kwargs.items():
        assert isinstance(value, (str, int, float, bool, type(None))), (
            f"Mismatch event field {key!r} must be a scalar; got {type(value)}"
        )


# ---------------------------------------------------------------------------
# AC1-C: signature invalid for both paths → IpnVerificationError
# ---------------------------------------------------------------------------


def test_invalid_sig_for_both_raises_verification_error() -> None:
    """Both canonical and raw miss → IpnVerificationError (→ 401)."""
    raw, _ = _diverging_raw_and_canonical()
    bad_sig = "deadbeef" * 16  # wrong signature

    gw = _gateway()
    with patch("billing.gateway.nowpayments.log_event"), pytest.raises(IpnVerificationError):
        gw.verify_ipn(headers=_headers(bad_sig), raw_body=raw)


def test_canonical_match_body_invalid_sig_no_mismatch_event() -> None:
    """Canonical path matches → no fallback, no mismatch event (optimistic path)."""
    body = _minimal_ipn_dict()
    canonical = _canonical_json(body)
    sig = _sign(canonical)

    # raw_body IS canonical here (they're the same bytes)
    gw = _gateway()
    with patch("billing.gateway.nowpayments.log_event") as mock_log:
        gw.verify_ipn(headers=_headers(sig), raw_body=canonical)

    mismatch_calls = [
        c for c in mock_log.call_args_list if c.args[0] == IPN_CANONICAL_MISMATCH_EVENT
    ]
    assert mismatch_calls == [], "No mismatch event when canonical matches"


# ---------------------------------------------------------------------------
# Regression: existing canonical-path test (unchanged semantics guard)
# ---------------------------------------------------------------------------


def test_missing_sig_header_raises() -> None:
    """No x-nowpayments-sig header → IpnVerificationError."""
    body = _minimal_ipn_dict()
    gw = _gateway()
    with pytest.raises(IpnVerificationError, match="missing"):
        gw.verify_ipn(headers={}, raw_body=json.dumps(body).encode())


def test_invalid_json_body_raises() -> None:
    """Non-JSON body → IpnVerificationError before any HMAC attempt."""
    gw = _gateway()
    raw = b"not json"
    sig = _sign(raw)
    with pytest.raises(IpnVerificationError, match="not valid JSON"):
        gw.verify_ipn(headers=_headers(sig), raw_body=raw)
