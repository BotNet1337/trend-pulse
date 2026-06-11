"""Integration tests for GET /feedback/{token} — AC2, AC3 (TASK-042).

AC2: GET /feedback/{token(up)} → 200 HTML, alert_feedback row written (verdict=up);
     second tap with down token → same row updated to verdict=down (UPSERT).
AC3: expired / tampered / garbage token → 4xx, DB untouched;
     endpoint enforces rate-limit (via limiter, tested structurally).
Edge: alert deleted by retention → 404/410.

Uses TestClient (ASGI) + live Postgres (db_session fixture, integration marker).
No external HTTP calls — the endpoint logic is fully in-process.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from alerts.feedback_tokens import sign_feedback_token
from config import get_settings
from storage.models import Alert, Cluster, User
from storage.models.alert_feedback import AlertFeedback

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# AC3 — rate-limit: over-limit returns 429 (unit-style, no live DB needed)
# ---------------------------------------------------------------------------


def test_feedback_rate_limit_returns_429() -> None:
    """Requests over the feedback rate-limit → 429.

    Uses an isolated FastAPI app with the same feedback route but a very small
    in-memory limiter (limit=1/minute) so the over-limit path fires immediately.
    Pattern mirrors tests/unit/test_rate_limit.py to avoid any live DB/Redis dep.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    from api.rate_limit import rate_limit_handler, rate_limit_key

    _SMALL_LIMIT = 1

    mini_app = FastAPI()
    test_limiter = Limiter(
        key_func=rate_limit_key,
        default_limits=[f"{_SMALL_LIMIT}/minute"],
        storage_uri="memory://",
    )
    mini_app.state.limiter = test_limiter
    mini_app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    mini_app.add_middleware(SlowAPIMiddleware)

    # Wire the feedback route with its per-route limiter overriding to the same
    # small limit.  We override the route decorator's limit function to match.
    from api.feedback import router as _feedback_module

    _orig_limit_fn = _feedback_module._feedback_rate_limit

    def _small_limit_fn() -> str:
        return f"{_SMALL_LIMIT}/minute"

    _feedback_module._feedback_rate_limit = _small_limit_fn  # type: ignore[assignment]

    try:
        from api.feedback.router import router as feedback_router

        mini_app.include_router(feedback_router)

        with TestClient(mini_app, raise_server_exceptions=False) as c:
            # First request: within limit
            r1 = c.get("/feedback/some-garbage-token", follow_redirects=False)
            # First request hits the route but will fail token validation (400) —
            # what matters is it is NOT 429.
            assert r1.status_code != 429, (
                f"First request should not be rate-limited, got {r1.status_code}"
            )

            # Second request: over the 1/minute limit → 429.
            r2 = c.get("/feedback/some-garbage-token", follow_redirects=False)
            assert r2.status_code == 429, (
                f"Expected 429 after exceeding limit, got {r2.status_code}"
            )
    finally:
        _feedback_module._feedback_rate_limit = _orig_limit_fn  # type: ignore[assignment]


_EMBEDDING_DIM = 384
_TTL = 604800  # 7 days
_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _seed_user_alert(session: Session) -> tuple[User, Alert]:
    """Seed a user + cluster + alert; return the alert."""
    user = User(email="feedback_test@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()

    cluster = Cluster(
        user_id=user.id,
        topic="test_feedback_topic",
        embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
        first_seen=_NOW,
        updated_at=_NOW,
    )
    session.add(cluster)
    session.flush()

    alert = Alert(
        user_id=user.id,
        cluster_id=cluster.id,
        score=80.0,
        channels_count=5,
        first_seen=_NOW,
    )
    session.add(alert)
    session.flush()
    return user, alert


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """TestClient with DB override via app dependency."""
    from api.feedback.router import get_db_session
    from api.main import app

    def override_get_db_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC2 — tapping writes verdict row; second tap updates it (UPSERT)
# ---------------------------------------------------------------------------


def test_feedback_up_creates_row(db_session: Session, client: TestClient) -> None:
    """GET /feedback/{token(up)} → 200 HTML, alert_feedback row inserted."""
    user, alert = _seed_user_alert(db_session)
    db_session.commit()

    jwt_secret = get_settings().jwt_secret
    token = sign_feedback_token(
        alert_id=alert.id, verdict="up", jwt_secret=jwt_secret, ttl_seconds=_TTL
    )

    response = client.get(f"/v1/feedback/{token}", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    # Verify row was written.
    row = db_session.execute(
        select(AlertFeedback).where(AlertFeedback.alert_id == alert.id)
    ).scalar_one_or_none()
    assert row is not None
    assert row.alert_id == alert.id
    assert row.user_id == user.id
    assert row.verdict == 1  # up = 1


def test_feedback_upsert_changes_verdict(db_session: Session, client: TestClient) -> None:
    """Second tap with different verdict updates the existing row (last-write-wins)."""
    _user, alert = _seed_user_alert(db_session)
    db_session.commit()

    jwt_secret = get_settings().jwt_secret

    # First tap: up
    token_up = sign_feedback_token(
        alert_id=alert.id, verdict="up", jwt_secret=jwt_secret, ttl_seconds=_TTL
    )
    r1 = client.get(f"/v1/feedback/{token_up}", follow_redirects=False)
    assert r1.status_code == 200

    # Second tap: down — should update, not duplicate
    token_down = sign_feedback_token(
        alert_id=alert.id, verdict="down", jwt_secret=jwt_secret, ttl_seconds=_TTL
    )
    r2 = client.get(f"/v1/feedback/{token_down}", follow_redirects=False)
    assert r2.status_code == 200

    # Only one row should exist.
    rows = (
        db_session.execute(select(AlertFeedback).where(AlertFeedback.alert_id == alert.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verdict == 0  # down = 0


# ---------------------------------------------------------------------------
# AC3 — invalid / expired / tampered tokens → 4xx, DB untouched
# ---------------------------------------------------------------------------


def test_garbage_token_returns_4xx(db_session: Session, client: TestClient) -> None:
    """A random garbage token returns 4xx without touching the DB."""
    response = client.get("/v1/feedback/not-a-valid-token-at-all", follow_redirects=False)
    assert response.status_code in (400, 401, 422)
    # DB must be empty.
    rows = db_session.execute(select(AlertFeedback)).scalars().all()
    assert len(rows) == 0


def test_expired_token_returns_4xx(db_session: Session, client: TestClient) -> None:
    """An expired token returns 4xx without touching the DB."""
    _user, alert = _seed_user_alert(db_session)
    db_session.commit()

    jwt_secret = get_settings().jwt_secret
    token = sign_feedback_token(
        alert_id=alert.id, verdict="up", jwt_secret=jwt_secret, ttl_seconds=-1
    )

    response = client.get(f"/v1/feedback/{token}", follow_redirects=False)
    assert response.status_code in (400, 401, 410)

    rows = db_session.execute(select(AlertFeedback)).scalars().all()
    assert len(rows) == 0


def test_tampered_token_returns_4xx(db_session: Session, client: TestClient) -> None:
    """A tampered token returns 4xx without touching the DB."""
    import base64
    import json

    _user, alert = _seed_user_alert(db_session)
    db_session.commit()

    jwt_secret = get_settings().jwt_secret
    token = sign_feedback_token(
        alert_id=alert.id, verdict="up", jwt_secret=jwt_secret, ttl_seconds=_TTL
    )

    # Tamper the payload
    parts = token.split(".")
    payload_bytes = base64.urlsafe_b64decode(parts[0] + "==")
    data = json.loads(payload_bytes)
    data["a"] = 99999  # wrong alert_id
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    tampered_token = f"{tampered_payload}.{parts[1]}"

    response = client.get(f"/v1/feedback/{tampered_token}", follow_redirects=False)
    assert response.status_code in (400, 401, 422)

    rows = db_session.execute(select(AlertFeedback)).scalars().all()
    assert len(rows) == 0


def test_alert_deleted_returns_404_or_410(db_session: Session, client: TestClient) -> None:
    """Token for a deleted/nonexistent alert returns 404/410."""
    jwt_secret = get_settings().jwt_secret
    # Use an alert_id that doesn't exist
    token = sign_feedback_token(
        alert_id=999999, verdict="up", jwt_secret=jwt_secret, ttl_seconds=_TTL
    )

    response = client.get(f"/v1/feedback/{token}", follow_redirects=False)
    assert response.status_code in (404, 410)


# ---------------------------------------------------------------------------
# AC4 — precision metric: total = all user alerts in window (not just rated)
# ---------------------------------------------------------------------------


def _seed_alerts_for_precision(session: Session, n: int) -> tuple[User, list[Alert]]:
    """Seed one user with n alerts (all delivered_at=_NOW) for precision tests."""
    user = User(email=f"precision_test_{n}@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()

    alerts: list[Alert] = []
    for i in range(n):
        cluster = Cluster(
            user_id=user.id,
            topic=f"precision_topic_{i}",
            embedding=[0.1 + i * 0.001] + [0.0] * (_EMBEDDING_DIM - 1),
            first_seen=_NOW,
            updated_at=_NOW,
        )
        session.add(cluster)
        session.flush()

        from storage.models.alerts import DELIVERY_STATUS_DELIVERED

        alert = Alert(
            user_id=user.id,
            cluster_id=cluster.id,
            score=80.0 + i,
            channels_count=1,
            first_seen=_NOW,
            delivered_at=_NOW,
            delivery_status=DELIVERY_STATUS_DELIVERED,
        )
        session.add(alert)
        session.flush()
        alerts.append(alert)

    return user, alerts


def test_precision_total_counts_all_alerts_not_just_rated(
    db_session: Session,
) -> None:
    """5 alerts for a user, feedback on 4 (3 up / 1 down) → precision=0.75,
    rated=4, total=5.

    This is the regression guard for the HIGH bug: if total is computed from
    alert_feedback COUNT(*) then total==rated==4 (WRONG). The correct total=5
    comes from counting alerts rows for the user in the window.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from observability.signal_latency import emit_alert_precision
    from storage.models.alert_feedback import VERDICT_DOWN, VERDICT_UP, AlertFeedback
    from storage.models.base import utcnow

    user, alerts = _seed_alerts_for_precision(db_session, 5)
    db_session.flush()

    # Provide feedback on 4 out of 5 alerts: 3 up, 1 down.
    feedback_verdicts = [VERDICT_UP, VERDICT_UP, VERDICT_UP, VERDICT_DOWN]
    for alert, verdict in zip(alerts[:4], feedback_verdicts, strict=True):
        now = utcnow()
        stmt = (
            pg_insert(AlertFeedback)
            .values(
                user_id=user.id,
                alert_id=alert.id,
                verdict=verdict,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_alert_feedback_alert_id",
                set_={"verdict": verdict, "updated_at": now},
            )
        )
        db_session.execute(stmt)

    db_session.commit()

    from unittest.mock import MagicMock, patch

    settings = MagicMock()
    settings.precision_window_seconds = 604800  # 7-day window — _NOW is within it

    with patch("observability.signal_latency.log_event"):
        results = emit_alert_precision(db_session, settings)

    # Exactly one user in the result.
    user_results = [r for r in results if r["user_id"] == user.id]
    assert len(user_results) == 1, f"Expected 1 result for user, got {user_results}"

    entry = user_results[0]
    assert entry["rated"] == 4, f"rated should be 4 (up+down), got {entry['rated']}"
    assert entry["precision"] == pytest.approx(0.75), (
        f"precision should be 0.75 (3/4), got {entry['precision']}"
    )
    # KEY ASSERTION: total must be 5 (all alerts), not 4 (only rated)
    assert entry["total"] == 5, (
        f"total should be 5 (all delivered alerts), got {entry['total']} — "
        "regression: total==rated means total is counting alert_feedback rows, "
        "not alerts rows"
    )
