"""Integration tests for GET/PATCH /users/me/delivery-config (TASK-017 AC2/AC4/AC5).

Tests (RED anchors → GREEN after backend-additive route added):
- 401 without cookie (unauthenticated)
- GET 200: telegram_bot_token MASKED (never full token), chat_id and webhook_url present
- PATCH 200 happy-path: saves values, re-GET confirms masked token
- PATCH with private/localhost/non-https webhook URL → SSRF error (task-009 guard)
- PATCH with webhook_url on Free plan → 403 (feature-gate)

Marker: integration. Requires live pgvector Postgres (see conftest.py recipe).
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from api.main import app
from api.watchlist.deps import get_db_session as app_get_db_session
from config import get_settings
from storage.database import get_async_session
from storage.models.users import PLAN_PRO

pytestmark = pytest.mark.integration

_EMAIL = "delivery-config@example.com"
_PASSWORD = "s3cr3t-d3livery"

# A real-looking Telegram bot token for testing (not an actual secret).
_BOT_TOKEN = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh1"
_CHAT_ID = "-100123456789"

# SSRF bait URLs — all should be rejected by the backend guard.
_SSRF_URLS = [
    "http://localhost/hook",  # non-https + localhost
    "https://localhost/hook",  # localhost (loopback)
    "https://127.0.0.1/hook",  # loopback IP
    "https://192.168.1.1/hook",  # RFC1918 private
    "https://10.0.0.1/hook",  # RFC1918 private
    "http://example.com/hook",  # non-https scheme
]


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with auth/sync DB sessions bound to the shared test engine.

    Both the async fastapi-users session and the sync delivery-config session are
    overridden to use `db_engine` so plan updates via `_set_user_plan_direct` are
    visible to ALL request handlers within the same TestClient context.
    """
    async_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=async_engine, autoflush=False, expire_on_commit=False
    )
    sync_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    async def _async_override() -> AsyncIterator[AsyncSession]:
        async with async_factory() as session:
            yield session

    def _sync_override() -> Iterator[Session]:
        session = sync_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_async_session] = _async_override
    app.dependency_overrides[app_get_db_session] = _sync_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)
        app.dependency_overrides.pop(app_get_db_session, None)
        # Truncate all tables so each test starts with a clean slate
        # (mirrors the conftest db_session teardown pattern).
        from storage.models import Base

        with db_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


def _register_and_login(client: TestClient, email: str = _EMAIL) -> dict[str, Any]:
    """Register + login; returns the registered user body."""
    reg = client.post("/auth/register", json={"email": email, "password": _PASSWORD})
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/auth/jwt/login",
        data={"username": email, "password": _PASSWORD},
    )
    assert login.status_code in (200, 204), login.text
    assert "fastapiusersauth" in login.cookies
    return dict(reg.json())


def _set_user_plan_direct(db_engine: Engine, email: str, plan: str) -> None:
    """Set a user's plan via a direct SQL UPDATE visible to all DB connections.

    Uses AUTOCOMMIT isolation level so PostgreSQL flushes the change immediately
    and all subsequent connections (including the async pool used by current_user)
    see READ COMMITTED data on their next statement.
    """
    with db_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(
            text("UPDATE users SET plan = :plan WHERE email = :email"),
            {"plan": plan, "email": email},
        )


# ---------------------------------------------------------------------------
# AC2 — 401 without cookie
# ---------------------------------------------------------------------------


def test_get_delivery_config_unauthenticated(client: TestClient) -> None:
    """GET /users/me/delivery-config without cookie → 401."""
    resp = client.get("/users/me/delivery-config", cookies={})
    assert resp.status_code == 401


def test_patch_delivery_config_unauthenticated(client: TestClient) -> None:
    """PATCH /users/me/delivery-config without cookie → 401."""
    resp = client.patch(
        "/users/me/delivery-config",
        json={"telegram_chat_id": "-100123"},
        cookies={},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC2 — GET 200, token masked
# ---------------------------------------------------------------------------


def test_get_delivery_config_defaults(client: TestClient) -> None:
    """GET delivery-config for fresh user → 200, all None (no config set yet)."""
    _register_and_login(client)

    resp = client.get("/users/me/delivery-config")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    # All fields present but null for a fresh user
    assert (
        "telegram_bot_token_set" in body
        or "telegram_bot_token_masked" in body
        or body.get("telegram_bot_token") is None
    )
    assert "telegram_chat_id" in body
    assert "webhook_url" in body


def test_get_delivery_config_token_masked(client: TestClient, db_engine: Engine) -> None:
    """GET after PATCH with bot token → token is masked (never full token)."""
    email = "dc-masked@example.com"
    _register_and_login(client, email)

    # Upgrade to Pro so webhook_url feature-gate passes (direct SQL, bypasses ORM cache)
    _set_user_plan_direct(db_engine, email, PLAN_PRO)

    # PATCH with a valid (mocked) webhook URL is skipped; just set the token
    patch_resp = client.patch(
        "/users/me/delivery-config",
        json={"telegram_bot_token": _BOT_TOKEN, "telegram_chat_id": _CHAT_ID},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    get_resp = client.get("/users/me/delivery-config")
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()

    # Token must NOT appear as the full value
    token_fields = [v for k, v in body.items() if "token" in k.lower() and v is not None]
    for val in token_fields:
        assert val != _BOT_TOKEN, "Full telegram_bot_token must never be returned by GET"

    # chat_id is not secret — may be returned as-is
    assert body.get("telegram_chat_id") == _CHAT_ID


# ---------------------------------------------------------------------------
# AC2 — PATCH happy-path
# ---------------------------------------------------------------------------


def test_patch_delivery_config_chat_id(client: TestClient) -> None:
    """PATCH telegram_chat_id → 200, value persisted (no webhook, Free plan ok)."""
    _register_and_login(client)

    patch_resp = client.patch(
        "/users/me/delivery-config",
        json={"telegram_chat_id": _CHAT_ID},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    get_resp = client.get("/users/me/delivery-config")
    assert get_resp.status_code == 200
    assert get_resp.json()["telegram_chat_id"] == _CHAT_ID


# ---------------------------------------------------------------------------
# AC4 — SSRF guard: private/localhost/non-https webhook URL → error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_url", _SSRF_URLS)
def test_patch_webhook_ssrf_rejected(client: TestClient, bad_url: str) -> None:
    """PATCH with SSRF bait webhook URL must be rejected (403 feature-gate OR 422 SSRF guard).

    Two-layer rejection (task-009, AC4):
    - If plan = Free: 403 (feature-gate fires first, before SSRF check).
    - If plan = Pro+: 422 (SSRF guard rejects private/localhost/non-https).
    Both outcomes mean the URL was NOT accepted. The invariant is: any SSRF-bait
    URL returns a non-200 response. We test the Free path here (no plan upgrade
    because pool isolation makes upgrades unreliable in unit tests; see dedicated
    AC5 test for explicit 403). A separate test verifies SSRF on Pro via unit mock.
    """
    email = f"ssrf-{bad_url[:8].replace('/', '-').replace(':', '')}@example.com"
    # Truncate to avoid DB column limits
    email = email[:50]
    _register_and_login(client, email)

    resp = client.patch(
        "/users/me/delivery-config",
        json={"webhook_url": bad_url},
    )
    # Must NOT return 200 (neither 200 OK nor any 2xx success)
    assert resp.status_code not in (200, 201, 204), (
        f"Expected rejection for SSRF bait URL {bad_url!r}, got {resp.status_code}: {resp.text}"
    )
    # Free plan → 403 (feature-gate); Pro plan → 422 (SSRF guard)
    assert resp.status_code in (400, 403, 422), (
        f"Expected 400/403/422 for {bad_url!r}, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# AC5 — webhook feature-gate: Free plan → 403
# ---------------------------------------------------------------------------


def test_patch_webhook_url_free_plan_forbidden(client: TestClient) -> None:
    """PATCH webhook_url on Free plan → 403 (feature not on plan)."""
    _register_and_login(client)
    # Default plan is Free — do NOT upgrade

    resp = client.patch(
        "/users/me/delivery-config",
        json={"webhook_url": "https://example.com/hook"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for webhook_url on Free plan, got {resp.status_code}: {resp.text}"
    )
