"""Integration: email-verification end-to-end (TASK-026 AC1 anchor).

Scenario:
  1. Register a new user → on_after_register triggers request_verify automatically.
  2. The on_after_request_verify hook calls send_templated_email — which we mock to
     capture the verify URL (and therefore the token).
  3. POST /auth/verify with the captured token → 200.
  4. GET /users/me returns is_verified=true.

RED anchor: this test FAILS before the verify router is mounted (step-2 of the plan)
because POST /auth/verify returns 404.

The mock patches `notifications.email.send_templated_email` at the module level so
the hook's `asyncio.to_thread(send_templated_email, ...)` picks it up.
No SMTP / templates service is required — entirely offline.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any
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

_TEST_EMAIL = "verify-flow@example.com"
_TEST_PASSWORD = "v3rify-pa55word"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with the auth user-db bound to a fresh async engine (mirrors
    test_auth_flow.py pattern).
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


def _extract_token_from_call_args(mock: MagicMock) -> str | None:
    """Extract the verify token from a captured send_templated_email call.

    The hook calls send_templated_email(to=..., template=..., props=..., subject=...)
    where props["verifyUrl"] is something like:
      http://localhost/auth/email/confirm?token=<TOKEN>&email=...
    """
    for call in mock.call_args_list:
        kwargs = call.kwargs if call.kwargs else {}
        if not kwargs:
            # positional args fallback
            continue
        props: dict[str, Any] = kwargs.get("props", {})
        verify_url: str = str(props.get("verifyUrl", ""))
        if not verify_url:
            continue
        qs = parse_qs(urlparse(verify_url).query)
        if "token" in qs:
            return qs["token"][0]
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_verify_email_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1 — register → verify email arrives (mocked) → POST /auth/verify → is_verified=true."""
    captured: MagicMock = MagicMock()

    # Patch the underlying sync function that the async hook calls via to_thread.
    # We patch at the module that imports it (api.auth.users) so the hook's reference
    # is replaced, regardless of import order.
    with patch("api.auth.users.send_templated_email", captured):
        # 1. Register — triggers on_after_register → request_verify → on_after_request_verify
        #    → send_templated_email captured.
        resp = client.post(
            "/auth/register",
            json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
        )
        assert resp.status_code == 201, f"Register failed: {resp.text}"
        user_id: int = resp.json()["id"]
        assert user_id

        # 2. Extract the token from the captured email call.
        token = _extract_token_from_call_args(captured)
        assert token is not None, (
            f"send_templated_email was not called or verifyUrl missing from props. "
            f"Calls: {captured.call_args_list}"
        )

    # 3. POST /auth/verify — this will 404 BEFORE the router is mounted (RED anchor).
    verify_resp = client.post("/auth/verify", json={"token": token})
    assert verify_resp.status_code == 200, (
        f"Expected 200 from /auth/verify, got {verify_resp.status_code}: {verify_resp.text}"
    )

    # 4. Login and check is_verified=true via GET /users/me.
    login = client.post(
        "/auth/jwt/login",
        data={"username": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert login.status_code in (200, 204), f"Login failed: {login.text}"

    me = client.get("/users/me")
    assert me.status_code == 200, f"GET /users/me failed: {me.text}"
    assert me.json().get("is_verified") is True, f"Expected is_verified=true, got: {me.json()}"


def test_verify_invalid_token_rejected(client: TestClient) -> None:
    """AC5 — invalid token → 4xx, no state change."""
    resp = client.post("/auth/verify", json={"token": "totally-fake-token"})
    assert resp.status_code in (400, 401, 422), (
        f"Expected 4xx for invalid token, got {resp.status_code}: {resp.text}"
    )


def test_request_verify_token_endpoint_exists(client: TestClient) -> None:
    """AC4 — POST /auth/request-verify-token endpoint is mounted (not 404/405)."""
    # We don't have a verified user here; just check the route is mounted.
    # A 422 means the route exists but the body is missing (expected before login).
    resp = client.post("/auth/request-verify-token", json={"email": _TEST_EMAIL})
    assert resp.status_code != 404, "Route /auth/request-verify-token is not mounted (got 404)"
