"""Integration: lifecycle emails — welcome, digest/win-back tick, unsubscribe (TASK-069).

Ephemeral PG (pgvector/pgvector:pg16) — start before running:
    docker run -d --name tp069_pg -e POSTGRES_PASSWORD=pg -e POSTGRES_USER=pg \\
        -e POSTGRES_DB=trendpulse -p 15437:5432 pgvector/pgvector:pg16

ENV:
    POSTGRES_HOST=localhost POSTGRES_PORT=15437 POSTGRES_USER=pg
    POSTGRES_PASSWORD=pg POSTGRES_DB=trendpulse
    (auth secrets are seeded by tests/conftest.py)

Marked `@pytest.mark.integration` — not run in `make ci-fast`.

Covers:
  - AC1: welcome email sent exactly once on the verify transition; re-verify
    does not duplicate; SMTP failure does not break the verify response.
  - AC2: digest goes to a due user with delivered alerts; same-day re-tick is
    a no-op; an empty week sends nothing.
  - AC3: win-back goes once per inactivity cycle.
  - AC4: GET /email/unsubscribe sets the flag idempotently, blocks the next
    tick, garbage token → uniform 400 envelope.
  - AC5: unverified users get nothing lifecycle; emails carry List-Unsubscribe.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from api.main import app
from config import get_settings
from notifications.lifecycle import collect_digest_items, generate_unsubscribe_token
from notifications.tasks import _send_lifecycle_emails
from storage.database import get_async_session
from storage.models.alerts import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_PENDING,
    Alert,
)
from storage.models.clusters import EMBEDDING_DIM, Cluster
from storage.models.users import User
from storage.models.watchlists import Watchlist

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fixtures / seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient with the auth user-db bound to a fresh async engine
    (mirrors test_auth_verify.py)."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _make_user(
    session: Session,
    *,
    email: str,
    is_verified: bool = True,
    opt_out: bool = False,
    digest_last_sent_at: datetime | None = None,
    winback_last_sent_at: datetime | None = None,
) -> User:
    user = User(
        email=email,
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=is_verified,
        lifecycle_emails_opt_out=opt_out,
        digest_last_sent_at=digest_last_sent_at,
        winback_last_sent_at=winback_last_sent_at,
    )
    session.add(user)
    session.flush()
    return user


def _seed_delivered_alert(
    session: Session,
    *,
    user: User,
    topic: str,
    score: float,
    delivered_at: datetime,
    pack_slug: str | None = None,
) -> None:
    """Cluster + watchlist + delivered alert for one user/topic."""
    cluster = Cluster(
        user_id=user.id,
        topic=topic,
        embedding=[0.0] * EMBEDDING_DIM,
    )
    session.add(cluster)
    session.flush()
    # channels table requires a channel row; watchlist FKs channels.id.
    from storage.models.channels import Channel

    channel = session.scalars(select(Channel).limit(1)).first()
    if channel is None:
        channel = Channel(handle=f"chan-{user.id}-{abs(hash(topic)) % 10_000}")
        session.add(channel)
        session.flush()
    session.add(
        Watchlist(
            user_id=user.id,
            channel_id=channel.id,
            topic=topic,
            pack_slug=pack_slug,
        )
    )
    session.add(
        Alert(
            user_id=user.id,
            cluster_id=cluster.id,
            score=score,
            channels_count=1,
            delivered_at=delivered_at,
            delivery_status=DELIVERY_STATUS_DELIVERED,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# AC4 — unsubscribe endpoint
# ---------------------------------------------------------------------------


def test_unsubscribe_sets_flag_idempotently(client: TestClient, db_session: Session) -> None:
    user = _make_user(db_session, email="unsub@example.com")
    db_session.commit()
    token = generate_unsubscribe_token(user.id)

    resp1 = client.get(f"/v1/email/unsubscribe?token={token}")
    assert resp1.status_code == 200, resp1.text
    assert "unsubscribed" in resp1.text.lower()

    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.lifecycle_emails_opt_out is True

    # Repeat click — idempotent 200, flag stays True.
    resp2 = client.get(f"/v1/email/unsubscribe?token={token}")
    assert resp2.status_code == 200, resp2.text
    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.lifecycle_emails_opt_out is True


def test_unsubscribe_garbage_token_uniform_400(client: TestClient) -> None:
    """Tampered/garbage/foreign tokens → the same 400 envelope (no oracle)."""
    for bad in ("garbage", "a.b.c", generate_unsubscribe_token(1)[:-4] + "AAAA"):
        resp = client.get(f"/v1/email/unsubscribe?token={bad}")
        assert resp.status_code == 400, f"{bad!r}: {resp.status_code}"
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION"
        # No reason details leak (uniform message).
        assert body["error"]["message"] == "Invalid unsubscribe link."


def test_unsubscribe_deleted_user_returns_success_page(client: TestClient) -> None:
    """Valid token for a missing user → same success HTML (no enumeration)."""
    token = generate_unsubscribe_token(999_999)
    resp = client.get(f"/v1/email/unsubscribe?token={token}")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# AC1 — welcome on verify
# ---------------------------------------------------------------------------


def test_welcome_sent_once_on_verify(client: TestClient) -> None:
    """Register → verify → exactly one auth/welcome send with unsubscribe parts;
    a second verify attempt does not duplicate it."""
    captured: MagicMock = MagicMock()
    email = "welcome-flow@example.com"

    with patch("api.auth.users.send_templated_email", captured):
        resp = client.post(
            "/v1/auth/register",
            json={"email": email, "password": "w3lcome-pa55word"},
        )
        assert resp.status_code == 201, resp.text

        # Extract the verify token from the captured verify-email call.
        token: str | None = None
        for call in captured.call_args_list:
            props = call.kwargs.get("props", {})
            url = str(props.get("verifyUrl", ""))
            if "token=" in url:
                from urllib.parse import parse_qs, urlparse

                token = parse_qs(urlparse(url).query)["token"][0]
        assert token is not None

        verify_resp = client.post("/v1/auth/verify", json={"token": token})
        assert verify_resp.status_code == 200, verify_resp.text

        welcome_calls = [
            c for c in captured.call_args_list if c.kwargs.get("template") == "auth/welcome"
        ]
        assert len(welcome_calls) == 1, f"expected exactly one welcome, got {len(welcome_calls)}"
        kwargs = welcome_calls[0].kwargs
        # AC5: footer link prop + List-Unsubscribe header are present.
        assert "unsubscribeUrl" in kwargs["props"]
        assert "/api/v1/email/unsubscribe?token=" in str(kwargs["props"]["unsubscribeUrl"])
        assert "List-Unsubscribe" in (kwargs.get("headers") or {})
        # CTA points at the pack-attach page.
        assert str(kwargs["props"]["dashboardUrl"]).endswith("/onboarding")

        # Re-verify with the same token → fastapi-users rejects (already
        # verified) and the hook must NOT fire again.
        again = client.post("/v1/auth/verify", json={"token": token})
        assert again.status_code != 200
        welcome_calls = [
            c for c in captured.call_args_list if c.kwargs.get("template") == "auth/welcome"
        ]
        assert len(welcome_calls) == 1


def test_welcome_failure_does_not_break_verify(client: TestClient) -> None:
    """SMTP/render failure inside the welcome hook → verify still returns 200."""
    email = "welcome-fail@example.com"
    sent: MagicMock = MagicMock()

    with patch("api.auth.users.send_templated_email", sent):
        resp = client.post(
            "/v1/auth/register",
            json={"email": email, "password": "w3lcome-pa55word"},
        )
        assert resp.status_code == 201, resp.text
        token: str | None = None
        for call in sent.call_args_list:
            props = call.kwargs.get("props", {})
            url = str(props.get("verifyUrl", ""))
            if "token=" in url:
                from urllib.parse import parse_qs, urlparse

                token = parse_qs(urlparse(url).query)["token"][0]
        assert token is not None

    failing = MagicMock(side_effect=RuntimeError("smtp down"))
    with patch("api.auth.users.send_templated_email", failing):
        verify_resp = client.post("/v1/auth/verify", json={"token": token})
        assert verify_resp.status_code == 200, verify_resp.text


# ---------------------------------------------------------------------------
# AC2/AC3/AC5 — lifecycle tick
# ---------------------------------------------------------------------------


def test_tick_sends_digest_and_is_idempotent(db_session: Session) -> None:
    user = _make_user(db_session, email="digest-due@example.com")
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="ai breakthrough",
        score=95.0,
        delivered_at=_NOW - timedelta(days=1),
        pack_slug="ai-tech",
    )
    db_session.commit()

    with (
        patch("notifications.tasks.send_weekly_digest") as mock_digest,
        patch("notifications.tasks.send_winback") as mock_winback,
    ):
        counts = _send_lifecycle_emails()

    assert counts["digests"] == 1
    mock_digest.assert_called_once()
    items = mock_digest.call_args.kwargs["items"]
    assert items and items[0].topic == "ai breakthrough"
    assert items[0].pack_slug == "ai-tech"
    # Recent delivery (1d ago) → not inactive → no win-back.
    mock_winback.assert_not_called()

    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.digest_last_sent_at is not None

    # Same-day re-tick → no-op (AC2).
    with patch("notifications.tasks.send_weekly_digest") as mock_digest2:
        counts2 = _send_lifecycle_emails()
    assert counts2["digests"] == 0
    mock_digest2.assert_not_called()


def test_tick_skips_empty_week_digest(db_session: Session) -> None:
    """Due by time but zero delivered alerts in 7d → nothing is sent and the
    last-sent marker is NOT advanced (retry next tick)."""
    user = _make_user(db_session, email="digest-empty@example.com")
    # Old delivered alert outside the 7d window — also makes win-back due,
    # which is fine: we assert digest specifically.
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="stale topic",
        score=80.0,
        delivered_at=_NOW - timedelta(days=20),
    )
    db_session.commit()

    with (
        patch("notifications.tasks.send_weekly_digest") as mock_digest,
        patch("notifications.tasks.send_winback"),
    ):
        counts = _send_lifecycle_emails()

    assert counts["digests"] == 0
    mock_digest.assert_not_called()
    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.digest_last_sent_at is None


def test_tick_sends_winback_once_per_cycle(db_session: Session) -> None:
    user = _make_user(db_session, email="winback-due@example.com")
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="quiet topic",
        score=70.0,
        delivered_at=_NOW - timedelta(days=20),
    )
    db_session.commit()

    with (
        patch("notifications.tasks.send_weekly_digest"),
        patch("notifications.tasks.send_winback") as mock_winback,
    ):
        counts = _send_lifecycle_emails()

    assert counts["winbacks"] == 1
    mock_winback.assert_called_once()
    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.winback_last_sent_at is not None

    # Re-tick: same inactivity cycle → no second win-back (AC3).
    with (
        patch("notifications.tasks.send_weekly_digest"),
        patch("notifications.tasks.send_winback") as mock_winback2,
    ):
        counts2 = _send_lifecycle_emails()
    assert counts2["winbacks"] == 0
    mock_winback2.assert_not_called()


def test_tick_skips_unverified_and_opted_out(db_session: Session) -> None:
    """AC5/AC4: unverified and opted-out users get NOTHING lifecycle."""
    unverified = _make_user(db_session, email="unverified@example.com", is_verified=False)
    opted_out = _make_user(db_session, email="opted-out@example.com", opt_out=True)
    for user, topic in ((unverified, "topic u"), (opted_out, "topic o")):
        _seed_delivered_alert(
            db_session,
            user=user,
            topic=topic,
            score=90.0,
            delivered_at=_NOW - timedelta(days=1),
        )
    db_session.commit()

    with (
        patch("notifications.tasks.send_weekly_digest") as mock_digest,
        patch("notifications.tasks.send_winback") as mock_winback,
    ):
        counts = _send_lifecycle_emails()

    assert counts == {"digests": 0, "winbacks": 0}
    mock_digest.assert_not_called()
    mock_winback.assert_not_called()


def test_tick_send_failure_does_not_mark_sent(db_session: Session) -> None:
    """EmailRenderError for one user → marker untouched, sweep continues."""
    user = _make_user(db_session, email="digest-fail@example.com")
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="ai breakthrough",
        score=95.0,
        delivered_at=_NOW - timedelta(days=1),
    )
    db_session.commit()

    from notifications.email import EmailRenderError

    with (
        patch(
            "notifications.tasks.send_weekly_digest",
            side_effect=EmailRenderError("templates down"),
        ),
        patch("notifications.tasks.send_winback"),
    ):
        counts = _send_lifecycle_emails()

    assert counts["digests"] == 0
    db_session.expire_all()
    db_user = db_session.get(User, user.id)
    assert db_user is not None and db_user.digest_last_sent_at is None


# ---------------------------------------------------------------------------
# Digest content collection (compliance §7)
# ---------------------------------------------------------------------------


def test_collect_digest_items_sanitizes_and_ranks(db_session: Session) -> None:
    user = _make_user(db_session, email="digest-content@example.com")
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="check https://spam.example @handle now",
        score=88.0,
        delivered_at=_NOW - timedelta(days=2),
    )
    _seed_delivered_alert(
        db_session,
        user=user,
        topic="top story",
        score=99.0,
        delivered_at=_NOW - timedelta(days=1),
        pack_slug="news",
    )
    # Pending alert and out-of-window alert must not appear.
    cluster = Cluster(user_id=user.id, topic="pending", embedding=[0.0] * EMBEDDING_DIM)
    db_session.add(cluster)
    db_session.flush()
    db_session.add(
        Alert(
            user_id=user.id,
            cluster_id=cluster.id,
            score=100.0,
            channels_count=1,
            delivery_status=DELIVERY_STATUS_PENDING,
        )
    )
    db_session.commit()

    items = collect_digest_items(
        db_session,
        user_id=user.id,
        now=_NOW,
        top_k=5,
        period_days=7,
    )

    assert [i.score for i in items] == [99.0, 88.0]  # score DESC
    assert items[0].topic == "top story"
    assert items[0].pack_slug == "news"
    # sanitize_topic_label strips URLs and @handles (compliance §7).
    assert "https://" not in items[1].topic
    assert "@handle" not in items[1].topic
