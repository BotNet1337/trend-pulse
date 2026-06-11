"""API-keys integration tests (marker: integration) — TASK-028.

RED anchor for AC1/AC2: Team POST /api-keys → 201 + plaintext key (once in body),
DB stores key_hash (≠ plaintext) + prefix; Free/Pro → 403 (feature-gate API_ACCESS).

After GREEN: AC3 (X-API-Key on GET /alerts → 200, last_used_at updated),
AC4 (list masked, revoke → 401), AC6 (mutation with key → 401/403, cookie flow OK).

Pattern: mirrors test_watchlist_api.py / test_alerts_api.py (TestClient + session
override + current_user override). One ephemeral PG for the whole session.

Team-user fixtures include an active Subscription row (required by effective_plan
for non-Free plan check in billing/limits.py — expires_at must be in the future).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.auth.api_key import _get_db_session as api_key_get_db_session
from api.auth.api_key import current_user_or_api_key
from api.deps import current_user
from api.main import app
from api.watchlist.deps import get_db_session
from storage.models.subscriptions import Subscription
from storage.models.users import PLAN_FREE, PLAN_PRO, PLAN_TEAM, User

pytestmark = pytest.mark.integration


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_user(session: Session, email: str, plan: str = PLAN_TEAM) -> User:
    user = User(email=email, hashed_password="x" * 16, plan=plan)
    session.add(user)
    session.flush()
    return user


def _make_subscription(session: Session, user: User, plan: str = PLAN_TEAM) -> Subscription:
    """Create an active Subscription for `user` so effective_plan returns `plan`."""
    sub = Subscription(
        user_id=user.id,
        plan=plan,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(sub)
    session.flush()
    return sub


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """A session whose flushes are immediately visible to the app (shared conn).

    All tables are wiped on teardown (same isolation pattern as watchlist tests).
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
def team_user(db_session_committing: Session) -> User:
    """Team user with active subscription (required by effective_plan)."""
    user = _make_user(db_session_committing, "team@example.com", plan=PLAN_TEAM)
    _make_subscription(db_session_committing, user, plan=PLAN_TEAM)
    return user


@pytest.fixture
def free_user(db_session_committing: Session) -> User:
    return _make_user(db_session_committing, "free@example.com", plan=PLAN_FREE)


@pytest.fixture
def pro_user(db_session_committing: Session) -> User:
    return _make_user(db_session_committing, "pro@example.com", plan=PLAN_PRO)


@pytest.fixture
def team_client(db_session_committing: Session, team_user: User) -> Iterator[TestClient]:
    """TestClient authenticated as team_user via cookie-dep override.

    Overrides BOTH `current_user` (for POST/DELETE /api-keys routes) AND
    `current_user_or_api_key` (for GET /alerts / GET /watchlists read-routes).
    Also overrides both session deps (get_db_session for route layer,
    api_key_get_db_session for X-API-Key auth path) to share the test session.
    """

    def _override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: team_user
    app.dependency_overrides[current_user_or_api_key] = lambda: team_user
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


@pytest.fixture
def free_client(db_session_committing: Session, free_user: User) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: free_user
    app.dependency_overrides[current_user_or_api_key] = lambda: free_user
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


@pytest.fixture
def pro_client(db_session_committing: Session, pro_user: User) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: pro_user
    app.dependency_overrides[current_user_or_api_key] = lambda: pro_user
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


# ─── AC1 RED anchor — Team creates key, plaintext exactly once ────────────────


def test_team_create_api_key_returns_201_with_plaintext(
    team_client: TestClient,
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC1: Team user POST /api-keys → 201; plaintext key in body exactly once;
    DB stores key_hash (≠ plaintext) and prefix; no plaintext persisted in DB.
    """
    resp = team_client.post("/v1/api-keys", json={"name": "my-key"})
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Response must contain the key field (plaintext, shown once)
    assert "key" in body, "plaintext key must be in the response"
    plaintext = body["key"]
    assert isinstance(plaintext, str)
    assert len(plaintext) > 0

    # Other fields present
    assert "id" in body
    assert "name" in body
    assert body["name"] == "my-key"
    assert "prefix" in body
    assert "created_at" in body

    # Plaintext must NOT appear in DB
    from storage.models.api_keys import ApiKey

    row = db_session_committing.get(ApiKey, body["id"])
    assert row is not None
    assert row.key_hash != plaintext, "key_hash must NOT be the plaintext"
    assert len(row.key_hash) == 64, "SHA-256 hex digest should be 64 chars"
    assert plaintext.startswith(row.prefix), "prefix should be a leading substring of plaintext"
    assert row.user_id == team_user.id

    # Plaintext must appear EXACTLY ONCE in the response text (not repeated)
    response_text = resp.text
    assert response_text.count(plaintext) == 1, "plaintext must appear exactly once in response"


# ─── AC2 RED anchor — Free and Pro → 403 (feature-gate API_ACCESS) ───────────


def test_free_user_create_api_key_returns_403(free_client: TestClient) -> None:
    """AC2: Free user POST /api-keys → 403 (API_ACCESS feature-gate).

    Note: free_client overrides current_user_or_api_key only for read routes;
    POST /api-keys uses `current_user` (cookie-only), overridden here to free_user.
    The assert_within_limit(API_ACCESS) for Free plan raises PlanLimitExceeded→403.
    """
    resp = free_client.post("/v1/api-keys", json={"name": "should-fail"})
    assert resp.status_code == 403, resp.text


def test_pro_user_create_api_key_returns_403(pro_client: TestClient) -> None:
    """AC2: Pro user POST /api-keys → 403 (API_ACCESS not on Pro plan)."""
    resp = pro_client.post("/v1/api-keys", json={"name": "should-fail-pro"})
    assert resp.status_code == 403, resp.text


def test_free_user_key_not_created_in_db(
    free_client: TestClient, db_session_committing: Session
) -> None:
    """AC2: After 403, no api_key row should exist in the DB."""
    free_client.post("/v1/api-keys", json={"name": "should-fail"})
    from sqlalchemy import select

    from storage.models.api_keys import ApiKey

    count = db_session_committing.scalar(select(ApiKey).limit(1))
    assert count is None, "no API key should be stored for Free user"


# ─── AC3 — X-API-Key on GET /alerts ──────────────────────────────────────────


def test_x_api_key_authenticates_on_get_alerts(
    team_client: TestClient,
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC3: Valid X-API-Key header (no cookie) → 200 on GET /alerts; last_used_at updated."""
    # Create a key (uses current_user override)
    resp = team_client.post("/v1/api-keys", json={"name": "alerts-key"})
    assert resp.status_code == 201, resp.text
    plaintext = resp.json()["key"]
    key_id = resp.json()["id"]

    # Remove all auth overrides — use only X-API-Key header (real auth path)
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(current_user_or_api_key, None)

    def _override() -> Iterator[Session]:
        yield db_session_committing

    # Override both session deps so X-API-Key resolve uses the same test session
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override

    try:
        with TestClient(app) as raw_client:
            resp2 = raw_client.get("/v1/alerts", headers={"X-API-Key": plaintext})
        assert resp2.status_code == 200, f"X-API-Key should authenticate: {resp2.text}"

        # Verify last_used_at was updated
        from storage.models.api_keys import ApiKey

        db_session_committing.expire_all()
        row = db_session_committing.get(ApiKey, key_id)
        assert row is not None
        assert row.last_used_at is not None, "last_used_at should be updated after use"
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)

    # Verify tenant scoping (only own alerts, not other users')
    body = resp2.json()
    assert "items" in body


def test_x_api_key_tenant_scoped(
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC3: X-API-Key auth returns only the key-owner's data (tenant-scoped)."""
    from api.api_keys.service import create_api_key

    _row, plaintext = create_api_key(db_session_committing, user_id=team_user.id, name="scope-key")
    db_session_committing.commit()

    def _override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(current_user_or_api_key, None)
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override

    try:
        with TestClient(app) as c:
            resp = c.get("/v1/alerts", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        # Only team_user's alerts — should be empty (no alerts created) but 200 OK
        for item in items:
            assert item.get("user_id") == team_user.id
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


# ─── AC4 — list masked + revoke ───────────────────────────────────────────────


def test_list_api_keys_returns_masked(
    team_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: GET /api-keys returns list without full key/key_hash; prefix/name/timestamps shown."""
    team_client.post("/v1/api-keys", json={"name": "key-one"})
    team_client.post("/v1/api-keys", json={"name": "key-two"})

    resp = team_client.get("/v1/api-keys")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 2

    for item in items:
        assert "id" in item
        assert "name" in item
        assert "prefix" in item
        assert "created_at" in item
        # Sensitive fields must NOT be present
        assert "key" not in item, "plaintext key must not appear in list"
        assert "key_hash" not in item, "key_hash must not appear in list"


def test_revoke_api_key(
    team_client: TestClient,
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC4: DELETE /api-keys/{id} revokes the key (revoked_at set); subsequent use → 401."""
    # Create key
    create_resp = team_client.post("/v1/api-keys", json={"name": "to-revoke"})
    assert create_resp.status_code == 201, create_resp.text
    key_id = create_resp.json()["id"]
    plaintext = create_resp.json()["key"]

    # Revoke it
    del_resp = team_client.delete(f"/v1/api-keys/{key_id}")
    assert del_resp.status_code == 204, del_resp.text

    # DB: revoked_at should be set
    from storage.models.api_keys import ApiKey

    db_session_committing.expire_all()
    row = db_session_committing.get(ApiKey, key_id)
    assert row is not None
    assert row.revoked_at is not None, "revoked_at should be set after DELETE"

    # Revoked key on GET /alerts → 401 (real auth path, no overrides)
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(current_user_or_api_key, None)

    def _override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override

    try:
        with TestClient(app) as raw_client:
            resp = raw_client.get("/v1/alerts", headers={"X-API-Key": plaintext})
        assert resp.status_code == 401, f"Revoked key should yield 401: {resp.text}"
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


def test_delete_nonexistent_api_key_returns_404(team_client: TestClient) -> None:
    """AC4: DELETE /api-keys/{id} for non-existent id → 404."""
    resp = team_client.delete("/v1/api-keys/999999")
    assert resp.status_code == 404, resp.text


def test_delete_other_users_key_returns_404(
    team_client: TestClient,
    db_session_committing: Session,
    free_user: User,
) -> None:
    """AC4: Attempt to revoke another user's key → 404 (no existence leak)."""
    from api.api_keys.service import create_api_key

    other_row, _ = create_api_key(db_session_committing, user_id=free_user.id, name="other-key")
    db_session_committing.flush()

    resp = team_client.delete(f"/v1/api-keys/{other_row.id}")
    assert resp.status_code == 404, resp.text


# ─── AC6 — surface limited to read; mutations with X-API-Key denied ───────────


def test_mutation_watchlist_with_api_key_denied(
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC6: POST /watchlists with X-API-Key (no cookie) → 401 (not authorized for mutations).

    POST /watchlists uses `current_user` dep (cookie-only), not `current_user_or_api_key`.
    So X-API-Key header cannot authorize it → 401.
    """
    from api.api_keys.service import create_api_key

    _row, plaintext = create_api_key(db_session_committing, user_id=team_user.id, name="mut-key")
    db_session_committing.commit()

    def _override() -> Iterator[Session]:
        yield db_session_committing

    # Remove all auth overrides — raw X-API-Key only
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(current_user_or_api_key, None)
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[api_key_get_db_session] = _override

    payload = {
        "topic": "ai",
        "channel": {"handle": "@testchan"},
        "alert_config": {
            "score_threshold": 70,
            "min_channels": 2,
            "notification_lang": "en",
        },
    }

    try:
        with TestClient(app) as c:
            resp = c.post("/v1/watchlists", json=payload, headers={"X-API-Key": plaintext})
        # Mutations via API-key must be rejected (401 from current_user dep — no cookie)
        assert resp.status_code in (401, 403), (
            f"Mutation with X-API-Key should be denied, got {resp.status_code}: {resp.text}"
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(api_key_get_db_session, None)


def test_cookie_flow_on_get_alerts_still_works(
    team_client: TestClient,
    db_session_committing: Session,
    team_user: User,
) -> None:
    """AC6: Cookie-based (UI) flow on GET /alerts still returns 200 (not broken).

    team_client overrides `current_user_or_api_key` → team_user (simulates
    cookie-authenticated UI flow — the dep is overridden the same way it would
    be resolved by the real cookie/JWT path).
    """
    resp = team_client.get("/v1/alerts")
    assert resp.status_code == 200, f"Cookie flow should still work: {resp.text}"
