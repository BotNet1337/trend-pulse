"""Integration tests for the superuser pool-admin API (TASK-116).

Covers (per the task ACs):
  * auth matrix — anonymous → 401, regular user → 403, superuser → 200
    (across all three endpoints);
  * `POST /pool-admin/qr-login/start` — happy path (200 with token/qr_url/
    expires_at/timeout_seconds), 503 when creds unconfigured, 429 at capacity;
  * `GET /pool-admin/qr-login/{token}` — happy (success carries session_string)
    and unknown/expired token → status `expired` (200, not 404/500);
  * `GET /pool-admin/pool-health` — fresh snapshot (stale=false, aggregates +
    accounts) and missing/old snapshot (stale=true).

QR service and Redis are FAKED via `app.dependency_overrides` so no network /
telethon is touched. The DB-backed superuser fixture mirrors
test_ops_business_metrics.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from api.main import app
from api.routes.pool_admin import get_pool_health_redis, get_qr_login_service
from collector.constants import POOL_HEALTH_REDIS_KEY
from collector.errors import QRLoginCapacityError, QRLoginNotConfiguredError
from collector.telegram.qr_login import QRLoginPoll, QRLoginStarted, QRLoginStatus
from config import get_settings
from storage.database import get_async_session
from storage.models.users import User

pytestmark = pytest.mark.integration

_TEST_PASSWORD = "test-pass-w0rd"
_QR_PATH_START = "/v1/pool-admin/qr-login/start"
_POOL_HEALTH_PATH = "/v1/pool-admin/pool-health"


def _qr_poll_path(token: str) -> str:
    return f"/v1/pool-admin/qr-login/{token}"


# ---------------------------------------------------------------------------
# Fakes for the QR-login service (no telethon, no network)
# ---------------------------------------------------------------------------


class _FakeQRService:
    """Configurable stand-in for QRLoginService used in start/poll tests."""

    def __init__(
        self,
        *,
        start_result: QRLoginStarted | None = None,
        start_error: Exception | None = None,
        poll_result: QRLoginPoll | None = None,
    ) -> None:
        self._start_result = start_result
        self._start_error = start_error
        self._poll_result = poll_result

    async def start(self) -> QRLoginStarted:
        if self._start_error is not None:
            raise self._start_error
        assert self._start_result is not None
        return self._start_result

    async def poll(self, token: str) -> QRLoginPoll:
        assert self._poll_result is not None
        return self._poll_result


class _RaisingRedis:
    """`_RedisLike` whose `get` raises RedisError (Redis unreachable path).

    `close` deliberately raises too, to prove the teardown guard cannot mask the
    in-flight 503 with an unhandled 500.
    """

    def get(self, name: str) -> str | None:
        raise RedisError("connection refused")

    def close(self) -> None:
        raise RedisError("close on broken socket")


class _RawRedis:
    """`_RedisLike` returning a fixed raw payload (for malformed-snapshot tests)."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def get(self, name: str) -> str | None:
        return self._raw

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Any) -> Iterator[TestClient]:
    """TestClient with the async session wired to the shared test schema."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        # TASK-032: a default Origin header so the CSRF/Origin middleware admits the
        # state-changing POST /qr-login/start on a cookie-auth session (mirrors
        # test_delivery_config.py). The Origin is in conftest's ALLOWED_ORIGINS.
        with TestClient(app, headers={"Origin": "http://testserver"}) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)
        app.dependency_overrides.pop(get_qr_login_service, None)
        app.dependency_overrides.pop(get_pool_health_redis, None)


def _register(client: TestClient, email: str) -> dict[str, Any]:
    resp = client.post("/v1/auth/register", json={"email": email, "password": _TEST_PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/v1/auth/jwt/login",
        data={"username": email, "password": _TEST_PASSWORD},
    )
    assert resp.status_code in (200, 204), resp.text


def _login_as_superuser(client: TestClient, db_session: Session, email: str) -> None:
    """Register `email`, promote to superuser in the DB, and log in."""
    user_data = _register(client, email)
    db_session.execute(update(User).where(User.id == user_data["id"]).values(is_superuser=True))
    db_session.commit()
    _login(client, email)


def _override_qr_service(service: _FakeQRService) -> None:
    app.dependency_overrides[get_qr_login_service] = lambda: service


def _seed_pool_health(snapshot: dict[str, Any]) -> fakeredis.FakeRedis:
    """Return a fakeredis pre-seeded with a pool-health snapshot, wired as the dep."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    redis.set(POOL_HEALTH_REDIS_KEY, json.dumps(snapshot))
    app.dependency_overrides[get_pool_health_redis] = lambda: redis
    return redis


def _fresh_snapshot() -> dict[str, Any]:
    as_of = datetime.now(UTC).isoformat()
    return {
        "size": 3,
        "cooling": 1,
        "quarantined": 0,
        "healthy": 2,
        "target": 2,
        "degraded": False,
        "as_of": as_of,
        "accounts": [
            {
                "index": 0,
                "state": "healthy",
                "cooldown_remaining_seconds": None,
                "last_error_reason": "",
            },
            {
                "index": 1,
                "state": "cooling",
                "cooldown_remaining_seconds": 42.0,
                "last_error_reason": "FLOOD_WAIT",
            },
            {
                "index": 2,
                "state": "healthy",
                "cooldown_remaining_seconds": None,
                "last_error_reason": "",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Auth matrix
# ---------------------------------------------------------------------------


class TestAuthMatrix:
    def test_anonymous_gets_401_on_all_routes(self, client: TestClient) -> None:
        assert client.post(_QR_PATH_START).status_code == 401
        assert client.get(_qr_poll_path("tok")).status_code == 401
        assert client.get(_POOL_HEALTH_PATH).status_code == 401

    def test_regular_user_gets_403_on_all_routes(
        self, client: TestClient, db_session: Session
    ) -> None:
        _register(client, "pa-regular@example.com")
        _login(client, "pa-regular@example.com")

        assert client.post(_QR_PATH_START).status_code == 403
        assert client.get(_qr_poll_path("tok")).status_code == 403
        assert client.get(_POOL_HEALTH_PATH).status_code == 403

    def test_superuser_reaches_pool_health(self, client: TestClient, db_session: Session) -> None:
        _seed_pool_health(_fresh_snapshot())
        _login_as_superuser(client, db_session, "pa-super-health@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# POST /pool-admin/qr-login/start
# ---------------------------------------------------------------------------


class TestQRLoginStart:
    def test_start_happy_path(self, client: TestClient, db_session: Session) -> None:
        started = QRLoginStarted(
            token="abc123", qr_url="tg://login?token=xyz", expires_at=1_700_000_000.0
        )
        _override_qr_service(_FakeQRService(start_result=started))
        _login_as_superuser(client, db_session, "pa-start@example.com")

        resp = client.post(_QR_PATH_START)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token"] == "abc123"
        assert body["qr_url"] == "tg://login?token=xyz"
        assert body["expires_at"] == 1_700_000_000.0
        assert body["timeout_seconds"] == get_settings().qr_login_timeout_seconds

    def test_start_unconfigured_returns_503(self, client: TestClient, db_session: Session) -> None:
        _override_qr_service(_FakeQRService(start_error=QRLoginNotConfiguredError("no creds")))
        _login_as_superuser(client, db_session, "pa-start-503@example.com")

        resp = client.post(_QR_PATH_START)
        assert resp.status_code == 503, resp.text
        # No secret/stack leak — message is the generic deployment hint.
        body = resp.json()
        assert "error" in body
        assert "no creds" not in json.dumps(body)

    def test_start_at_capacity_returns_429(self, client: TestClient, db_session: Session) -> None:
        _override_qr_service(_FakeQRService(start_error=QRLoginCapacityError("full")))
        _login_as_superuser(client, db_session, "pa-start-429@example.com")

        resp = client.post(_QR_PATH_START)
        assert resp.status_code == 429, resp.text


# ---------------------------------------------------------------------------
# GET /pool-admin/qr-login/{token}
# ---------------------------------------------------------------------------


class TestQRLoginPoll:
    def test_poll_success_carries_session_string(
        self, client: TestClient, db_session: Session
    ) -> None:
        poll = QRLoginPoll(
            status=QRLoginStatus.SUCCESS,
            expires_at=1_700_000_000.0,
            session_string="1Aa-the-new-session",
        )
        _override_qr_service(_FakeQRService(poll_result=poll))
        _login_as_superuser(client, db_session, "pa-poll-ok@example.com")

        resp = client.get(_qr_poll_path("abc123"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        assert body["session_string"] == "1Aa-the-new-session"
        assert body["reason"] is None

    def test_poll_unknown_token_is_expired_not_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        poll = QRLoginPoll(status=QRLoginStatus.EXPIRED, expires_at=1_700_000_000.0)
        _override_qr_service(_FakeQRService(poll_result=poll))
        _login_as_superuser(client, db_session, "pa-poll-expired@example.com")

        resp = client.get(_qr_poll_path("unknown-token"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "expired"
        assert body["session_string"] is None

    @pytest.mark.parametrize(
        ("status_enum", "wire", "reason"),
        [
            (QRLoginStatus.PASSWORD_NEEDED, "password_needed", "2FA password required"),
            (QRLoginStatus.ERROR, "error", "SessionRevokedError"),
        ],
    )
    def test_poll_non_success_surfaces_reason_without_session(
        self,
        client: TestClient,
        db_session: Session,
        status_enum: QRLoginStatus,
        wire: str,
        reason: str,
    ) -> None:
        poll = QRLoginPoll(status=status_enum, expires_at=1_700_000_000.0, reason=reason)
        _override_qr_service(_FakeQRService(poll_result=poll))
        _login_as_superuser(client, db_session, f"pa-poll-{wire}@example.com")

        resp = client.get(_qr_poll_path("abc123"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == wire
        assert body["reason"] == reason
        assert body["session_string"] is None


# ---------------------------------------------------------------------------
# GET /pool-admin/pool-health
# ---------------------------------------------------------------------------


class TestPoolHealth:
    def test_fresh_snapshot(self, client: TestClient, db_session: Session) -> None:
        snapshot = _fresh_snapshot()
        _seed_pool_health(snapshot)
        _login_as_superuser(client, db_session, "pa-health-fresh@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stale"] is False
        assert body["size"] == 3
        assert body["cooling"] == 1
        assert body["healthy"] == 2
        assert body["target"] == 2
        assert body["degraded"] is False
        assert body["as_of"] == snapshot["as_of"]
        assert len(body["accounts"]) == 3
        cooling = next(a for a in body["accounts"] if a["state"] == "cooling")
        assert cooling["index"] == 1
        assert cooling["cooldown_remaining_seconds"] == 42.0
        assert cooling["last_error_reason"] == "FLOOD_WAIT"

    def test_fresh_snapshot_defaults_ingest_contradiction_false(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A legacy snapshot WITHOUT `ingest_contradiction` validates (extra=ignore) and
        the response defaults the flag to false (TASK-118 additive, backward-compatible)."""
        _seed_pool_health(_fresh_snapshot())
        _login_as_superuser(client, db_session, "pa-health-contra-default@example.com")

        body = client.get(_POOL_HEALTH_PATH).json()
        assert body["ingest_contradiction"] is False

    def test_snapshot_passes_through_ingest_contradiction_and_failing(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The API passes through the collector-derived `ingest_contradiction` flag and a
        `failing` per-account state (TASK-118)."""
        snapshot = _fresh_snapshot()
        snapshot["ingest_contradiction"] = True
        snapshot["accounts"][0]["state"] = "failing"
        snapshot["accounts"][0]["last_error_reason"] = "WrongSessionIdError"
        _seed_pool_health(snapshot)
        _login_as_superuser(client, db_session, "pa-health-contra@example.com")

        body = client.get(_POOL_HEALTH_PATH).json()
        assert body["ingest_contradiction"] is True
        failing = next(a for a in body["accounts"] if a["state"] == "failing")
        assert failing["last_error_reason"] == "WrongSessionIdError"

    def test_missing_snapshot_is_stale(self, client: TestClient, db_session: Session) -> None:
        # Empty fakeredis (no key) wired as the dependency.
        redis = fakeredis.FakeRedis(decode_responses=True)
        app.dependency_overrides[get_pool_health_redis] = lambda: redis
        _login_as_superuser(client, db_session, "pa-health-missing@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stale"] is True
        assert body["size"] == 0
        assert body["accounts"] == []
        assert body["as_of"] is None

    def test_old_snapshot_is_stale(self, client: TestClient, db_session: Session) -> None:
        snapshot = _fresh_snapshot()
        old = datetime.now(UTC) - timedelta(seconds=10 * get_settings().collect_interval_seconds)
        snapshot["as_of"] = old.isoformat()
        _seed_pool_health(snapshot)
        _login_as_superuser(client, db_session, "pa-health-old@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Aggregates still surfaced, but flagged stale.
        assert body["stale"] is True
        assert body["size"] == 3
        assert len(body["accounts"]) == 3

    def test_redis_unreachable_returns_503_without_leak(
        self, client: TestClient, db_session: Session
    ) -> None:
        # get() raises RedisError; the teardown close() also raises — neither may
        # turn into an unhandled 500, and no DSN/exception text may leak.
        app.dependency_overrides[get_pool_health_redis] = lambda: _RaisingRedis()
        _login_as_superuser(client, db_session, "pa-health-redis-down@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 503, resp.text
        leaked = json.dumps(resp.json())
        assert "connection refused" not in leaked
        assert "broken socket" not in leaked

    @pytest.mark.parametrize(
        "raw",
        [
            "}{ not json at all",  # JSONDecodeError branch
            '{"size": 1}',  # valid JSON, missing required fields → ValidationError branch
        ],
    )
    def test_malformed_snapshot_is_stale_not_500(
        self, client: TestClient, db_session: Session, raw: str
    ) -> None:
        app.dependency_overrides[get_pool_health_redis] = lambda: _RawRedis(raw)
        _login_as_superuser(client, db_session, "pa-health-malformed@example.com")

        resp = client.get(_POOL_HEALTH_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stale"] is True
        assert body["accounts"] == []


class TestQRServiceSingleton:
    def test_get_qr_login_service_is_a_process_singleton(self) -> None:
        # start() and poll() must share ONE in-process registry (TASK-114), so the
        # dependency must return the same instance across calls.
        assert get_qr_login_service() is get_qr_login_service()
