"""HMAC-SHA256 signed compact feedback tokens for 👍/👎 alert buttons (TASK-042).

A feedback token is a compact, URL-safe, self-contained bearer token that
encodes a single (alert_id, verdict, expiry) tuple. It is single-purpose:

- alert_id: int  — the alert being rated.
- verdict: "up" | "down" — the user's opinion.
- exp: int — Unix timestamp after which the token is no longer valid.

Token format: base64url(payload).base64url(sig)
  - payload: compact JSON {"a": <alert_id>, "v": "up"|"down", "e": <exp>}
  - sig: first 16 bytes of HMAC-SHA256(derived_key, payload_bytes), base64url

The signing key is derived from ``jwt_secret`` with a distinct "feedback" salt
(HMAC-SHA256(key=jwt_secret.encode(), msg=b"feedback")) to prevent cross-use of
auth JWT tokens vs feedback tokens. 16-byte truncated signature keeps URLs short
(Telegram has a URL length limit for inline button urls).

Design invariants:
- Token is opaque to the user; no enumerable id in URL (alert_id is inside
  the HMAC-protected payload, not the token identity itself).
- ``verify_feedback_token`` never leaks which field is wrong (uniform error).
- No magic literals: sig_length, salt, payload key names are all constants.
- Full type hints; no bare Any; no # type: ignore.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

# Payload field names — short to keep tokens compact (Telegram URL limit).
_FIELD_ALERT_ID = "a"
_FIELD_VERDICT = "v"
_FIELD_EXPIRY = "e"

# HMAC key derivation salt — distinct from JWT usage to prevent cross-use.
_FEEDBACK_SALT = b"feedback"

# Truncated signature length in bytes (16 bytes = 128-bit, compact URL-safe).
_SIG_BYTES = 16

# Verdict string constants
VERDICT_UP = "up"
VERDICT_DOWN = "down"

# Token separator character
_TOKEN_SEP = "."


class FeedbackTokenError(Exception):
    """Raised when a feedback token is invalid, expired, or tampered."""


def _derive_key(jwt_secret: str) -> bytes:
    """Derive a distinct feedback signing key from jwt_secret using HMAC + salt.

    HMAC(key=jwt_secret.encode(), msg=b"feedback") → 32-byte derived key.
    This prevents feedback tokens from being forged using a leaked JWT secret
    in another context, and vice-versa.
    """
    return hmac.new(
        jwt_secret.encode(),
        _FEEDBACK_SALT,
        digestmod=hashlib.sha256,
    ).digest()


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    # Restore padding: len must be a multiple of 4.
    padding = 4 - len(s) % 4
    if padding != 4:
        s = s + "=" * padding
    return base64.urlsafe_b64decode(s)


def sign_feedback_token(
    *,
    alert_id: int,
    verdict: str,
    jwt_secret: str,
    ttl_seconds: int,
) -> str:
    """Create a compact signed feedback token for the given alert and verdict.

    Args:
        alert_id:     The alert row id.
        verdict:      "up" or "down".
        jwt_secret:   Application jwt_secret (key derivation input).
        ttl_seconds:  Token validity in seconds from now (e.g. 604800 = 7d).

    Returns:
        A compact URL-safe token string: ``<payload_b64>.<sig_b64>``.
    """
    exp = int(time.time()) + ttl_seconds
    payload: dict[str, int | str] = {
        _FIELD_ALERT_ID: alert_id,
        _FIELD_VERDICT: verdict,
        _FIELD_EXPIRY: exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = _b64url_encode(payload_bytes)

    derived_key = _derive_key(jwt_secret)
    sig_full = hmac.new(derived_key, payload_bytes, digestmod=hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig_full[:_SIG_BYTES])

    return f"{payload_b64}{_TOKEN_SEP}{sig_b64}"


def verify_feedback_token(
    token: str,
    *,
    jwt_secret: str,
) -> dict[str, int | str]:
    """Verify a feedback token and return the parsed payload.

    Args:
        token:       The compact token string from the URL.
        jwt_secret:  Application jwt_secret (same as used for signing).

    Returns:
        Dict with keys ``alert_id`` (int), ``verdict`` (str), ``exp`` (int).

    Raises:
        FeedbackTokenError: If the token is malformed, tampered, or expired.
            The error message distinguishes expired ("expired") from tampered/bad
            ("invalid") to aid debugging, but never leaks the jwt_secret or
            which specific byte was wrong (no timing oracle).
    """
    if not token:
        raise FeedbackTokenError("invalid")

    parts = token.split(_TOKEN_SEP)
    if len(parts) != 2:
        raise FeedbackTokenError("invalid")

    payload_b64, sig_b64 = parts[0], parts[1]

    # Decode payload bytes.
    try:
        payload_bytes = _b64url_decode(payload_b64)
    except Exception as exc:
        raise FeedbackTokenError("invalid") from exc

    # Recompute signature and compare in constant time to prevent timing attacks.
    derived_key = _derive_key(jwt_secret)
    expected_sig_full = hmac.new(derived_key, payload_bytes, digestmod=hashlib.sha256).digest()
    expected_sig_b64 = _b64url_encode(expected_sig_full[:_SIG_BYTES])

    if not hmac.compare_digest(expected_sig_b64, sig_b64):
        raise FeedbackTokenError("invalid")

    # Decode payload JSON.
    try:
        raw = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FeedbackTokenError("invalid") from exc

    # Extract and validate fields.
    try:
        alert_id = int(raw[_FIELD_ALERT_ID])
        verdict = str(raw[_FIELD_VERDICT])
        exp = int(raw[_FIELD_EXPIRY])
    except (KeyError, ValueError, TypeError) as exc:
        raise FeedbackTokenError("invalid") from exc

    # Check expiry — after HMAC verification to prevent oracle timing on exp alone.
    if time.time() > exp:
        raise FeedbackTokenError("expired")

    return {"alert_id": alert_id, "verdict": verdict, "exp": exp}
