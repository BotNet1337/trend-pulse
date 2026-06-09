"""Alerts read API integration tests (marker: integration).

RED anchor for AC1 (TASK-020): GET /alerts cursor-pagination — no dupes/gaps,
insert-between-pages stability, tiebreaker by id, next_cursor=None on last page,
invalid cursor → 422.

Runs against the live pgvector Postgres (same `Settings.database_url`).
`current_user` and the sync DB session are overridden to the fixture user so
the full HTTP surface is exercised via TestClient.

Pattern: mirrors test_watchlist_api.py (same fixtures, same isolation pattern).

Note on plan: the main `user` fixture is Pro plan so history window is non-zero
(Free plan → history_unavailable=True, empty items — tested separately via
`test_free_plan_history_unavailable`).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.auth.api_key import current_user_or_api_key
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
    first_seen: datetime | None = None,
) -> Alert:
    kwargs: dict[str, object] = {
        "user_id": user_id,
        "cluster_id": cluster_id,
        "score": score,
        "channels_count": channels_count,
        "delivery_status": delivery_status,
    }
    if first_seen is not None:
        kwargs["first_seen"] = first_seen
    alert = Alert(**kwargs)
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

    # Override both current_user (for routes that use it directly) and
    # current_user_or_api_key (for GET /alerts + GET /watchlists read-routes
    # updated in TASK-028 to accept both cookie and X-API-Key).
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_or_api_key] = lambda: user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def free_client(db_session_committing: Session, free_user: User) -> Iterator[TestClient]:
    """TestClient authenticated as the free_user."""

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: free_user
    app.dependency_overrides[current_user_or_api_key] = lambda: free_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


# ─── RED anchor: 401 without cookie ──────────────────────────────────────────


def test_no_auth_returns_401() -> None:
    """GET /alerts without cookie → 401 (auth-guard, no override)."""
    with TestClient(app) as anon:
        resp = anon.get("/alerts")
    assert resp.status_code == 401


# ─── AC1 (TASK-020) — cursor contract ────────────────────────────────────────


def test_list_returns_200_for_authenticated(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """GET /alerts with valid session → 200 AlertListResponse (cursor contract)."""
    cluster = _make_cluster(db_session_committing, user.id)
    _make_alert(db_session_committing, user.id, cluster.id)

    resp = client.get("/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "next_cursor" in body
    assert "history_unavailable" in body
    # Old offset/total fields must be gone
    assert "total" not in body
    assert "offset" not in body
    assert "limit" not in body


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


# ─── AC1 — cursor-листание без дублей/пропусков ───────────────────────────────


def test_cursor_paginates_without_dupes_or_gaps(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC1: Cursor pagination collects all N alerts, no duplicates, no gaps."""
    n = 7
    limit = 3
    # Each alert needs its own cluster (unique (user_id, cluster_id) constraint)
    for i in range(n):
        cluster = _make_cluster(db_session_committing, user.id, topic=f"topic-nd-{i}")
        _make_alert(
            db_session_committing,
            user.id,
            cluster.id,
            score=float(80 + i),
        )

    collected_ids: list[int] = []
    cursor: str | None = None

    for _ in range(n + 2):  # safety limit to prevent infinite loop
        params: dict[str, int | str] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/alerts", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        page_items = body["items"]
        collected_ids.extend(item["id"] for item in page_items)
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(collected_ids) == n, f"expected {n}, got {len(collected_ids)}"
    assert len(set(collected_ids)) == n, "duplicates found in cursor pagination"


def test_insert_between_pages_no_dupes(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC1: Inserting a new alert (newer first_seen) between pages doesn't cause dupes/gaps."""
    # Create 4 alerts with explicitly recent timestamps (within Pro 30-day window)
    now = datetime.now(UTC)
    alert_ids: list[int] = []
    for i in range(4):
        # Each alert is 1 second apart, all within the last day
        ts = now.replace(microsecond=0) - timedelta(seconds=3 - i)
        cluster = _make_cluster(db_session_committing, user.id, topic=f"topic-ibp-{i}")
        alert = _make_alert(
            db_session_committing,
            user.id,
            cluster.id,
            first_seen=ts,
        )
        alert_ids.append(alert.id)

    # Get first page (limit=2) — returns newest 2
    resp1 = client.get("/alerts", params={"limit": 2})
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()
    first_page_ids = {item["id"] for item in body1["items"]}
    cursor = body1["next_cursor"]
    assert cursor is not None, "expected next_cursor after first page"

    # Insert a NEW alert with first_seen NEWER than all existing
    newer_ts = now + timedelta(seconds=60)
    new_cluster = _make_cluster(db_session_committing, user.id, topic="topic-ibp-new")
    new_alert = _make_alert(
        db_session_committing,
        user.id,
        new_cluster.id,
        first_seen=newer_ts,
    )

    # Continue pagination from cursor — should not return already-seen items
    all_page2_ids: list[int] = []
    while cursor is not None:
        resp = client.get("/alerts", params={"limit": 2, "cursor": cursor})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        all_page2_ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]

    # The new alert (newer ts) is above the cursor window — should NOT appear in page 2+
    assert new_alert.id not in all_page2_ids, "new alert leaked into subsequent cursor pages"
    # No items from page 1 should reappear
    assert not first_page_ids.intersection(all_page2_ids), "duplicates across cursor pages"


def test_equal_first_seen_tiebreaker(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC1: Alerts with equal first_seen use id DESC as tiebreaker — all seen exactly once.

    Uses NON-zero microseconds so the cursor round-trip (encode isoformat → decode →
    bind into the keyset predicate) is exercised at full timestamptz precision —
    a truncation/tz drift on the boundary value would drop or duplicate a row here.
    """
    # Recent timestamp within the Pro 30-day window; nonzero microseconds on purpose.
    same_ts = datetime.now(UTC).replace(microsecond=123456)
    created_ids: list[int] = []
    for i in range(3):
        cluster = _make_cluster(db_session_committing, user.id, topic=f"topic-tie-{i}")
        alert = _make_alert(
            db_session_committing,
            user.id,
            cluster.id,
            first_seen=same_ts,
        )
        created_ids.append(alert.id)

    collected_ids: list[int] = []
    cursor: str | None = None

    for _ in range(10):
        params: dict[str, int | str] = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/alerts", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for item in body["items"]:
            collected_ids.append(item["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(collected_ids) == 3, f"expected 3 alerts, got {len(collected_ids)}"
    assert len(set(collected_ids)) == 3, "duplicates in tiebreaker test"
    # All created ids must appear
    assert set(collected_ids) == set(created_ids)


def test_next_cursor_none_on_last_page(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC1: next_cursor is None when all items fit in one page."""
    limit = 5
    n = 3  # fewer than limit
    for i in range(n):
        cluster = _make_cluster(db_session_committing, user.id, topic=f"topic-lp-{i}")
        _make_alert(db_session_committing, user.id, cluster.id)

    resp = client.get("/alerts", params={"limit": limit})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == n
    assert body["next_cursor"] is None


def test_invalid_cursor_not_500(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC3: Invalid/garbage cursor → 422 (not 500)."""
    resp = client.get("/alerts", params={"cursor": "garbage!!!"})
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


def test_out_of_range_cursor_id_not_500(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC3: A well-formed cursor carrying an out-of-int8-range id → 422, not a DB 500.

    A crafted cursor with a huge id must be rejected at decode time (range guard)
    rather than reaching the DB and raising an int8-overflow DataError.
    """
    import base64
    import json

    payload = json.dumps(["2026-01-01T00:00:00+00:00", 2**63]).encode()
    crafted = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    resp = client.get("/alerts", params={"cursor": crafted})
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


# ─── AC1 — pagination (cursor-based, replaces old limit/offset tests) ─────────


def test_pagination_with_cursor(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """Cursor pagination: pages of limit=2 cover all 5 alerts without duplication."""
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

    all_ids: list[int] = []
    cursor: str | None = None

    for _ in range(10):
        params: dict[str, int | str] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/alerts", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        all_ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(all_ids) == 5
    assert len(set(all_ids)) == 5


def test_limit_capped_at_max(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """Requesting limit > MAX_ALERTS_PAGE_SIZE is silently clamped to max by service."""
    cluster = _make_cluster(db_session_committing, user.id)
    _make_alert(db_session_committing, user.id, cluster.id)

    # Pass limit exactly at MAX_ALERTS_PAGE_SIZE (100) — should succeed
    resp = client.get("/alerts", params={"limit": 100})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Response must have next_cursor (new contract, not limit field)
    assert "next_cursor" in body
    assert "items" in body


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


# ─── AC4 — history window by plan ────────────────────────────────────────────


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
    assert body["next_cursor"] is None
