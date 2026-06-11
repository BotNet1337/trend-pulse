"""Integration tests — unified error-envelope (TASK-030 AC1/AC2/AC4/AC7-server).

RED anchor: these tests FAIL before TASK-030 is implemented (current bodies are
`{"detail": ...}`; no error.code, no envelope). They drive the GREEN implementation.

Each test class exercises one error-source and asserts the full envelope shape:
    {"error": {"code": "<ErrorCode>", "message": "<str>", "details?": [...]}}

Test layout:
    TestUnauthorized    — 401 UNAUTHORIZED   (unauthenticated /v1/users/me)
    TestPlanLimitQuota  — 402 PLAN_LIMIT_EXCEEDED (free user, CHANNELS=0 → 402)
    TestFeatureNotAvailable — 403 FEATURE_NOT_AVAILABLE (api-key feature on free)
    TestNotFound        — 404 NOT_FOUND       (/v1/watchlists/999999)
    TestDuplicate       — 409 DUPLICATE       (duplicate watchlist creation)
    TestValidation      — 422 VALIDATION + details[{field, message}]
    TestRateLimited     — 429 RATE_LIMITED    (mini-app limiter override trick)
    TestBillingNotConfigured — 503 BILLING_NOT_CONFIGURED
    TestInternalSterile — 500 INTERNAL sterile (monkeypatched route)

Forbidden (403 non-plan) is skipped with a comment: all current 403s come from
PlanLimitExceeded (FEATURE_NOT_AVAILABLE); no plain-forbidden route exists yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.auth.api_key import current_user_or_api_key
from api.deps import current_user
from api.main import app
from api.rate_limit import rate_limit_handler, rate_limit_key
from api.watchlist.deps import get_db_session as watchlist_get_db_session
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import User

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SMALL_RATE_LIMIT = 1


def _assert_envelope(
    body: dict,  # type: ignore[type-arg]
    *,
    code: str,
    status: int | None = None,
) -> None:
    """Assert the unified envelope shape and code. `status` checked by caller."""
    assert "error" in body, f"Missing 'error' key in body: {body}"
    err = body["error"]
    assert "code" in err, f"Missing 'code' in error: {err}"
    assert "message" in err, f"Missing 'message' in error: {err}"
    assert err["code"] == code, f"Expected code={code!r}, got {err['code']!r}"
    assert isinstance(err["message"], str) and err["message"], (
        f"message must be a non-empty string, got {err['message']!r}"
    )


def _make_user(session: Session, email: str, plan: str = "pro") -> User:
    user = User(email=email, hashed_password="x" * 16, plan=plan)
    session.add(user)
    session.flush()
    if plan != "free":
        sub = Subscription(
            user_id=user.id,
            plan=plan,
            expires_at=utcnow() + timedelta(days=30),
        )
        session.add(sub)
        session.flush()
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with db_engine.begin() as conn:
            from storage.models import Base

            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    """TestClient with NO user overrides — exercises auth guards."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def authed_client(
    db_session_committing: Session,
) -> Iterator[tuple[TestClient, User]]:
    """TestClient with a Pro user wired to dependency overrides."""
    user = _make_user(db_session_committing, "envelope_test@example.com", plan="pro")

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_or_api_key] = lambda: user
    app.dependency_overrides[watchlist_get_db_session] = _session_override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, user
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(watchlist_get_db_session, None)


@pytest.fixture
def free_client(
    db_session_committing: Session,
) -> Iterator[tuple[TestClient, User]]:
    """TestClient with a Free plan user (CHANNELS=0 → 402 on create)."""
    user = _make_user(db_session_committing, "envelope_free@example.com", plan="free")

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_or_api_key] = lambda: user
    app.dependency_overrides[watchlist_get_db_session] = _session_override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, user
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(watchlist_get_db_session, None)


def _watchlist_payload(
    handle: str = "@testchan_envelope",
    topic: str = "env_topic",
) -> dict:  # type: ignore[type-arg]
    return {
        "topic": topic,
        "channel": {"handle": handle},
        "alert_config": {
            "score_threshold": 70,
            "min_channels": 2,
            "notification_lang": "en",
        },
    }


# ---------------------------------------------------------------------------
# AC1 — 401 UNAUTHORIZED
# ---------------------------------------------------------------------------


class TestUnauthorized:
    def test_unauth_users_me_returns_envelope_unauthorized(self, anon_client: TestClient) -> None:
        """Unauthenticated GET /v1/users/me → 401 envelope with code=UNAUTHORIZED."""
        resp = anon_client.get("/v1/users/me")
        assert resp.status_code == 401, resp.text
        _assert_envelope(resp.json(), code="UNAUTHORIZED")

    def test_unauth_tenant_returns_401_envelope(self, anon_client: TestClient) -> None:
        """Unauthenticated GET /v1/users/me/tenant → 401 envelope."""
        resp = anon_client.get("/v1/users/me/tenant")
        assert resp.status_code == 401, resp.text
        _assert_envelope(resp.json(), code="UNAUTHORIZED")


# ---------------------------------------------------------------------------
# AC1 — 402 PLAN_LIMIT_EXCEEDED (Free user, CHANNELS=0 — TASK-049)
# ---------------------------------------------------------------------------


class TestPlanLimitQuota:
    def test_free_user_watchlist_create_returns_402_envelope(
        self, free_client: tuple[TestClient, User]
    ) -> None:
        """Free plan CHANNELS=0 → POST /v1/watchlists → 402 PLAN_LIMIT_EXCEEDED envelope."""
        client, _ = free_client
        resp = client.post("/v1/watchlists", json=_watchlist_payload())
        assert resp.status_code == 402, resp.text
        _assert_envelope(resp.json(), code="PLAN_LIMIT_EXCEEDED")


# ---------------------------------------------------------------------------
# AC1 — 403 FEATURE_NOT_AVAILABLE (free user, api-key feature gate → 403)
# ---------------------------------------------------------------------------


class TestFeatureNotAvailable:
    def test_free_user_api_key_create_returns_403_envelope(
        self, free_client: tuple[TestClient, User]
    ) -> None:
        """Free plan API-key feature is gated → POST /v1/api-keys → 403 FEATURE_NOT_AVAILABLE."""
        client, _ = free_client
        resp = client.post("/v1/api-keys", json={"name": "test-key"})
        assert resp.status_code == 403, resp.text
        _assert_envelope(resp.json(), code="FEATURE_NOT_AVAILABLE")


# Note: 403 FORBIDDEN (non-plan-limit) — no current route produces a plain-403
# HTTPException that is not a PlanLimitExceeded. The generic HTTPException handler
# maps status 403 → FORBIDDEN for future use; skipping an integration test for it
# since it would require injecting a fake route, which is covered by the
# TestInternalSterile pattern instead.


# ---------------------------------------------------------------------------
# AC1 — 404 NOT_FOUND
# ---------------------------------------------------------------------------


class TestNotFound:
    def test_missing_watchlist_returns_404_envelope(
        self, authed_client: tuple[TestClient, User]
    ) -> None:
        """GET /v1/watchlists/999999 → 404 NOT_FOUND envelope."""
        client, _ = authed_client
        resp = client.get("/v1/watchlists/999999")
        assert resp.status_code == 404, resp.text
        _assert_envelope(resp.json(), code="NOT_FOUND")


# ---------------------------------------------------------------------------
# AC1 — 409 DUPLICATE
# ---------------------------------------------------------------------------


class TestDuplicate:
    def test_duplicate_watchlist_returns_409_envelope(
        self, authed_client: tuple[TestClient, User]
    ) -> None:
        """POST /v1/watchlists twice with same channel → 409 DUPLICATE envelope."""
        client, _ = authed_client
        payload = _watchlist_payload(handle="@dup_chan_envelope", topic="dup_topic")
        first = client.post("/v1/watchlists", json=payload)
        assert first.status_code == 201, first.text
        second = client.post("/v1/watchlists", json=payload)
        assert second.status_code == 409, second.text
        _assert_envelope(second.json(), code="DUPLICATE")


# ---------------------------------------------------------------------------
# AC1/AC4 — 422 VALIDATION + details[{field, message}]
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_payload_returns_422_envelope_with_details(
        self, authed_client: tuple[TestClient, User]
    ) -> None:
        """POST /v1/watchlists with bad handle → 422 VALIDATION + details list."""
        client, _ = authed_client
        resp = client.post(
            "/v1/watchlists",
            json=_watchlist_payload(handle="@bad handle!"),  # invalid — space in handle
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        _assert_envelope(body, code="VALIDATION")
        err = body["error"]
        assert "details" in err, f"details missing from 422 envelope: {err}"
        details = err["details"]
        assert isinstance(details, list) and len(details) > 0, (
            f"details must be a non-empty list, got {details!r}"
        )
        # Each item must have {field, message}
        for item in details:
            assert "field" in item, f"detail item missing 'field': {item}"
            assert "message" in item, f"detail item missing 'message': {item}"

    def test_missing_required_field_422_envelope(
        self, authed_client: tuple[TestClient, User]
    ) -> None:
        """POST /v1/watchlists with missing 'topic' → 422 VALIDATION envelope."""
        client, _ = authed_client
        # Omit required 'topic' field
        resp = client.post(
            "/v1/watchlists",
            json={
                "channel": {"handle": "@valid_chan"},
                "alert_config": {
                    "score_threshold": 70,
                    "min_channels": 2,
                    "notification_lang": "en",
                },
            },
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        _assert_envelope(body, code="VALIDATION")
        # details must carry the 'topic' field reference (no 'body' prefix)
        details = body["error"]["details"]
        field_names = [d["field"] for d in details]
        assert any("topic" in f for f in field_names), (
            f"Expected 'topic' in field names, got {field_names!r}"
        )


# ---------------------------------------------------------------------------
# AC1 — 429 RATE_LIMITED (mini-app limiter trick, mirrors test_feedback_api.py)
# ---------------------------------------------------------------------------


class TestRateLimited:
    def test_rate_limit_returns_429_envelope(self) -> None:
        """429 from slowapi → RATE_LIMITED envelope (no internal detail leaked)."""
        mini_app = FastAPI()
        test_limiter = Limiter(
            key_func=rate_limit_key,
            default_limits=[f"{_SMALL_RATE_LIMIT}/minute"],
            storage_uri="memory://",
        )
        mini_app.state.limiter = test_limiter
        mini_app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
        mini_app.add_middleware(SlowAPIMiddleware)

        @mini_app.get("/probe")
        def _probe() -> dict:  # type: ignore[type-arg]
            return {"ok": True}

        with TestClient(mini_app, raise_server_exceptions=False) as c:
            # Exhaust the 1/minute budget
            r1 = c.get("/probe")
            assert r1.status_code == 200
            r2 = c.get("/probe")
            assert r2.status_code == 429, f"Expected 429, got {r2.status_code}"
            _assert_envelope(r2.json(), code="RATE_LIMITED")


# ---------------------------------------------------------------------------
# AC1 — 503 BILLING_NOT_CONFIGURED
# ---------------------------------------------------------------------------


class TestBillingNotConfigured:
    def test_billing_invoice_without_credentials_returns_503_envelope(
        self, authed_client: tuple[TestClient, User]
    ) -> None:
        """POST /v1/billing/invoice without NOWPayments creds → 503 envelope.

        The test environment has NOWPAYMENTS_API_KEY unset by default so hitting
        the billing invoice endpoint raises BillingNotConfiguredError → 503.
        The payload is a valid InvoiceRequest (plan="pro", period="month") so that
        validation passes and the request always reaches the billing service path,
        making the 503 assertion unconditional.
        """
        client, _ = authed_client
        # Valid InvoiceRequest: plan must be a non-free paid plan; period defaults to "month".
        resp = client.post("/v1/billing/invoice", json={"plan": "pro", "period": "month"})
        assert resp.status_code == 503, (
            f"Expected 503 BILLING_NOT_CONFIGURED, got {resp.status_code}: {resp.text}"
        )
        _assert_envelope(resp.json(), code="BILLING_NOT_CONFIGURED")


# ---------------------------------------------------------------------------
# AC1/AC7 — 500 INTERNAL sterile (no traceback/repr in body)
# ---------------------------------------------------------------------------

_SENTINEL = "SENTINEL-LEAK-7f3a9c2b"
_SENTINEL_ROUTE = "/test-internal-sterile-boom"


class TestInternalSterile:
    def test_unexpected_exception_returns_sterile_500_envelope(self) -> None:
        """Generic Exception in a route → 500 INTERNAL envelope; no stack in body.

        Exercises the REAL api.main.app handler (_generic_handler) by temporarily
        injecting a raising route and tearing it down in the finally block to avoid
        cross-test pollution.
        """

        # Inject a temporary raising route onto the REAL app.
        # The sentinel string must NOT appear in the 500 response body (AC7).
        async def _boom_route() -> dict:  # type: ignore[type-arg]
            raise RuntimeError(f"{_SENTINEL} internal detail with /home/user/path")

        app.router.add_api_route(_SENTINEL_ROUTE, _boom_route, methods=["GET"])
        # Force route rebuild so the new route is recognised.
        app.openapi_schema = None

        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(_SENTINEL_ROUTE)
                assert resp.status_code == 500, resp.text
                body = resp.json()
                # Envelope shape (AC1): exactly {error: {code, message}} — no extra keys.
                assert set(body.keys()) == {"error"}, (
                    f"Extra keys in 500 body: {set(body.keys()) - {'error'}}"
                )
                _assert_envelope(body, code="INTERNAL")
                # Security AC7: no internal detail in the response body.
                raw = resp.text
                assert _SENTINEL not in raw, "Sentinel leaked in 500 body (internal detail exposed)"
                assert "RuntimeError" not in raw, "Exception class leaked in 500 body"
                assert "Traceback" not in raw, "Traceback leaked in 500 body"
                assert "/home" not in raw, "Internal path leaked in 500 body"
        finally:
            # Remove the injected route — avoids pollution across test sessions.
            app.router.routes = [
                r
                for r in app.router.routes
                if not (hasattr(r, "path") and r.path == _SENTINEL_ROUTE)
            ]
            app.openapi_schema = None
