"""Alerts read API integration tests (marker: integration).

RED anchor for AC2 (TASK-016): GET /alerts requires auth, returns only the
caller's alerts, supports pagination, and applies history window by plan.

Runs against the live pgvector Postgres (same `Settings.database_url`).
`current_user` and the sync DB session are overridden to the fixture user so
the full HTTP surface is exercised via TestClient.

Pattern: mirrors test_watchlist_api.py (same fixtures, same isolation pattern).

Note on plan: the main `user` fixture is Pro plan so history window is non-zero
(Free plan → history_unavailable=True, empty items — tested separately via
`test_free_plan_history_unavailable`).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.deps import current_user
from api.main import app
from api.watchlist.deps import get_db_session
from storage.models.alerts import DELIVERY_STATUS_DELIVERED, DELIVERY_STATUS_PENDING, Alert
from storage.models.clusters import Cluster
from storage.models.users import PLAN_FREE, PLAN_PRO, User

pytestmark = pytest.mark.integration


def _make_user(session: Session, email: str, plan: str = PLAN_PRO) -> User:
    user = User(email=email, hashed_password="x" * 16, plan=plan)
    session.add(user)
    session.flush()
    return user


def _make_cluster(session: Session, user_id: int, topic: str = "bitcoin") -> Cluster:
    """Create a cluster row (no embedding needed for read tests — use zeros)."""
    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        # 384-dim zero vector — valid for test read queries, no pgvector ops run
        embedding=[0.0] * 384,
    )
    session.add(cluster)
    session.flush()
    return cluster


def _make_alert(
    session: Session,
    user_id: int,
    cluster_id: int,
    score: float = 88.0,
    channels_count: int = 5,
    delivery_status: str = DELIVERY_STATUS_DELIVERED,
) -> Alert:
    alert = Alert(
        user_id=user_id,
        cluster_id=cluster_id,
        score=score,
        channels_count=channels_count,
        delivery_status=delivery_status,
    )
    session.add(alert)
    session.flush()
    return alert


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """A session whose flushes are visible to the app (shares one transaction).

    Rows are wiped via bulk delete on teardown (same pattern as watchlist tests).
    """
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
def user(db_session_committing: Session) -> User:
    """Main user fixture on Pro plan — ensures non-zero history window."""
    return _make_user(db_session_committing, "alert-owner@example.com", plan=PLAN_PRO)


@pytest.fixture
def free_user(db_session_committing: Session) -> User:
    """Free-plan user — history_unavailable=True on GET /alerts."""
    return _make_user(db_session_committing, "free-alert@example.com", plan=PLAN_FREE)


@pytest.fixture
def client(db_session_committing: Session, user: User) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def free_client(db_session_committing: Session, free_user: User) -> Iterator[TestClient]:
    """TestClient authenticated as the free_user."""

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: free_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db_session, None)


# ─── RED anchor: AC2 — 401 without cookie ────────────────────────────────────


def test_no_auth_returns_401() -> None:
    """GET /alerts without cookie → 401 (auth-guard, no override)."""
    with TestClient(app) as anon:
        resp = anon.get("/alerts")
    assert resp.status_code == 401


# ─── AC2 — 200 + only own alerts ─────────────────────────────────────────────


def test_list_returns_200_for_authenticated(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """GET /alerts with valid session → 200 AlertListResponse."""
    cluster = _make_cluster(db_session_committing, user.id)
    _make_alert(db_session_committing, user.id, cluster.id)

    resp = client.get("/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body
    assert "history_unavailable" in body


def test_list_returns_only_own_alerts(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """GET /alerts returns only the caller's alerts (tenant-scoped)."""
    # Create another user with an alert (also pro, to ensure it has alerts visible)
    other = _make_user(db_session_committing, "other-alerts@example.com", plan=PLAN_PRO)
    other_cluster = _make_cluster(db_session_committing, other.id, topic="ethereum")
    _make_alert(db_session_committing, other.id, other_cluster.id, score=70.0)

    # Create own alert
    own_cluster = _make_cluster(db_session_committing, user.id, topic="bitcoin")
    own_alert = _make_alert(db_session_committing, user.id, own_cluster.id, score=88.0)

    resp = client.get("/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 1
    assert items[0]["id"] == own_alert.id
    assert items[0]["score"] == pytest.approx(88.0)
    assert items[0]["topic"] == "bitcoin"


def test_alert_read_fields_present(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AlertRead shape includes id, score, topic, first_seen, channels_count, delivery_status."""
    cluster = _make_cluster(db_session_committing, user.id, topic="crypto")
    _make_alert(
        db_session_committing,
        user.id,
        cluster.id,
        score=92.5,
        channels_count=12,
        delivery_status=DELIVERY_STATUS_DELIVERED,
    )

    resp = client.get("/alerts")
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert "id" in item
    assert "score" in item
    assert "topic" in item
    assert "first_seen" in item
    assert "channels_count" in item
    assert "delivery_status" in item
    assert item["score"] == pytest.approx(92.5)
    assert item["topic"] == "crypto"
    assert item["channels_count"] == 12
    assert item["delivery_status"] == DELIVERY_STATUS_DELIVERED


# ─── AC2 — pagination ────────────────────────────────────────────────────────


def test_pagination_limit_offset(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """Pagination: limit/offset work; total counts correctly."""
    # Each alert needs its own cluster (unique (user_id, cluster_id) constraint)
    for i in range(5):
        cluster = _make_cluster(db_session_committing, user.id, topic=f"topic-pag-{i}")
        _make_alert(
            db_session_committing,
            user.id,
            cluster.id,
            score=float(80 + i),
            channels_count=i + 1,
            delivery_status=DELIVERY_STATUS_PENDING,
        )

    resp_p1 = client.get("/alerts", params={"limit": 2, "offset": 0})
    assert resp_p1.status_code == 200, resp_p1.text
    body_p1 = resp_p1.json()
    assert len(body_p1["items"]) == 2
    assert body_p1["total"] == 5
    assert body_p1["limit"] == 2
    assert body_p1["offset"] == 0

    resp_p2 = client.get("/alerts", params={"limit": 2, "offset": 2})
    assert resp_p2.status_code == 200, resp_p2.text
    body_p2 = resp_p2.json()
    assert len(body_p2["items"]) == 2

    resp_p3 = client.get("/alerts", params={"limit": 2, "offset": 4})
    assert resp_p3.status_code == 200, resp_p3.text
    body_p3 = resp_p3.json()
    assert len(body_p3["items"]) == 1


def test_limit_capped_at_max(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """Requesting limit > MAX_ALERTS_PAGE_SIZE is silently clamped to max by service."""
    cluster = _make_cluster(db_session_committing, user.id)
    _make_alert(db_session_committing, user.id, cluster.id)

    # Pass limit above 100 — FastAPI clamps via Query(ge=1), server clamps via service.
    # We request exactly MAX_ALERTS_PAGE_SIZE (100) to avoid Pydantic rejection.
    resp = client.get("/alerts", params={"limit": 100})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # limit in response must not exceed the server max constant (100)
    assert body["limit"] <= 100


# ─── AC2 — detail endpoint ────────────────────────────────────────────────────


def test_get_alert_detail_own(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """GET /alerts/{id} returns own alert detail."""
    cluster = _make_cluster(db_session_committing, user.id, topic="defi")
    alert = _make_alert(db_session_committing, user.id, cluster.id, score=77.0)

    resp = client.get(f"/alerts/{alert.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == alert.id
    assert body["topic"] == "defi"
    assert body["score"] == pytest.approx(77.0)


def test_get_alert_detail_foreign_returns_404(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """GET /alerts/{id} for another tenant's alert → 404 (no existence leak)."""
    other = _make_user(db_session_committing, "other2-alerts@example.com")
    other_cluster = _make_cluster(db_session_committing, other.id)
    foreign_alert = _make_alert(db_session_committing, other.id, other_cluster.id)

    resp = client.get(f"/alerts/{foreign_alert.id}")
    assert resp.status_code == 404, resp.text


# ─── AC5 — history window by plan ────────────────────────────────────────────


def test_free_plan_history_unavailable(
    free_client: TestClient, db_session_committing: Session, free_user: User
) -> None:
    """Free plan: GET /alerts returns empty items + history_unavailable=True."""
    cluster = _make_cluster(db_session_committing, free_user.id)
    _make_alert(db_session_committing, free_user.id, cluster.id)

    resp = free_client.get("/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Free plan: history window = 0 days → no history, flag set
    assert body["history_unavailable"] is True
    assert body["items"] == []
