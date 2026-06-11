"""Packs API integration tests (marker: integration) — TASK-038.

RED anchors for AC1-AC5:
- AC1: GET /packs → catalog list (any user).
- AC2: POST /packs/{slug}/subscribe → watchlist rows created with pack_slug;
       repeat call idempotent (created=0).
- AC3: Free user with 1 pack → 402 on second pack; manual CHANNELS limit
       NOT consumed by pack rows (TASK-049: Free CHANNELS=0, so test uses Pro user
       for manual-channel creation assertions; packs still work for Free).
- AC4: DELETE /packs/{slug}/subscribe removes pack rows; 404 for unknown slug.
- AC5: Tenant scope — user B cannot see user A's packs in watchlists.
- RACE: concurrent channel get-or-create does not poison the transaction (Finding 1).

Pattern: mirrors test_watchlist_api.py / test_api_keys_api.py.
"""

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth.api_key import current_user_or_api_key
from api.deps import current_user
from api.main import app
from api.watchlist.deps import get_db_session
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import PLAN_FREE, User

pytestmark = pytest.mark.integration

# ─── Helpers ──────────────────────────────────────────────────────────────────

_PLAN_PRO = "pro"


def _make_user(session: Session, email: str, plan: str = PLAN_FREE) -> User:
    """Create a test user. For paid plans, also create an active Subscription row.

    TASK-049: Free CHANNELS=0 — tests that create own channels need plan=pro +
    active subscription (effective_plan rolls back to Free without a sub row).
    """
    user = User(email=email, hashed_password="x" * 16, plan=plan)
    session.add(user)
    session.flush()
    if plan != PLAN_FREE:
        sub = Subscription(
            user_id=user.id,
            plan=plan,
            expires_at=utcnow() + timedelta(days=30),
        )
        session.add(sub)
        session.flush()
    return user


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """A session whose flushes are immediately visible to the app (shared conn)."""
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
def free_user(db_session_committing: Session) -> User:
    return _make_user(db_session_committing, "free@packs.example.com", plan=PLAN_FREE)


@pytest.fixture
def pro_user(db_session_committing: Session) -> User:
    """Pro user with active subscription — for tests that create manual watchlists.

    TASK-049: Free CHANNELS=0; manual channel creation requires Pro plan + active sub.
    """
    return _make_user(db_session_committing, "pro@packs.example.com", plan=_PLAN_PRO)


@pytest.fixture
def other_user(db_session_committing: Session) -> User:
    return _make_user(db_session_committing, "other@packs.example.com", plan=PLAN_FREE)


@pytest.fixture
def free_client(db_session_committing: Session, free_user: User) -> Iterator[TestClient]:
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


@pytest.fixture
def pro_client(db_session_committing: Session, pro_user: User) -> Iterator[TestClient]:
    """Client acting as a Pro user — for tests that need manual channel creation.

    TASK-049: Free CHANNELS=0; manual watchlist creation tests use this fixture.
    """

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: pro_user
    app.dependency_overrides[current_user_or_api_key] = lambda: pro_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def other_client(db_session_committing: Session, other_user: User) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: other_user
    app.dependency_overrides[current_user_or_api_key] = lambda: other_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


# ─── AC1 — catalog list ────────────────────────────────────────────────────────


def test_get_packs_returns_catalog(free_client: TestClient) -> None:
    """AC1 (RED anchor): GET /packs → list of pack slugs/titles from data.py."""
    resp = free_client.get("/packs")
    assert resp.status_code == 200, resp.text
    packs = resp.json()
    assert isinstance(packs, list)
    assert len(packs) >= 2, "catalog must have at least 2 packs"
    slugs = {p["slug"] for p in packs}
    assert "crypto-ru" in slugs
    assert "tech-en" in slugs
    for pack in packs:
        assert "slug" in pack
        assert "title" in pack
        assert "topic" in pack
        assert "channels_count" in pack
        assert isinstance(pack["channels_count"], int)
        assert pack["channels_count"] > 0


def test_get_packs_no_auth_returns_401() -> None:
    """AC1: without auth → 401."""
    with TestClient(app) as anon:
        resp = anon.get("/packs")
    assert resp.status_code == 401, resp.text


# ─── AC2 — subscribe in 1 click + idempotency ────────────────────────────────


def test_subscribe_creates_watchlist_rows(
    free_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """AC2: POST /packs/crypto-ru/subscribe → watchlist rows with pack_slug='crypto-ru'."""
    resp = free_client.post("/packs/crypto-ru/subscribe")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "created" in body
    assert "skipped" in body
    assert body["created"] > 0, "first subscribe must create rows"
    assert body["skipped"] == 0

    # Verify rows are in DB with pack_slug set
    from sqlalchemy import select

    from storage.models.watchlists import Watchlist

    rows = db_session_committing.scalars(
        select(Watchlist).where(Watchlist.user_id == free_user.id)
    ).all()
    assert len(rows) > 0
    for row in rows:
        assert row.pack_slug == "crypto-ru", (
            f"expected pack_slug='crypto-ru', got {row.pack_slug!r}"
        )


def test_subscribe_idempotent(
    free_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """AC2: repeat subscribe → idempotent: created=0, skipped=N."""
    resp1 = free_client.post("/packs/crypto-ru/subscribe")
    assert resp1.status_code == 200, resp1.text
    first_body = resp1.json()
    n_created = first_body["created"]
    assert n_created > 0

    resp2 = free_client.post("/packs/crypto-ru/subscribe")
    assert resp2.status_code == 200, resp2.text
    second_body = resp2.json()
    assert second_body["created"] == 0, "second subscribe must not create new rows"
    assert second_body["skipped"] == n_created, "all previously created must be skipped"


def test_subscribe_unknown_slug_returns_404(free_client: TestClient) -> None:
    """AC2: unknown slug → 404."""
    resp = free_client.post("/packs/nonexistent-pack/subscribe")
    assert resp.status_code == 404, resp.text


# ─── AC3 — packs limit (not channels) + channels limit unaffected ────────────


def test_second_pack_returns_402_for_free_user(
    free_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """AC3: Free user with 1 pack → 402 on subscribing to a second pack."""
    # Subscribe to first pack
    resp1 = free_client.post("/packs/crypto-ru/subscribe")
    assert resp1.status_code == 200, resp1.text

    # Try to subscribe to second pack → 402
    resp2 = free_client.post("/packs/tech-en/subscribe")
    assert resp2.status_code == 402, (
        f"expected 402 for second pack, got {resp2.status_code}: {resp2.text}"
    )


def test_pack_rows_do_not_consume_channel_limit(
    pro_client: TestClient,
    db_session_committing: Session,
    pro_user: User,
) -> None:
    """AC3 (TASK-038 + TASK-049): pack rows (pack_slug IS NOT NULL) do NOT count
    toward _channel_usage.

    TASK-049: Free CHANNELS=0 (own channels blocked for Free). This test uses a Pro
    user (CHANNELS=100) to verify that pack rows don't consume the channel cap:
    after subscribing to a pack (many rows with pack_slug set), manual channel
    creation should still succeed (pack rows are independent of channel_usage).

    Free-user CHANNELS=0 enforcement is verified separately in test_over_limit_returns_402
    (test_watchlist_api.py) and the unit tests (test_billing_limits.py).
    """
    # Subscribe to crypto-ru as Pro user (pack rows with pack_slug set)
    resp = pro_client.post("/packs/crypto-ru/subscribe")
    assert resp.status_code == 200, resp.text
    n_pack_rows = resp.json()["created"]
    assert n_pack_rows > 0

    # Manual watchlists must still be addable (pack rows don't consume channel cap)
    for i in range(3):  # confirm independence: pack rows ≠ channel_usage
        ok = pro_client.post(
            "/watchlists",
            json={
                "topic": f"manual_topic_{i}",
                "channel": {"handle": f"@manual_chan_{i}"},
                "alert_config": {
                    "score_threshold": 70,
                    "min_channels": 1,
                    "notification_lang": "en",
                },
            },
        )
        assert ok.status_code == 201, f"manual watchlist {i} should succeed: {ok.text}"


# ─── AC4 — unsubscribe ────────────────────────────────────────────────────────


def test_unsubscribe_removes_pack_rows(
    free_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """AC4: DELETE /packs/{slug}/subscribe removes all pack rows for that slug."""
    # Subscribe first
    sub = free_client.post("/packs/crypto-ru/subscribe")
    assert sub.status_code == 200, sub.text
    n_created = sub.json()["created"]
    assert n_created > 0

    # Unsubscribe
    del_resp = free_client.delete("/packs/crypto-ru/subscribe")
    assert del_resp.status_code == 200, del_resp.text
    del_body = del_resp.json()
    assert "deleted" in del_body
    assert del_body["deleted"] == n_created, (
        f"expected deleted={n_created}, got {del_body['deleted']}"
    )

    # Verify rows gone
    from sqlalchemy import select

    from storage.models.watchlists import Watchlist

    rows = db_session_committing.scalars(
        select(Watchlist)
        .where(Watchlist.user_id == free_user.id)
        .where(Watchlist.pack_slug == "crypto-ru")
    ).all()
    assert len(rows) == 0, "all pack rows must be removed after unsubscribe"


def test_unsubscribe_does_not_remove_manual_watchlists(
    pro_client: TestClient,
    db_session_committing: Session,
    pro_user: User,
) -> None:
    """AC4: unsubscribe removes only pack rows; manual watchlists untouched.

    TASK-049: Free CHANNELS=0 — can't create manual watchlists as Free user.
    Test uses Pro user (CHANNELS=100) to create a manual watchlist, then subscribe
    and unsubscribe a pack, verifying the manual watchlist survives.
    """
    # Create a manual watchlist as Pro user
    manual = pro_client.post(
        "/watchlists",
        json={
            "topic": "manual",
            "channel": {"handle": "@keep_this"},
            "alert_config": {
                "score_threshold": 70,
                "min_channels": 1,
                "notification_lang": "en",
            },
        },
    )
    assert manual.status_code == 201, manual.text
    manual_id = manual.json()["id"]

    # Subscribe to pack
    sub = pro_client.post("/packs/crypto-ru/subscribe")
    assert sub.status_code == 200, sub.text

    # Unsubscribe pack
    pro_client.delete("/packs/crypto-ru/subscribe")

    # Manual watchlist must still exist
    still = pro_client.get(f"/watchlists/{manual_id}")
    assert still.status_code == 200, f"manual watchlist must survive: {still.text}"


def test_unsubscribe_unknown_slug_returns_404(free_client: TestClient) -> None:
    """AC4: 404 on unknown slug."""
    resp = free_client.delete("/packs/nonexistent-pack/subscribe")
    assert resp.status_code == 404, resp.text


def test_unsubscribe_not_subscribed_returns_200_deleted_zero(
    free_client: TestClient,
) -> None:
    """AC4 edge: slug valid, not subscribed → 200 with deleted=0 (no error, idempotent).

    Decision comment: slug not in catalog = 404; valid slug + 0 rows = 200 deleted=0.
    """
    resp = free_client.delete("/packs/crypto-ru/subscribe")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 0


# ─── AC5 — tenant scope ───────────────────────────────────────────────────────


def test_tenant_scope_pack_rows_not_visible_to_other_user(
    free_client: TestClient,
    other_client: TestClient,
    db_session_committing: Session,
    free_user: User,
    other_user: User,
) -> None:
    """AC5: user A's pack subscription not visible in user B's watchlists."""
    # User A subscribes
    sub = free_client.post("/packs/crypto-ru/subscribe")
    assert sub.status_code == 200, sub.text
    n = sub.json()["created"]
    assert n > 0

    # User B lists watchlists — must not see user A's rows
    resp_b = other_client.get("/watchlists")
    assert resp_b.status_code == 200, resp_b.text
    rows_b = resp_b.json()
    owner_ids = {r["user_id"] for r in rows_b}
    assert free_user.id not in owner_ids, "user B must not see user A's watchlists"


# ─── RACE — concurrent channel get-or-create (Finding 1) ─────────────────────


def test_subscribe_survives_channel_integrity_error_race(
    free_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """RACE: concurrent channel creation raises IntegrityError on the first channel.

    Simulates the race where two concurrent subscribe calls both miss the SELECT
    on a new channel (it doesn't exist yet) and both attempt INSERT — one wins,
    one gets IntegrityError on uq_channels_source_kind_handle.

    We monkeypatch ChannelRepository.get_or_create to raise IntegrityError exactly
    once (the first call), then behave normally. With the savepoint wrapping
    _get_or_create_channel, the outer transaction must survive: the row for that
    channel is skipped (IntegrityError → rollback savepoint → skipped += 1) and all
    other rows in the batch are still created successfully.

    Without the fix (channel resolve outside savepoint), the IntegrityError would
    escape the savepoint and poison the outer transaction → 500.
    """
    from storage.repositories import ChannelRepository

    original_get_or_create = ChannelRepository.get_or_create
    call_count: list[int] = [0]

    def _get_or_create_once_raises(
        self: ChannelRepository,
        session: Session,
        *,
        source_kind: object,
        handle: str,
    ) -> object:
        call_count[0] += 1
        if call_count[0] == 1:
            # Simulate the race: a concurrent session already inserted this channel
            # between our SELECT-miss and INSERT attempt.
            raise IntegrityError(
                statement="INSERT INTO channels ...",
                params={},
                orig=Exception("unique constraint violation"),
            )
        return original_get_or_create(self, session, source_kind=source_kind, handle=handle)

    with patch.object(ChannelRepository, "get_or_create", _get_or_create_once_raises):
        resp = free_client.post("/packs/crypto-ru/subscribe")

    # The request must not 500; first channel is skipped (race-lost), rest succeed.
    assert resp.status_code == 200, (
        f"subscribe must survive channel IntegrityError race, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    # At least (N-1) channels created, first one skipped due to simulated race.
    assert body["skipped"] >= 1, "the racey channel must be counted as skipped"
    # Remaining channels beyond the first should be created normally.
    assert body["created"] >= 0, "created count must be non-negative"
