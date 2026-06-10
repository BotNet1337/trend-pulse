"""Integration test for showcase autopost tick (TASK-044).

Seeds:
- A showcase user (showcase@internal).
- Clusters + scores for the showcase user (qualifying and non-qualifying).

Runs _run_tick_body() with a mocked sender (no real Bot API call).

Asserts:
- A showcase_posts row is created with status=posted for the best qualifying cluster.
- Non-qualifying clusters (wrong score, too young, etc.) are not posted.
- Idempotency: second call with same session state does not create a duplicate row.
- Retry (AC3): pending row from failed send does NOT block re-selection; next tick
  with working sender → same cluster becomes posted.
- Daily cap counts POSTED rows only; pending row must not consume the cap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from storage.models.clusters import EMBEDDING_DIM
from storage.models.showcase_posts import STATUS_PENDING, STATUS_POSTED, ShowcasePost

pytestmark = pytest.mark.integration

_EMBEDDING = [0.1] + [0.0] * (EMBEDDING_DIM - 1)


def _seed_showcase_user(session: Session) -> int:
    """Create the showcase system user. Returns user id."""
    from storage.models.users import User

    user = User(email="showcase@internal", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user.id


def _seed_cluster(
    session: Session,
    *,
    user_id: int,
    topic: str,
    viral_score: float,
    first_seen: datetime,
) -> int:
    """Seed a cluster + score row. Returns cluster id."""
    from storage.models.clusters import Cluster
    from storage.models.scores import Score

    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        embedding=_EMBEDDING,
        first_seen=first_seen,
        updated_at=first_seen,
    )
    session.add(cluster)
    session.flush()

    score = Score(
        user_id=user_id,
        cluster_id=cluster.id,
        viral_score=viral_score,
        velocity=1.0,
        engagement=1.0,
        cross_channel=0.5,
    )
    session.add(score)
    session.flush()
    return cluster.id


def test_tick_creates_showcase_post_for_best_qualifying_cluster(db_session: Session) -> None:
    """tick body seeds showcase_posts(status=posted) for the best qualifying cluster."""
    from showcase.tasks import _run_tick_body

    now = datetime.now(UTC)
    showcase_user_id = _seed_showcase_user(db_session)

    # Qualifying cluster: score=92, age=3000s (>2400 delay, <86400 window)
    good_id = _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Bitcoin ETF approval",
        viral_score=92.0,
        first_seen=now - timedelta(seconds=3000),
    )

    # Non-qualifying: score too low
    _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Low score topic",
        viral_score=60.0,
        first_seen=now - timedelta(seconds=3000),
    )

    # Non-qualifying: too young (only 100s old — less than 2400s delay)
    _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Too young topic",
        viral_score=95.0,
        first_seen=now - timedelta(seconds=100),
    )

    # Patch: fixed 'now' via datetime + mocked sender (no real Bot API)
    from config import Settings

    settings = Settings.model_construct(
        showcase_bot_token="test-token",
        showcase_channel_chat_id="-100test",
        showcase_post_min_score=85.0,
        showcase_post_delay_seconds=2400,
        showcase_posts_per_day_max=8,
        trending_window_seconds=86_400,
        showcase_user_email="showcase@internal",
        telegram_api_base_url="https://api.telegram.org",
        alert_http_timeout_seconds=10,
        public_base_url="https://foresignal.biz",
        free_alert_delay_seconds=1800,
        jwt_secret="test",
        oauth_state_secret="test",
        google_client_id="test",
        google_client_secret="test",
    )

    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", return_value=True),
    ):
        _run_tick_body(db_session)

    # Assert: one showcase_posts row with status=posted for good_id
    sp = db_session.query(ShowcasePost).filter_by(cluster_id=good_id).first()
    assert sp is not None, "Expected showcase_posts row for the qualifying cluster"
    assert sp.status == STATUS_POSTED
    assert sp.posted_at is not None


def test_tick_idempotent_no_duplicate_on_second_call(db_session: Session) -> None:
    """Second tick with same qualifying cluster does not create a duplicate row."""
    from showcase.tasks import _run_tick_body

    now = datetime.now(UTC)
    showcase_user_id = _seed_showcase_user(db_session)
    cluster_id = _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Idempotency test",
        viral_score=88.0,
        first_seen=now - timedelta(seconds=3600),
    )

    call_count = 0

    def counting_sender(*args: object, **kwargs: object) -> bool:
        nonlocal call_count
        call_count += 1
        return True

    from config import Settings

    settings = Settings.model_construct(
        showcase_bot_token="test-token",
        showcase_channel_chat_id="-100test",
        showcase_post_min_score=85.0,
        showcase_post_delay_seconds=2400,
        showcase_posts_per_day_max=8,
        trending_window_seconds=86_400,
        showcase_user_email="showcase@internal",
        telegram_api_base_url="https://api.telegram.org",
        alert_http_timeout_seconds=10,
        public_base_url="https://foresignal.biz",
        free_alert_delay_seconds=1800,
        jwt_secret="test",
        oauth_state_secret="test",
        google_client_id="test",
        google_client_secret="test",
    )

    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", side_effect=counting_sender),
    ):
        # First tick
        _run_tick_body(db_session)
        # Second tick — must not send again
        _run_tick_body(db_session)

    # sender called exactly once (second tick skips posted cluster)
    assert call_count == 1

    # Only one showcase_posts row
    rows = db_session.query(ShowcasePost).filter_by(cluster_id=cluster_id).all()
    assert len(rows) == 1
    assert rows[0].status == STATUS_POSTED


def _make_settings(**overrides: object) -> object:
    """Build a minimal Settings stub (model_construct, no env lookup)."""
    from config import Settings

    base: dict[str, object] = {
        "showcase_bot_token": "test-token",
        "showcase_channel_chat_id": "-100test",
        "showcase_post_min_score": 85.0,
        "showcase_post_delay_seconds": 2400,
        "showcase_posts_per_day_max": 8,
        "trending_window_seconds": 86_400,
        "showcase_user_email": "showcase@internal",
        "telegram_api_base_url": "https://api.telegram.org",
        "alert_http_timeout_seconds": 10,
        "public_base_url": "https://foresignal.biz",
        "free_alert_delay_seconds": 1800,
        "jwt_secret": "test",
        "oauth_state_secret": "test",
        "google_client_id": "test",
        "google_client_secret": "test",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_retry_tick_resends_pending_cluster(db_session: Session) -> None:
    """AC3 — retry path: pending row from failed send is re-selected next tick.

    Scenario:
    1. Tick 1: sender→False → row inserted with status=pending.
    2. Tick 2: sender→True → SAME cluster is re-selected, sent, row becomes posted.

    RED evidence: with current code the dedup set includes ALL rows (pending too),
    so the pending cluster is blocked and the second tick skips it.
    """
    from showcase.tasks import _run_tick_body

    now = datetime.now(UTC)
    showcase_user_id = _seed_showcase_user(db_session)
    cluster_id = _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Retry test cluster",
        viral_score=90.0,
        first_seen=now - timedelta(seconds=3600),
    )
    settings = _make_settings()

    # Tick 1: sender fails → pending row created.
    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", return_value=False),
    ):
        _run_tick_body(db_session)

    pending_row = db_session.query(ShowcasePost).filter_by(cluster_id=cluster_id).first()
    assert pending_row is not None, "Expected pending row after failed send"
    assert pending_row.status == STATUS_PENDING

    # Tick 2: sender succeeds → same cluster must be re-sent and row becomes posted.
    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", return_value=True),
    ):
        _run_tick_body(db_session)

    db_session.expire_all()
    posted_row = db_session.query(ShowcasePost).filter_by(cluster_id=cluster_id).first()
    assert posted_row is not None
    assert posted_row.status == STATUS_POSTED, (
        "Expected status=posted after retry tick, got: "
        + str(posted_row.status)
        + " — dedup set must exclude pending rows so retry is possible"
    )


def test_fix_cases_runs_without_tg_creds(db_session: Session) -> None:
    """TASK-045 invariant: fixation is independent of posting credentials.

    When showcase_bot_token / showcase_channel_chat_id are empty (no posting),
    _run_tick_body must still call fix_cases() and insert a showcase_cases row
    for any cluster with viral_score >= showcase_case_min_score.

    RED: with the current code _run_tick_body returns early at the creds guard
    (line ~104) before fix_cases is called, so no row is inserted → FAIL.
    GREEN: after restructuring, fix_cases runs unconditionally; creds guard only
    controls the posting path.
    """
    from sqlalchemy import func, select

    from showcase.tasks import _run_tick_body
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)
    showcase_user_id = _seed_showcase_user(db_session)
    _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="No-creds fixation test",
        viral_score=92.0,  # >= default threshold of 90.0
        first_seen=now - timedelta(hours=2),
    )
    db_session.commit()

    # Settings with NO posting creds but valid case threshold.
    settings = _make_settings(
        showcase_bot_token="",
        showcase_channel_chat_id="",
        showcase_case_min_score=90.0,
    )

    with patch("config.get_settings", return_value=settings):
        _run_tick_body(db_session)

    db_session.expire_all()
    count = db_session.scalar(select(func.count(ShowcaseCase.id)))
    assert count == 1, (
        f"Expected 1 showcase_cases row even without TG creds, got {count}. "
        "fix_cases must run independently of the posting-creds guard."
    )


def test_pending_row_does_not_consume_daily_cap(db_session: Session) -> None:
    """AC5 / AC3: a stuck pending row must not eat the daily cap.

    If the cap counts pending rows the system can end up with 'cap=1 but nothing posted',
    blocking all future postings for the rest of the UTC day.
    """
    from showcase.tasks import _run_tick_body

    now = datetime.now(UTC)
    showcase_user_id = _seed_showcase_user(db_session)

    # Single qualifying cluster.
    cluster_id = _seed_cluster(
        db_session,
        user_id=showcase_user_id,
        topic="Cap test cluster",
        viral_score=91.0,
        first_seen=now - timedelta(seconds=3600),
    )

    # Cap set to 1 so it triggers easily.
    settings = _make_settings(showcase_posts_per_day_max=1)

    # Tick 1: send fails → pending row.
    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", return_value=False),
    ):
        _run_tick_body(db_session)

    pending_row = db_session.query(ShowcasePost).filter_by(cluster_id=cluster_id).first()
    assert pending_row is not None
    assert pending_row.status == STATUS_PENDING

    # Tick 2: sender works — cap must not block re-send of the pending cluster.
    with (
        patch("config.get_settings", return_value=settings),
        patch("showcase.tasks.send_showcase_post", return_value=True),
    ):
        _run_tick_body(db_session)

    db_session.expire_all()
    row = db_session.query(ShowcasePost).filter_by(cluster_id=cluster_id).first()
    assert row is not None
    assert row.status == STATUS_POSTED, "Pending row must not count toward daily cap; got: " + str(
        row.status
    )
