"""Integration tests for CSRF/Origin-check middleware (TASK-032 AC3).

Tests validate that the CSRFOriginMiddleware correctly:
- Blocks state-changing requests on cookie-auth sessions with missing Origin → 403.
- Blocks requests with an Origin not in the allow-list → 403.
- Passes requests with a same-origin Origin header → 2xx.
- Never blocks safe methods (GET/HEAD/OPTIONS) regardless of Origin.
- Passes /billing/ipn requests even without Origin (HMAC-verified webhook).
- Passes requests authenticated via X-API-Key header (machine clients).

Marker: integration. Requires live pgvector Postgres (see conftest.py recipe).
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.main import app
from config import get_settings
from storage.database import get_async_session

pytestmark = pytest.mark.integration

_EMAIL = "csrf-test@example.com"
_PASSWORD = "csrf-s3cr3t-pass"

# Dev-default allowed origin (matches _DEFAULT_ALLOWED_ORIGINS in config.py).
_ALLOWED_ORIGIN = "http://localhost"
# An origin NOT in the allow-list.
_FOREIGN_ORIGIN = "https://evil.example.com"


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with auth session bound to the shared test DB engine."""
    async_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=async_engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with async_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        with TestClient(app, raise_server_exceptions=True) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _register_and_login(client: TestClient) -> None:
    """Register a test user and log in, establishing a session cookie."""
    client.post(
        "/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    resp = client.post(
        "/v1/auth/jwt/login",
        data={"username": _EMAIL, "password": _PASSWORD},
    )
    assert resp.status_code in (200, 204), f"Login failed: {resp.text}"
    assert "fastapiusersauth" in resp.cookies or "fastapiusersauth" in client.cookies


# ---------------------------------------------------------------------------
# AC3 — CSRF middleware behaviour on cookie-auth mutations
# ---------------------------------------------------------------------------


def test_mutation_no_origin_blocked(client: TestClient) -> None:
    """Cookie-auth POST without Origin → 403 (CSRF protection fires)."""
    _register_and_login(client)

    # POST /v1/auth/jwt/logout is a cookie-auth mutation; no Origin header.
    resp = client.post("/v1/auth/jwt/logout")
    assert resp.status_code == 403, resp.text
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


def test_mutation_foreign_origin_blocked(client: TestClient) -> None:
    """Cookie-auth POST with an Origin not in the allow-list → 403."""
    _register_and_login(client)

    resp = client.post(
        "/v1/auth/jwt/logout",
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert resp.status_code == 403, resp.text
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


def test_mutation_same_origin_passes(client: TestClient) -> None:
    """Cookie-auth POST with an allowed Origin → passes (not 403)."""
    _register_and_login(client)

    # POST /v1/auth/jwt/logout with a same-origin header should pass the CSRF
    # check (logout itself may return 200 or 204).
    resp = client.post(
        "/v1/auth/jwt/logout",
        headers={"Origin": _ALLOWED_ORIGIN},
    )
    assert resp.status_code in (200, 204), (
        f"Expected 200/204 from logout with same-origin, got {resp.status_code}: {resp.text}"
    )


def test_get_never_blocked(client: TestClient) -> None:
    """GET requests are never blocked by CSRF middleware (safe method)."""
    _register_and_login(client)

    # GET /v1/users/me is a safe method — no Origin needed.
    resp = client.get("/v1/users/me")
    # Should be 200 (authenticated) or 4xx for other reasons, never 403 CSRF.
    assert resp.status_code != 403 or resp.json().get("error", {}).get("code") != "FORBIDDEN"


def test_get_without_origin_passes(client: TestClient) -> None:
    """GET without any Origin passes (safe method exemption)."""
    _register_and_login(client)

    resp = client.get("/v1/watchlists")
    # 200 OK (empty watchlist) — CSRF middleware never fires on GET.
    assert resp.status_code in (200, 404), resp.text


def test_unauthenticated_mutation_passes(client: TestClient) -> None:
    """Unauthenticated mutation without Origin passes CSRF check (no session cookie)."""
    # Register route is unauthenticated — no session cookie → CSRF skipped.
    resp = client.post(
        "/v1/auth/register",
        json={"email": "nocsrf-test@example.com", "password": "nocsrf-pass"},
    )
    # 201 (or 400 if already exists) — NEVER 403 CSRF.
    assert resp.status_code in (201, 400, 422), resp.text


def test_ipn_without_origin_passes(client: TestClient) -> None:
    """/billing/ipn POST without Origin passes CSRF (webhook exemption).

    The IPN endpoint is HMAC-verified; returning 403 CSRF would break NOWPayments
    callbacks. We expect 401 (invalid/missing signature) not 403 CSRF.
    """
    resp = client.post(
        "/v1/billing/ipn",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    # 401 (invalid sig) or 503 (billing not configured) — not 403 CSRF.
    assert resp.status_code in (400, 401, 503), (
        f"Expected 401/503 from IPN without sig, got {resp.status_code}: {resp.text}"
    )
    if resp.status_code == 403:
        body = resp.json()
        assert body.get("error", {}).get("code") != "FORBIDDEN", (
            "IPN endpoint should be exempt from CSRF check"
        )


def test_api_key_cookieless_request_passes(client: TestClient) -> None:
    """Cookieless X-API-Key request is exempt from CSRF (genuine machine client).

    The CSRF exemption for X-API-Key applies ONLY when no session cookie is present.
    A genuine machine client (programmatic API consumer) does not carry a browser
    session cookie — it is not a browser CSRF target, so it is exempt.

    We send a POST to a protected endpoint without logging in first (no cookie).
    The X-API-Key will be rejected by auth (401/403), but NOT with a CSRF 403.
    """
    # DO NOT call _register_and_login — we need no session cookie.
    resp = client.post(
        "/v1/watchlists",
        json={"name": "machine-test"},
        headers={"X-API-Key": "some-machine-key"},
    )
    # The API key is invalid (401) or the endpoint rejects the body (422),
    # but it must NOT be a CSRF FORBIDDEN (403 with code=FORBIDDEN).
    if resp.status_code == 403:
        body = resp.json()
        assert body.get("error", {}).get("code") != "FORBIDDEN", (
            f"Cookieless X-API-Key request must be exempt from CSRF check. Got: {body}"
        )


def test_delete_mutation_blocked_without_origin(client: TestClient) -> None:
    """Cookie-auth DELETE without Origin → 403 (state-changing method)."""
    _register_and_login(client)

    resp = client.delete("/v1/account")
    assert resp.status_code == 403, resp.text
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


def test_patch_mutation_blocked_without_origin(client: TestClient) -> None:
    """Cookie-auth PATCH without Origin → 403 (state-changing method)."""
    _register_and_login(client)

    resp = client.patch(
        "/v1/users/me/delivery-config",
        json={"telegram_chat_id": "-100123456"},
    )
    assert resp.status_code == 403, resp.text
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


def test_patch_with_same_origin_passes_csrf(client: TestClient) -> None:
    """Cookie-auth PATCH with same-origin → passes CSRF (may fail for other reasons)."""
    _register_and_login(client)

    resp = client.patch(
        "/v1/users/me/delivery-config",
        json={"telegram_chat_id": "-100123456"},
        headers={"Origin": _ALLOWED_ORIGIN},
    )
    # CSRF passes; result is 200 (valid patch) or 422/4xx for other reasons.
    assert resp.status_code != 403 or resp.json().get("error", {}).get("code") != "FORBIDDEN"


def test_null_origin_blocked(client: TestClient) -> None:
    """Cookie-auth mutation with Origin: null → 403 (sandboxed iframe rejection).

    RFC 6454 §7.3: browsers send `Origin: null` for sandboxed iframes and
    data: URIs. Accepting it would allow any cross-origin attacker with a
    sandboxed iframe to bypass the CSRF check. We must explicitly reject it.
    """
    _register_and_login(client)

    resp = client.post(
        "/v1/auth/jwt/logout",
        headers={"Origin": "null"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for Origin: null, got {resp.status_code}: {resp.text}"
    )
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN", f"Expected FORBIDDEN error code, got: {body}"


def test_api_key_with_session_cookie_still_csrf_checked(client: TestClient) -> None:
    """Cookie-auth + X-API-Key mutation without valid Origin → 403.

    A request carrying BOTH a session cookie AND X-API-Key is still subject
    to the Origin check — the session cookie is the CSRF attack surface.
    The X-API-Key exemption applies ONLY to cookieless machine clients.
    """
    _register_and_login(client)

    # Both session cookie (from login) and X-API-Key present, no Origin.
    resp = client.post(
        "/v1/auth/jwt/logout",
        headers={"X-API-Key": "some-machine-key"},
        # No Origin header — should be 403 because session cookie is present.
    )
    assert resp.status_code == 403, (
        f"Expected 403 when session cookie + X-API-Key without Origin, "
        f"got {resp.status_code}: {resp.text}"
    )
    body: dict[str, Any] = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"
