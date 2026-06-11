"""Trending API integration tests (marker: integration) — TASK-039.

RED anchors for AC1-AC5:
- AC1: GET /trending?pack=crypto-ru → top-K sorted by viral_score desc, aggregates only.
- AC2: window (older than 24h excluded); limit > MAX → 422; unknown pack → 404.
- AC3: ensure_showcase_tenant() idempotent — second call no new user, no duplicate subs.
- AC4: isolation — regular user's watchlists/alerts don't expose showcase rows;
       /trending returns only showcase data even when caller has own clusters.
- AC5: response schema has no raw-content fields (topic + metrics only).
- warming_up=true when showcase tenant missing or has no clusters.

Pattern: mirrors test_packs_api.py / test_alerts_api.py.
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
from storage.models.clusters import Cluster
from storage.models.scores import Score
from storage.models.users import PLAN_FREE, User

pytestmark = pytest.mark.integration

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(session: Session, email: str, plan: str = PLAN_FREE) -> User:
    user = User(email=email, hashed_password="x" * 16, plan=plan)
    session.add(user)
    session.flush()
    return user


def _make_cluster(
    session: Session,
    user_id: int,
    topic: str,
    first_seen: datetime | None = None,
    updated_at: datetime | None = None,
) -> Cluster:
    """Create a Cluster row for the given user with a zero embedding (valid for read tests)."""
    now = datetime.now(UTC)
    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        embedding=[0.0] * 384,
        first_seen=first_seen or now,
        updated_at=updated_at or now,
    )
    session.add(cluster)
    session.flush()
    return cluster


def _make_score(
    session: Session,
    user_id: int,
    cluster_id: int,
    viral_score: float,
    channels_count: int = 3,
) -> Score:
    """Create a Score row for (user, cluster) with given viral_score."""
    score = Score(
        user_id=user_id,
        cluster_id=cluster_id,
        velocity=0.5,
        engagement=0.5,
        cross_channel=0.5,
        viral_score=viral_score,
        channels_count=channels_count,
    )
    session.add(score)
    session.flush()
    return score


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """Session whose flushes are immediately visible to the app (shared conn)."""
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
def regular_user(db_session_committing: Session) -> User:
    return _make_user(db_session_committing, "regular@trending.example.com", plan=PLAN_FREE)


@pytest.fixture
def regular_client(db_session_committing: Session, regular_user: User) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: regular_user
    app.dependency_overrides[current_user_or_api_key] = lambda: regular_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


# ─── AC1 — trending returns top showcase clusters sorted by viral_score ───────


def test_trending_no_auth_returns_401(db_session_committing: Session) -> None:
    """GET /trending without auth → 401."""
    with TestClient(app) as anon:
        resp = anon.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 401, resp.text


def test_trending_returns_top_k_sorted_desc(
    regular_client: TestClient,
    db_session_committing: Session,
    regular_user: User,
) -> None:
    """AC1 (RED anchor): GET /trending?pack=crypto-ru returns clusters sorted by viral_score desc.

    Seeds a showcase user with clusters/scores for the 'crypto' topic (matching crypto-ru pack),
    verifies top-K order and aggregate-only fields.
    """
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)

    now = datetime.now(UTC)

    # Seed 3 clusters with different viral scores
    c1 = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, c1.id, viral_score=90.0, channels_count=5)

    c2 = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, c2.id, viral_score=75.0, channels_count=3)

    c3 = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, c3.id, viral_score=55.0, channels_count=2)

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "items" in body
    assert "warming_up" in body
    assert body["warming_up"] is False

    items = body["items"]
    assert len(items) == 3

    # Sorted descending by viral_score
    scores = [item["viral_score"] for item in items]
    assert scores == sorted(scores, reverse=True), f"Expected desc order, got {scores}"
    assert scores[0] == pytest.approx(90.0)
    assert scores[1] == pytest.approx(75.0)
    assert scores[2] == pytest.approx(55.0)

    # TASK-066 AC2: channels_count comes from the persisted Score row (not a fake 1).
    counts = [item["channels_count"] for item in items]
    assert counts == [5, 3, 2], f"Expected real per-cluster channel counts, got {counts}"


# ─── AC5 — no raw content fields ──────────────────────────────────────────────


def test_trending_response_contains_aggregate_fields_only(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC5: Response items have only aggregate fields; no text/raw-content."""
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)
    now = datetime.now(UTC)
    c = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, c.id, viral_score=80.0)

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    assert len(items) >= 1

    for item in items:
        # Required aggregate fields present
        assert "topic" in item
        assert "viral_score" in item
        assert "channels_count" in item
        assert "first_seen" in item
        # Raw content must NOT be present (compliance §7)
        assert "text" not in item
        assert "content" not in item
        assert "post_text" not in item
        assert "raw" not in item
        assert "message" not in item


# ─── AC2 — window filtering (older than 24h excluded) ─────────────────────────


def test_trending_excludes_clusters_older_than_24h(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC2: clusters with first_seen older than 24h window are excluded."""
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)
    now = datetime.now(UTC)

    # Fresh cluster — within 24h window
    fresh_ts = now - timedelta(hours=1)
    c_fresh = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=fresh_ts)
    _make_score(db_session_committing, showcase_user, c_fresh.id, viral_score=99.0)

    # Stale cluster — older than 24h window
    stale_ts = now - timedelta(hours=25)
    c_stale = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=stale_ts)
    _make_score(db_session_committing, showcase_user, c_stale.id, viral_score=88.0)

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    # We don't expose cluster_id in response; verify by viral_score uniqueness
    viral_scores = [item["viral_score"] for item in items]
    assert 99.0 in [pytest.approx(s) for s in viral_scores], "fresh cluster must appear"
    assert not any(abs(s - 88.0) < 0.01 for s in viral_scores), (
        "stale cluster (>24h) must NOT appear"
    )


def test_trending_limit_over_max_returns_422(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC2: limit > MAX_TRENDING_LIMIT → 422."""
    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru", "limit": 999})
    assert resp.status_code == 422, resp.text


def test_trending_unknown_pack_returns_404(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC2: unknown pack slug → 404."""
    resp = regular_client.get("/v1/trending", params={"pack": "totally-unknown-pack-xyz"})
    assert resp.status_code == 404, resp.text


# ─── AC3 — idempotent bootstrap ───────────────────────────────────────────────


def test_ensure_showcase_tenant_idempotent(
    db_session_committing: Session,
) -> None:
    """AC3: calling ensure_showcase_tenant() twice → same user id, no duplicate subs."""
    from sqlalchemy import func, select

    from api.trending.bootstrap import ensure_showcase_tenant
    from config import get_settings
    from storage.models.users import User
    from storage.models.watchlists import Watchlist

    uid1 = ensure_showcase_tenant(db_session_committing)
    uid2 = ensure_showcase_tenant(db_session_committing)

    assert uid1 == uid2, f"Expected same user id on repeated call; got {uid1} vs {uid2}"

    # Only one user row with the showcase email must exist
    showcase_email = get_settings().showcase_user_email
    count = db_session_committing.scalar(
        select(func.count(User.id)).where(User.email == showcase_email)
    )
    assert count == 1, f"Expected exactly 1 showcase user, got {count}"

    # No duplicate watchlist rows (same user_id, channel_id, topic constraint)
    wl_count = db_session_committing.scalar(
        select(func.count(Watchlist.id)).where(Watchlist.user_id == uid1)
    )
    # All rows exist once — no duplicates
    # We can verify by checking the unique count equals total count
    distinct_wl = db_session_committing.scalar(
        select(func.count()).select_from(
            select(Watchlist.channel_id, Watchlist.topic)
            .where(Watchlist.user_id == uid1)
            .distinct()
            .subquery()
        )
    )
    assert wl_count == distinct_wl, "Duplicate watchlist rows detected after double bootstrap"


# ─── AC4 — isolation ──────────────────────────────────────────────────────────


def test_regular_user_watchlists_do_not_expose_showcase_data(
    regular_client: TestClient,
    db_session_committing: Session,
    regular_user: User,
) -> None:
    """AC4: regular user's GET /watchlists does not see showcase user's watchlist rows."""
    from api.trending.bootstrap import ensure_showcase_tenant

    # Bootstrap showcase (it gets watchlist rows from pack subscriptions)
    ensure_showcase_tenant(db_session_committing)

    resp = regular_client.get("/v1/watchlists")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    # All returned rows must belong to the regular_user
    for row in rows:
        assert row["user_id"] == regular_user.id, (
            f"Watchlist row belongs to user {row['user_id']}, not regular_user {regular_user.id}"
        )


def test_trending_returns_only_showcase_data_not_caller_clusters(
    regular_client: TestClient,
    db_session_committing: Session,
    regular_user: User,
) -> None:
    """AC4: /trending returns only showcase clusters; caller's own clusters are NOT included."""
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)
    now = datetime.now(UTC)

    # Seed showcase cluster with known viral_score
    sc = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, sc.id, viral_score=80.0)

    # Seed regular user's own cluster with a DIFFERENT viral_score
    uc = _make_cluster(db_session_committing, regular_user.id, "crypto", first_seen=now)
    _make_score(db_session_committing, regular_user.id, uc.id, viral_score=99.0)

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text

    viral_scores = [item["viral_score"] for item in resp.json()["items"]]
    # regular_user's cluster (99.0) must NOT appear
    assert not any(abs(s - 99.0) < 0.01 for s in viral_scores), (
        "Caller's own cluster must NOT appear in /trending (only showcase)"
    )
    # showcase cluster (80.0) must appear
    assert any(abs(s - 80.0) < 0.01 for s in viral_scores), (
        "Showcase cluster must appear in /trending"
    )


def test_regular_user_alerts_do_not_expose_showcase_clusters(
    regular_client: TestClient,
    db_session_committing: Session,
    regular_user: User,
) -> None:
    """AC4: GET /alerts only returns the caller's alerts (showcase isolation via existing scope)."""
    from api.trending.bootstrap import ensure_showcase_tenant
    from storage.models.alerts import Alert

    showcase_user = ensure_showcase_tenant(db_session_committing)

    # Seed a cluster + alert for showcase user
    now = datetime.now(UTC)
    sc = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    showcase_alert = Alert(
        user_id=showcase_user,
        cluster_id=sc.id,
        score=99.0,
        channels_count=5,
        delivery_status="delivered",
    )
    db_session_committing.add(showcase_alert)
    db_session_committing.flush()

    # regular user's GET /alerts must NOT include showcase user's alert
    resp = regular_client.get("/v1/alerts")
    assert resp.status_code == 200, resp.text
    alert_ids = [a["id"] for a in resp.json()["items"]]
    assert showcase_alert.id not in alert_ids, (
        "Showcase user's alert must not appear in regular user's /alerts"
    )


# ─── warming_up semantics ─────────────────────────────────────────────────────


def test_trending_warming_up_when_no_showcase_tenant(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """Edge case: no showcase tenant in DB → warming_up=true, empty items, 200."""
    # Do NOT call ensure_showcase_tenant — showcase does not exist
    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warming_up"] is True
    assert body["items"] == []


def test_trending_warming_up_when_showcase_has_no_clusters(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """Edge case: showcase tenant exists but has no clusters → warming_up=true."""
    from api.trending.bootstrap import ensure_showcase_tenant

    ensure_showcase_tenant(db_session_committing)
    # No clusters seeded for showcase

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warming_up"] is True
    assert body["items"] == []


def test_trending_pack_with_no_24h_activity_returns_empty_not_warming_up(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """Edge case: showcase warmed but pack topic has no 24h data → empty, warming_up=false."""
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)

    # Seed a fresh cluster for a DIFFERENT pack's topic (tech), not crypto
    now = datetime.now(UTC)
    c = _make_cluster(db_session_committing, showcase_user, "tech", first_seen=now)
    _make_score(db_session_committing, showcase_user, c.id, viral_score=70.0)

    # crypto-ru pack has topic='crypto' → no clusters → empty list, but showcase IS warmed
    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Showcase has clusters (tech topic), so it IS warmed → warming_up=false
    assert body["warming_up"] is False
    assert body["items"] == []


# ─── limit parameter ──────────────────────────────────────────────────────────


def test_trending_limit_default_and_custom(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC2: custom limit ≤ MAX is respected; default limit applies when omitted."""
    from api.trending.bootstrap import ensure_showcase_tenant

    showcase_user = ensure_showcase_tenant(db_session_committing)
    now = datetime.now(UTC)

    # Seed 15 clusters
    for i in range(15):
        c = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
        _make_score(db_session_committing, showcase_user, c.id, viral_score=float(50 + i))

    # Default limit (10)
    resp_default = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp_default.status_code == 200
    assert len(resp_default.json()["items"]) == 10

    # Custom limit=5
    resp_limited = regular_client.get("/v1/trending", params={"pack": "crypto-ru", "limit": 5})
    assert resp_limited.status_code == 200
    assert len(resp_limited.json()["items"]) == 5

    # limit=20 (MAX allowed)
    resp_max = regular_client.get("/v1/trending", params={"pack": "crypto-ru", "limit": 20})
    assert resp_max.status_code == 200
    assert len(resp_max.json()["items"]) == 15  # only 15 seeded


# ─── Fix-cycle: AC5 — topic sanitization (compliance §7) ─────────────────────


def test_trending_topic_label_sanitized_no_url_no_handle(
    regular_client: TestClient,
    db_session_committing: Session,
) -> None:
    """Fix 2 (AC5): _sanitize_topic_label is invoked at the API boundary.

    The service filters clusters by pack.topic (exact match), so clusters must
    have topic == pack.topic to appear in the response. We verify that:
    1. The sanitized label IS returned for a clean topic (no false positives).
    2. A cluster whose topic exactly equals the pack keyword passes through cleanly.
    3. The unit tests in test_trending_entrypoint.py verify full URL/@handle stripping.

    Note: In production the pipeline sets cluster.topic = post.text[:255]; the
    pack-topic equality filter (`WHERE cluster.topic == pack.topic`) means only
    clusters explicitly created with topic = pack.topic (e.g. "crypto") match.
    The sanitization is defense-in-depth for future filter changes (e.g. ILIKE/vector
    proximity) — verified comprehensively in unit tests.
    """
    from api.trending.bootstrap import ensure_showcase_tenant
    from api.trending.service import TRENDING_LABEL_MAX_LEN

    showcase_user = ensure_showcase_tenant(db_session_committing)
    now = datetime.now(UTC)

    # Seed cluster with pack.topic = "crypto" so it passes the filter.
    c = _make_cluster(db_session_committing, showcase_user, "crypto", first_seen=now)
    _make_score(db_session_committing, showcase_user, c.id, viral_score=95.0)

    resp = regular_client.get("/v1/trending", params={"pack": "crypto-ru"})
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    assert len(items) >= 1, "Expected at least one item from seeded cluster"

    for item in items:
        label = item["topic"]
        # Sanitization contract: no URLs, handles, or emails in returned labels.
        assert "https://" not in label, f"URL in topic label: {label!r}"
        assert "t.me/" not in label, f"t.me link in topic label: {label!r}"
        assert "@" not in label or all(not part.startswith("@") for part in label.split()), (
            f"@-handle in topic label: {label!r}"
        )
        assert len(label) <= TRENDING_LABEL_MAX_LEN, (
            f"Label length {len(label)} > TRENDING_LABEL_MAX_LEN={TRENDING_LABEL_MAX_LEN}"
        )


# ─── Fix-cycle: AC4 — showcase login → 400/401 not 500 ───────────────────────


def test_showcase_login_returns_4xx_not_500(
    db_session_committing: Session,
) -> None:
    """Fix 3 (AC4): POST /auth/jwt/login as showcase@internal → 400 or 401, NOT 500.

    Previously bootstrap stored a raw sha256 hex as hashed_password, causing
    fastapi-users authenticate() to raise UnknownHashError → unhandled 500.
    After fix: PasswordHelper().hash() stores a valid argon2 hash, so the verify
    step runs correctly and returns 400 (bad credentials), not 500.
    """
    from api.main import app
    from api.trending.bootstrap import ensure_showcase_tenant
    from config import get_settings

    # Bootstrap the showcase user (argon2 hash stored now)
    ensure_showcase_tenant(db_session_committing)
    db_session_committing.commit()

    showcase_email = get_settings().showcase_user_email

    # Use a real TestClient (no auth overrides) to exercise the full login path
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/v1/auth/jwt/login",
            data={"username": showcase_email, "password": "wrong-password-intentional"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert resp.status_code in (400, 401), (
        f"Expected 400 or 401 (bad credentials), got {resp.status_code}: {resp.text}"
    )
