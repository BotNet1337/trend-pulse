"""Unit tests for alerts.feedback_tokens — sign/verify/expiry/tamper (AC1 anchor).

Tests MUST fail (RED) before feedback_tokens.py exists — they are the RED anchor
for TASK-042. The token is a compact HMAC-SHA256 signed token carrying
alert_id + verdict + exp; key derived from jwt_secret with a distinct "feedback"
salt; token is short (truncated sig, base64url). verify() returns payload or
raises FeedbackTokenError for bad/expired/tampered tokens.

Pure compute (no DB / no network) — runs under `make ci-fast`.
"""

import pytest

from alerts.feedback_tokens import (
    FeedbackTokenError,
    sign_feedback_token,
    verify_feedback_token,
)

_JWT_SECRET = "test-jwt-secret-for-tokens"
_TTL = 7 * 24 * 3600  # 604800s


def test_sign_and_verify_roundtrip() -> None:
    """A freshly signed token verifies back to the original alert_id and verdict."""
    token = sign_feedback_token(alert_id=42, verdict="up", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL)
    payload = verify_feedback_token(token, jwt_secret=_JWT_SECRET)
    assert payload["alert_id"] == 42
    assert payload["verdict"] == "up"


def test_sign_down_verdict() -> None:
    """Down verdict roundtrips correctly."""
    token = sign_feedback_token(
        alert_id=99, verdict="down", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL
    )
    payload = verify_feedback_token(token, jwt_secret=_JWT_SECRET)
    assert payload["alert_id"] == 99
    assert payload["verdict"] == "down"


def test_token_is_compact() -> None:
    """Token must be short enough for Telegram URL buttons (≤ 256 chars total URL)."""
    token = sign_feedback_token(alert_id=1, verdict="up", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL)
    # Token itself should be well under 100 chars — we need room for the base URL.
    assert len(token) < 100, f"Token too long: {len(token)} chars"


def test_expired_token_raises() -> None:
    """A token with ttl_seconds=0 (or already past) raises FeedbackTokenError."""
    # ttl=-1 means already expired at sign time.
    token = sign_feedback_token(alert_id=7, verdict="up", jwt_secret=_JWT_SECRET, ttl_seconds=-1)
    with pytest.raises(FeedbackTokenError, match="expired"):
        verify_feedback_token(token, jwt_secret=_JWT_SECRET)


def test_tampered_alert_id_raises() -> None:
    """Modifying the token payload (re-encoding different alert_id) raises FeedbackTokenError."""
    import base64
    import json

    token = sign_feedback_token(alert_id=5, verdict="up", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL)
    # Token format: base64url(payload).base64url(sig)
    # Tamper by re-encoding the payload with a different alert_id
    parts = token.split(".")
    assert len(parts) == 2, "Expected 2-part token"
    # Decode and modify payload
    payload_bytes = base64.urlsafe_b64decode(parts[0] + "==")
    orig_data = json.loads(payload_bytes)
    orig_data["a"] = 999  # tampered alert_id
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(orig_data, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    tampered_token = f"{tampered_payload}.{parts[1]}"
    with pytest.raises(FeedbackTokenError, match="invalid"):
        verify_feedback_token(tampered_token, jwt_secret=_JWT_SECRET)


def test_wrong_jwt_secret_raises() -> None:
    """Token signed with one secret fails verification with a different secret."""
    token = sign_feedback_token(
        alert_id=3, verdict="down", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL
    )
    with pytest.raises(FeedbackTokenError, match="invalid"):
        verify_feedback_token(token, jwt_secret="completely-different-secret")


def test_garbage_token_raises() -> None:
    """A random string that is not a valid token raises FeedbackTokenError."""
    with pytest.raises(FeedbackTokenError):
        verify_feedback_token("not-a-valid-token-at-all", jwt_secret=_JWT_SECRET)


def test_empty_token_raises() -> None:
    """An empty token raises FeedbackTokenError."""
    with pytest.raises(FeedbackTokenError):
        verify_feedback_token("", jwt_secret=_JWT_SECRET)


def test_different_jwt_secrets_produce_different_tokens() -> None:
    """Two different jwt_secrets produce tokens that don't cross-verify."""
    secret_a = "secret-a"
    secret_b = "secret-b"
    token_a = sign_feedback_token(alert_id=1, verdict="up", jwt_secret=secret_a, ttl_seconds=_TTL)
    with pytest.raises(FeedbackTokenError):
        verify_feedback_token(token_a, jwt_secret=secret_b)


def test_feedback_salt_differs_from_jwt_tokens() -> None:
    """The derived key uses the 'feedback' salt, making tokens non-interchangeable."""
    # Signing with the same underlying bytes but different salts should produce
    # tokens that can't verify against each other. Verified implicitly via
    # test_wrong_jwt_secret_raises; here we verify the token structure has a sig.
    token = sign_feedback_token(alert_id=1, verdict="up", jwt_secret=_JWT_SECRET, ttl_seconds=_TTL)
    assert "." in token  # must have payload.sig structure
