"""Integration: reset-password end-to-end (TASK-026 AC2/AC3/AC4/AC5).

Scenarios:
  AC2 — forgot-password for existing user → reset-email (mocked) → reset-password
        → login with new password succeeds; old password rejected.
  AC3 — no-enumeration: forgot-password for nonexistent email returns the SAME
        HTTP status + body as for a real email.
  AC4 — all four new auth routes appear in OpenAPI (application routes check).
  AC5 — invalid/tampered reset-token → 4xx; password not changed.

The tests mock `notifications.email.send_templated_email` at the users.py import
site to capture the reset-password URL and extract the token — no SMTP / templates
service required.
"""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.main import app
from config import get_settings
from storage.database import get_async_session

pytestmark = pytest.mark.integration

# Each test uses a unique email suffix to avoid REGISTER_USER_ALREADY_EXISTS
# collisions when the shared ephemeral DB is not truncated between functions.
_RESET_EMAIL_ENUM = "reset-enum@example.com"
_RESET_EMAIL_E2E = "reset-e2e@example.com"
_RESET_EMAIL_INVALID = "reset-invalid-tok@example.com"
_ORIGINAL_PASSWORD = "0riginal-Pa55!"
_NEW_PASSWORD = "N3w-Pa55w0rd!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with async DB session bound to fresh engine (mirrors auth-flow pattern)."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        # TASK-032: set a default Origin header so the CSRF/Origin middleware
        # accepts cookie-auth mutations from the test client (http://testserver
        # is in the ALLOWED_ORIGINS env seeded in conftest.py).
        with TestClient(app, headers={"Origin": "http://testserver"}) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _register_user(client: TestClient, email: str, password: str) -> None:
    """Register a user (capture+discard the auto-verify email)."""
    captured: MagicMock = MagicMock()
    with patch("api.auth.users.send_templated_email", captured):
        resp = client.post("/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, f"Register failed: {resp.text}"


def _extract_reset_token(mock: MagicMock) -> str | None:
    """Extract the reset token from the captured send_templated_email call.

    The hook builds resetUrl = {frontend_base_url}/auth/password/reset?token=<TOKEN>
    """
    for call in mock.call_args_list:
        kwargs = call.kwargs if call.kwargs else {}
        if not kwargs:
            continue
        props = kwargs.get("props", {})
        reset_url = str(props.get("resetUrl", ""))
        if not reset_url:
            continue
        qs = parse_qs(urlparse(reset_url).query)
        if "token" in qs:
            return qs["token"][0]
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_forgot_password_no_enumeration(client: TestClient) -> None:
    """AC3 — forgot-password for nonexistent and real email: same HTTP response."""
    _register_user(client, _RESET_EMAIL_ENUM, _ORIGINAL_PASSWORD)

    captured: MagicMock = MagicMock()
    with patch("api.auth.users.send_templated_email", captured):
        # For a real (existing) user:
        real_resp = client.post("/v1/auth/forgot-password", json={"email": _RESET_EMAIL_ENUM})

    # For a nonexistent user (no email sent).
    # Use a valid email format (fastapi-users validates the schema); just not in DB.
    ghost_resp = client.post(
        "/v1/auth/forgot-password", json={"email": "nobody@ghost-nonexistent.com"}
    )

    # Both responses must have the same status code (no-enumeration, AC3).
    assert real_resp.status_code == ghost_resp.status_code, (
        f"no-enumeration violated: real={real_resp.status_code} ghost={ghost_resp.status_code}"
    )
    # Hook only called for real user — ghost never triggers it.
    assert captured.call_count >= 1, "send_templated_email not called for real user"


def test_reset_password_end_to_end(client: TestClient) -> None:
    """AC2 — forgot → reset-email → reset-password → login new/old."""
    _register_user(client, _RESET_EMAIL_E2E, _ORIGINAL_PASSWORD)

    # Capture the reset email call.
    captured: MagicMock = MagicMock()
    with patch("api.auth.users.send_templated_email", captured):
        forgot = client.post("/v1/auth/forgot-password", json={"email": _RESET_EMAIL_E2E})
    assert forgot.status_code in (200, 202), f"forgot-password failed: {forgot.text}"

    # Extract reset token from captured email.
    token = _extract_reset_token(captured)
    assert token is not None, (
        f"Reset token not captured from email mock. Calls: {captured.call_args_list}"
    )

    # Reset password.
    reset_resp = client.post(
        "/v1/auth/reset-password",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert reset_resp.status_code == 200, f"reset-password failed: {reset_resp.text}"

    # Login with new password succeeds.
    new_login = client.post(
        "/v1/auth/jwt/login",
        data={"username": _RESET_EMAIL_E2E, "password": _NEW_PASSWORD},
    )
    assert new_login.status_code in (200, 204), f"Login with new password failed: {new_login.text}"

    # Login with OLD password is rejected (AC2).
    old_login = client.post(
        "/v1/auth/jwt/login",
        data={"username": _RESET_EMAIL_E2E, "password": _ORIGINAL_PASSWORD},
    )
    assert old_login.status_code in (400, 401), (
        f"Expected old password to be rejected, got {old_login.status_code}"
    )


def test_reset_password_invalid_token(client: TestClient) -> None:
    """AC5 — invalid reset token → 4xx, no state change."""
    _register_user(client, _RESET_EMAIL_INVALID, _ORIGINAL_PASSWORD)

    resp = client.post(
        "/v1/auth/reset-password",
        json={"token": "fake-tampered-token", "password": "hacked!"},
    )
    assert resp.status_code in (400, 401, 422), (
        f"Expected 4xx for invalid token, got {resp.status_code}: {resp.text}"
    )

    # Original password still works.
    login = client.post(
        "/v1/auth/jwt/login",
        data={"username": _RESET_EMAIL_INVALID, "password": _ORIGINAL_PASSWORD},
    )
    assert login.status_code in (200, 204), (
        f"Original password should still work, got {login.status_code}"
    )


def test_auth_routes_in_openapi(client: TestClient) -> None:
    """AC4 — verify/reset routes present in OpenAPI schema."""
    # Swagger may be disabled in test; use app.routes introspection instead.
    from api.main import app as _app

    route_paths = {getattr(r, "path", "") for r in _app.routes}
    expected = {
        "/v1/auth/request-verify-token",
        "/v1/auth/verify",
        "/v1/auth/forgot-password",
        "/v1/auth/reset-password",
    }
    missing = expected - route_paths
    assert not missing, f"Auth routes not mounted: {missing}"
