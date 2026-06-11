"""Watchlist CRUD API integration tests (marker: integration).

Runs against the live pgvector Postgres (same `Settings.database_url` as the
other integration tests). `current_user` is overridden to a fixture user, and the
sync DB session dependency is bound to the test session, so the whole CRUD surface
is exercised over HTTP via `TestClient`.

User decision (overrides task doc): ONE DB row = ONE watchlist
`(user_id, channel_id, topic)` + alert-config. A watchlist carries a SINGLE
channel and is addressed by its numeric row id.

TASK-049: Free CHANNELS=0 (Free = воронка). CRUD tests use Pro plan user so that
watchlist creation is not blocked by the new Free channel limit. The plan-limit
test (AC5) now verifies that a Free user cannot create even ONE own channel (→ 402).
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.auth.api_key import current_user_or_api_key
from api.deps import current_user
from api.main import app
from api.watchlist.deps import get_db_session
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import User

pytestmark = pytest.mark.integration


def _make_user(session: Session, email: str, plan: str = "pro") -> User:
    """Create a test user with an active subscription for paid plans.

    TASK-049: Free CHANNELS=0 — CRUD tests need plan=pro + active subscription.
    `effective_plan` in billing/limits.py resolves pro→Free if there is no active
    subscription row in the DB, so we create one here for paid-plan users.

    Pass plan="free" explicitly for Free-user limit-enforcement tests.
    """
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


def _payload(handle: str = "@channel_one", topic: str = "ai") -> dict[str, object]:
    return {
        "topic": topic,
        "channel": {"handle": handle},
        "alert_config": {
            "score_threshold": 70,
            "min_channels": 2,
            "notification_lang": "en",
        },
    }


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """A session whose flushes are visible to the app (shares one transaction).

    The app's `get_db_session` dependency is overridden onto THIS session so a row
    inserted by the route handler is readable by the test (and vice versa) without
    cross-connection isolation. Rows are wiped via the `db_session` teardown pattern
    handled by the outer fixtures.
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
    return _make_user(db_session_committing, "owner@example.com")


@pytest.fixture
def client(db_session_committing: Session, user: User) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    # Override both current_user (mutations: POST/PATCH/DELETE) and
    # current_user_or_api_key (read: GET /watchlists, GET /watchlists/{id}) —
    # the latter was updated in TASK-028 to accept cookie OR X-API-Key.
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


def test_create_returns_201_with_user_id(client: TestClient, user: User) -> None:
    """AC1 (RED anchor): create -> 201 + body carrying id and the owner's user_id."""
    resp = client.post("/watchlists", json=_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["user_id"] == user.id
    assert body["topic"] == "ai"
    assert body["channel"]["handle"] == "@channel_one"
    assert body["channel"]["kind"] == "telegram"
    assert body["alert_config"]["score_threshold"] == 70


def test_list_returns_only_own(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC2: GET / lists only the caller's watchlists."""
    other = _make_user(db_session_committing, "other@example.com")
    db_session_committing.flush()
    from storage.models.channels import Channel, SourceKind
    from storage.models.watchlists import Watchlist

    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@foreign")
    db_session_committing.add(ch)
    db_session_committing.flush()
    db_session_committing.add(
        Watchlist(user_id=other.id, channel_id=ch.id, topic="theirs", threshold=1.0)
    )
    db_session_committing.flush()

    client.post("/watchlists", json=_payload(handle="@mine_chan", topic="mine"))

    resp = client.get("/watchlists")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == user.id
    assert rows[0]["topic"] == "mine"


def test_update_and_delete_enforce_ownership(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC3: another tenant's id -> 404; own id -> 200/204."""
    other = _make_user(db_session_committing, "other2@example.com")
    db_session_committing.flush()
    from storage.models.channels import Channel, SourceKind
    from storage.models.watchlists import Watchlist

    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@foreign2")
    db_session_committing.add(ch)
    db_session_committing.flush()
    foreign = Watchlist(user_id=other.id, channel_id=ch.id, topic="theirs", threshold=1.0)
    db_session_committing.add(foreign)
    db_session_committing.flush()
    foreign_id = foreign.id

    # Foreign id is indistinguishable from missing -> 404 on update and delete.
    assert client.patch(f"/watchlists/{foreign_id}", json={"topic": "hacked"}).status_code == 404
    assert client.delete(f"/watchlists/{foreign_id}").status_code == 404

    created = client.post("/watchlists", json=_payload(handle="@own_chan")).json()
    own_id = created["id"]
    upd = client.patch(f"/watchlists/{own_id}", json={"topic": "renamed"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["topic"] == "renamed"
    assert client.delete(f"/watchlists/{own_id}").status_code == 204
    assert client.get(f"/watchlists/{own_id}").status_code == 404


def test_bad_handle_returns_422(client: TestClient) -> None:
    """AC4: a malformed handle is rejected at the boundary (Pydantic 422)."""
    resp = client.post("/watchlists", json=_payload(handle="@bad handle!"))
    assert resp.status_code == 422, resp.text


def test_over_limit_returns_402(db_session_committing: Session) -> None:
    """AC5 / AC2 (TASK-049): Free user cannot create ANY own channel (CHANNELS=0 → 402).

    The fixture `client` uses a Pro user (so CRUD tests work). Here we create a fresh
    Free user to verify the new Free CHANNELS=0 limit enforcement directly.
    """
    from collections.abc import Iterator as IteratorType

    from api.auth.api_key import current_user_or_api_key
    from api.deps import current_user
    from api.watchlist.deps import get_db_session

    free_user = _make_user(db_session_committing, "freelimit@example.com", plan="free")
    db_session_committing.flush()

    def _session_override() -> IteratorType[Session]:
        yield db_session_committing

    app.dependency_overrides[current_user] = lambda: free_user
    app.dependency_overrides[current_user_or_api_key] = lambda: free_user
    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as free_client:
            # Free CHANNELS=0 → first own channel create → 402
            resp = free_client.post("/watchlists", json=_payload(handle="@chan_free_1", topic="t1"))
            assert resp.status_code == 402, resp.text
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
        app.dependency_overrides.pop(get_db_session, None)


def test_default_kind_is_telegram(client: TestClient) -> None:
    """AC6: omitting kind stores/returns source_kind == 'telegram'."""
    resp = client.post("/watchlists", json=_payload(handle="@default_kind"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["channel"]["kind"] == "telegram"


def test_no_auth_returns_401() -> None:
    """AC7: without the current_user override the route is 401 (auth-guard)."""
    # No override of current_user here -> the real dependency rejects the request.
    with TestClient(app) as anon:
        resp = anon.post("/watchlists", json=_payload())
    assert resp.status_code == 401


def test_duplicate_channel_topic_returns_409(client: TestClient) -> None:
    """Same (channel, topic) for one user is a conflict, not a 500.

    Exercises the IntegrityError -> rollback -> DuplicateWatchlistError -> 409 path
    (unique (user_id, channel_id, topic) from task-002).
    """
    first = client.post("/watchlists", json=_payload(handle="@dup_chan", topic="dup"))
    assert first.status_code == 201, first.text
    second = client.post("/watchlists", json=_payload(handle="@dup_chan", topic="dup"))
    assert second.status_code == 409, second.text
