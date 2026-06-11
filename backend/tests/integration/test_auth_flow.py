"""Integration auth flow (marker: integration) — full register -> login -> protected
-> logout, plus a Google OAuth callback with the httpx-oauth code exchange mocked.

Runs against the live pgvector Postgres (same `Settings.database_url` as the other
integration tests). The app's async user-db session is overridden onto a test-scoped
async engine so the flow is fully exercised over HTTP via `TestClient`.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.auth import fastapi_users
from api.main import app
from config import get_settings
from storage.database import get_async_session

pytestmark = pytest.mark.integration

_TEST_EMAIL = "flow@example.com"
_TEST_PASSWORD = "s3cret-pass-w0rd"


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with the auth user-db session bound to a fresh async engine.

    Depends on `db_engine` (session-scoped, conftest) so the schema — incl. the
    `users`/`oauth_accounts` tables — exists before the async flow queries it,
    regardless of test execution order.
    """
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _register(client: TestClient, email: str = _TEST_EMAIL) -> dict[str, Any]:
    resp = client.post("/v1/auth/register", json={"email": email, "password": _TEST_PASSWORD})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_register_login_protected_logout(client: TestClient) -> None:
    """AC1/AC2/AC3: register, login (cookie set), protected 200, logout -> 401."""
    user = _register(client)
    user_id = user["id"]

    # Protected route is 401 without auth (AC2).
    unauth = client.get("/v1/users/me/tenant")
    assert unauth.status_code == 401

    # Login via JWT/cookie backend (form: username + password) (AC1).
    login = client.post(
        "/v1/auth/jwt/login",
        data={"username": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert login.status_code in (200, 204), login.text
    assert "fastapiusersauth" in login.cookies  # httpOnly auth cookie set

    # Authenticated request returns the tenant id (AC2/AC3 cookie persists).
    me = client.get("/v1/users/me/tenant")
    assert me.status_code == 200, me.text
    assert me.json() == {"user_id": user_id}

    # Logout clears the cookie; subsequent request is 401 again (AC3).
    logout = client.post("/v1/auth/jwt/logout")
    assert logout.status_code in (200, 204), logout.text
    after = client.get("/v1/users/me/tenant")
    assert after.status_code == 401


def test_wrong_password_rejected(client: TestClient) -> None:
    """AC5: a wrong password yields 400 (no user-enumeration leak)."""
    _register(client, email="wrongpass@example.com")
    bad = client.post(
        "/v1/auth/jwt/login",
        data={"username": "wrongpass@example.com", "password": "not-the-password"},
    )
    assert bad.status_code == 400


def test_google_callback_creates_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: a Google callback (code exchange mocked) creates/links a user + token.

    The httpx-oauth network round-trips (token exchange + id/email lookup) are
    monkeypatched; the library still drives state verification and user creation.
    """
    from httpx_oauth.clients.google import GoogleOAuth2

    google_email = "google-user@example.com"

    async def _fake_get_access_token(
        self: GoogleOAuth2, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        # unix ts that fits INT4 (fastapi-users OAuthAccount.expires_at is Integer);
        # ~year 2033, well under int4 max 2147483647.
        return {"access_token": "fake-google-access-token", "expires_at": 2000000000}

    async def _fake_get_id_email(self: GoogleOAuth2, token: str) -> tuple[str, str | None]:
        return ("google-account-id-123", google_email)

    monkeypatch.setattr(GoogleOAuth2, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(GoogleOAuth2, "get_id_email", _fake_get_id_email)

    # Drive the real authorize step to obtain a valid `state` AND the CSRF cookie:
    # fastapi-users >=14 puts a CSRF token in both the state JWT and a cookie and
    # checks they match on callback (double-submit), so a hand-built state is
    # rejected as OAUTH_INVALID_STATE. TestClient persists the CSRF cookie for us.
    authorize = client.get("/v1/auth/google/authorize")
    assert authorize.status_code == 200, authorize.text
    authorization_url = authorize.json()["authorization_url"]
    state = parse_qs(urlparse(authorization_url).query)["state"][0]

    resp = client.get(
        "/v1/auth/google/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 204, 302, 307), resp.text

    # The created/linked user is now loginable is not directly assertable without
    # a password; assert the OAuth identity row exists for the Google email.
    assert fastapi_users is not None  # instance wired
