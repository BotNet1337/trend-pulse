"""Unit tests for delivery-config schemas and SSRF guard reuse (TASK-017 AC2/AC4).

Tests that do not require a DB:
- mask_bot_token: correct masking (last 4 chars, never full token)
- DeliveryConfigRead: model structure
- DeliveryConfigUpdate: model validation
- SSRF rejection (mocked socket.getaddrinfo): private/localhost/non-https URLs
  rejected by the backend guard (validates that delivery_config router correctly
  calls validate_webhook_url and maps WebhookValidationError → 422).
"""

from unittest.mock import MagicMock, patch

import pytest

from api.account.schemas import DeliveryConfigRead, DeliveryConfigUpdate, mask_bot_token

# ---------------------------------------------------------------------------
# mask_bot_token
# ---------------------------------------------------------------------------


def test_mask_bot_token_none_returns_none() -> None:
    """None input → None output (no token set)."""
    assert mask_bot_token(None) is None


def test_mask_bot_token_empty_returns_none() -> None:
    """Empty string → None (not set)."""
    assert mask_bot_token("") is None


def test_mask_bot_token_short_returns_mask_prefix() -> None:
    """Token shorter than 4 chars → masked without suffix (hidden but «set»)."""
    result = mask_bot_token("abc")
    assert result is not None
    assert result == "***"


def test_mask_bot_token_normal_shows_last_4() -> None:
    """Normal token → last 4 chars visible, rest masked."""
    token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh1"
    result = mask_bot_token(token)
    assert result is not None
    # Must end with last 4 chars of token
    assert result.endswith(token[-4:])
    # Must start with mask prefix
    assert result.startswith("***")
    # Must NOT equal the full token
    assert result != token


def test_mask_bot_token_never_exposes_full_token() -> None:
    """Masking must never return the full token value."""
    token = "secrettoken1234"
    result = mask_bot_token(token)
    assert result != token
    assert len(result or "") < len(token)


# ---------------------------------------------------------------------------
# DeliveryConfigRead
# ---------------------------------------------------------------------------


def test_delivery_config_read_all_none() -> None:
    """DeliveryConfigRead accepts all-None (fresh user with no config)."""
    model = DeliveryConfigRead(
        telegram_bot_token_masked=None,
        telegram_chat_id=None,
        webhook_url=None,
    )
    assert model.telegram_bot_token_masked is None
    assert model.telegram_chat_id is None
    assert model.webhook_url is None


def test_delivery_config_read_with_masked_token() -> None:
    """DeliveryConfigRead stores masked token, not the full value."""
    model = DeliveryConfigRead(
        telegram_bot_token_masked="***gh1",
        telegram_chat_id="-100123",
        webhook_url="https://example.com/hook",
    )
    assert model.telegram_bot_token_masked == "***gh1"
    assert model.telegram_chat_id == "-100123"


# ---------------------------------------------------------------------------
# DeliveryConfigUpdate
# ---------------------------------------------------------------------------


def test_delivery_config_update_all_none_is_valid() -> None:
    """DeliveryConfigUpdate with all None is valid (empty PATCH → no-op)."""
    model = DeliveryConfigUpdate()
    assert model.telegram_bot_token is None
    assert model.telegram_chat_id is None
    assert model.webhook_url is None


def test_delivery_config_update_partial() -> None:
    """DeliveryConfigUpdate with only some fields set."""
    model = DeliveryConfigUpdate(telegram_chat_id="-100999")
    assert model.telegram_chat_id == "-100999"
    assert model.telegram_bot_token is None
    assert model.webhook_url is None


def test_delivery_config_update_rejects_extra_fields() -> None:
    """extra='forbid' — unknown fields must raise a Pydantic validation error."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DeliveryConfigUpdate(telegram_chat_id="-100", unknown_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# SSRF guard reuse (unit: mocked socket) — validates delivery_config router
# calls validate_webhook_url which rejects private/localhost/non-https URLs.
# ---------------------------------------------------------------------------


def test_ssrf_guard_rejects_private_ip() -> None:
    """validate_webhook_url raises WebhookValidationError for private IP."""
    from alerts.errors import WebhookValidationError
    from alerts.security import validate_webhook_url

    with patch("socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("192.168.1.1", 0))]
        with pytest.raises(WebhookValidationError, match="non-public"):
            validate_webhook_url("https://internal.example.com/hook")


def test_ssrf_guard_rejects_loopback() -> None:
    """validate_webhook_url raises WebhookValidationError for loopback (127.0.0.1)."""
    from alerts.errors import WebhookValidationError
    from alerts.security import validate_webhook_url

    with patch("socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
        with pytest.raises(WebhookValidationError):
            validate_webhook_url("https://localhost/hook")


def test_ssrf_guard_rejects_http_scheme() -> None:
    """validate_webhook_url raises WebhookValidationError for non-https scheme."""
    from alerts.errors import WebhookValidationError
    from alerts.security import validate_webhook_url

    with pytest.raises(WebhookValidationError, match="scheme"):
        validate_webhook_url("http://example.com/hook")


def test_ssrf_guard_accepts_public_https() -> None:
    """validate_webhook_url passes for a public HTTPS host (mocked)."""
    from alerts.security import validate_webhook_url

    with patch("socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("1.2.3.4", 0))]
        # Should NOT raise
        result = validate_webhook_url("https://webhook.example.com/hook")
        assert result == "1.2.3.4"


# ---------------------------------------------------------------------------
# Router-level SSRF gate via TestClient (no DB required — mocked dependencies)
# ---------------------------------------------------------------------------


def _make_mock_user(plan: str = "pro") -> MagicMock:
    """Build a minimal User mock for delivery-config endpoint tests."""
    user = MagicMock()
    user.id = 1
    user.plan = plan
    user.telegram_bot_token = None
    user.telegram_chat_id = None
    user.webhook_url = None
    return user


def test_router_patch_ssrf_returns_422_for_pro_user() -> None:
    """PATCH delivery-config with SSRF URL and Pro user → 422 (SSRF guard fires)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from api.account.delivery_config import router
    from api.deps import current_user
    from api.watchlist.deps import get_db_session

    app = FastAPI()
    app.include_router(router)

    mock_user = _make_mock_user(plan="pro")
    mock_session = MagicMock(spec=Session)

    # Mock session.scalars().unique().one() to return db_user with pro plan
    db_user = MagicMock()
    db_user.id = 1
    db_user.plan = "pro"
    db_user.telegram_bot_token = None
    db_user.telegram_chat_id = None
    db_user.webhook_url = None
    mock_session.scalars.return_value.unique.return_value.one.return_value = db_user

    app.dependency_overrides[current_user] = lambda: mock_user
    app.dependency_overrides[get_db_session] = lambda: mock_session

    from billing.plans import Plan

    with (
        TestClient(app) as client,
        # Mock effective_plan to return PRO so the feature-gate passes
        # (assert_within_limit calls effective_plan → we bypass Subscription lookup).
        patch("billing.limits.effective_plan", return_value=Plan.PRO),
        patch("socket.getaddrinfo") as mock_gai,
    ):
        mock_gai.return_value = [(None, None, None, None, ("192.168.1.100", 0))]
        resp = client.patch(
            "/users/me/delivery-config",
            json={"webhook_url": "https://internal.corp/hook"},
        )

    assert resp.status_code == 422, (
        f"Expected 422 SSRF rejection, got {resp.status_code}: {resp.text}"
    )
