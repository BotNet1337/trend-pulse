"""Integration test for GET /users/me (TASK-014 AC2).

Verifies:
- 401 when no auth cookie is present
- 200 with email / plan / is_verified when authenticated via httpOnly cookie

Follows the pattern of test_auth_flow.py: live pgvector Postgres, TestClient,
async session override, pytestmark=pytest.mark.integration.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.main import app
from config import get_settings
from storage.database import get_async_session

pytestmark = pytest.mark.integration

_TEST_EMAIL = "me-route@example.com"
_TEST_PASSWORD = "s3cret-me-pass"


@pytest.fixture
def client(db_engine: Any) -> Iterator[TestClient]:
    """TestClient with auth user-db session bound to the shared test engine.

    Depends on `db_engine` (session-scoped in conftest) so schema (users,
    oauth_accounts) exists before the async flow queries it.
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


def _register_and_login(client: TestClient, email: str = _TEST_EMAIL) -> dict[str, Any]:
    """Register a fresh user and log in; returns the UserRead body from register."""
    reg = client.post(
        "/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    user: dict[str, Any] = reg.json()

    login = client.post(
        "/v1/auth/jwt/login",
        data={"username": email, "password": _TEST_PASSWORD},
    )
    assert login.status_code in (200, 204), login.text
    assert "fastapiusersauth" in login.cookies
    return user


def test_get_users_me_unauthenticated(client: TestClient) -> None:
    """AC2 (RED anchor): GET /users/me without cookie → 401."""
    resp = client.get("/v1/users/me")
    assert resp.status_code == 401


def test_get_users_me_authenticated(client: TestClient) -> None:
    """AC2: GET /users/me with valid cookie → 200, email/plan/is_verified present."""
    user = _register_and_login(client)

    resp = client.get("/v1/users/me")
    assert resp.status_code == 200, resp.text

    body: dict[str, Any] = resp.json()
    # Required fields
    assert body["email"] == user["email"]
    assert "plan" in body
    assert "is_verified" in body
    # plan defaults to "free" for a new user (storage/models/users.py PLAN_FREE)
    assert body["plan"] == "free"
    # New users are not verified by default (fastapi-users default)
    assert body["is_verified"] is False
    # TASK-063: client-side admin UX flag — present and False for a regular user.
    assert body["is_superuser"] is False


def test_get_users_me_superuser_flag_true(client: TestClient, db_engine: Any) -> None:
    """TASK-063: is_superuser=True on the model is reflected in /users/me.

    The flag is a UX hint only (the real gate is `current_superuser` on the
    ops route); here we just verify the additive field round-trips.
    """
    email = "me-route-superuser@example.com"
    _register_and_login(client, email=email)

    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET is_superuser = TRUE WHERE email = :email"),
            {"email": email},
        )

    resp = client.get("/v1/users/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_superuser"] is True
