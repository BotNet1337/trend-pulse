"""Integration (G2) — scorer tick into alert rows (AC3-AC6).

Seeds a user + watchlists + clusters + recent posts in a live Postgres, runs the
scorer tick body (`scorer.score_recent_clusters`), and asserts:

- AC3 below-threshold topic-match → NO alert,
- AC4 above-threshold topic-match → exactly ONE alert (correct fields),
- AC5 above-threshold topic-MISMATCH → NO alert,
- AC6 re-running the tick is idempotent → still exactly ONE alert.

`score_recent_clusters` opens its own `storage.get_session()` against the SAME test
DB the `db_session` fixture binds to (mirrors `test_run_batch.py`); seed data is
committed so the scorer's sessions see it. The whole module is skipped without a DB.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from storage.models import Alert, Channel, Cluster, Post, User, Watchlist
from storage.models.channels import SourceKind as ChannelSourceKind

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_NOW = datetime.now(UTC)


def _embedding() -> list[float]:
    return [0.1] + [0.0] * (_EMBEDDING_DIM - 1)


def _seed_user(session: Session, email: str) -> User:
    user = User(email=email, hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user


def _seed_channel(session: Session, handle: str) -> Channel:
    channel = Channel(source_kind=ChannelSourceKind.TELEGRAM, handle=handle)
    session.add(channel)
    session.flush()
    return channel


def _seed_cluster(session: Session, *, user_id: int, topic: str) -> Cluster:
    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        embedding=_embedding(),
        first_seen=_NOW,
        updated_at=_NOW,
    )
    session.add(cluster)
    session.flush()
    return cluster


def _seed_post(
    session: Session,
    *,
    user_id: int,
    channel_id: int,
    external_id: str,
    views: int,
    forwards: int,
    reactions: int,
    minutes_ago: int,
) -> None:
    session.add(
        Post(
            user_id=user_id,
            channel_id=channel_id,
            external_id=external_id,
            views=views,
            forwards=forwards,
            reactions=reactions,
            posted_at=_NOW - timedelta(minutes=minutes_ago),
        )
    )


def _alerts_for(session: Session, *, user_id: int, cluster_id: int) -> list[Alert]:
    session.expire_all()
    return (
        session.query(Alert).filter(Alert.user_id == user_id, Alert.cluster_id == cluster_id).all()
    )


def test_above_threshold_topic_match_creates_exactly_one_alert_idempotently(
    db_session: Session,
) -> None:
    from scorer.tasks import score_recent_clusters

    user = _seed_user(db_session, "above@example.com")
    ch1 = _seed_channel(db_session, "@crypto1")
    ch2 = _seed_channel(db_session, "@crypto2")
    # Watch "crypto" across two channels, low threshold so the score clears it.
    db_session.add(Watchlist(user_id=user.id, channel_id=ch1.id, topic="crypto", threshold=0.1))
    db_session.add(Watchlist(user_id=user.id, channel_id=ch2.id, topic="crypto", threshold=0.1))
    cluster = _seed_cluster(db_session, user_id=user.id, topic="crypto")
    # Two channels, healthy engagement, spread over ~30 min → score > 0.1.
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch1.id,
        external_id="a1",
        views=1000,
        forwards=50,
        reactions=200,
        minutes_ago=30,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch2.id,
        external_id="a2",
        views=800,
        forwards=40,
        reactions=150,
        minutes_ago=5,
    )
    db_session.commit()

    created = score_recent_clusters()
    assert created >= 1

    alerts = _alerts_for(db_session, user_id=user.id, cluster_id=cluster.id)
    assert len(alerts) == 1  # AC4 — exactly one
    alert = alerts[0]
    assert alert.user_id == user.id
    assert alert.cluster_id == cluster.id
    assert alert.score > 0.1
    assert alert.channels_count == 2

    # AC6 — a second tick must NOT create a duplicate.
    score_recent_clusters()
    assert len(_alerts_for(db_session, user_id=user.id, cluster_id=cluster.id)) == 1


def test_below_threshold_creates_no_alert(db_session: Session) -> None:
    from scorer.tasks import score_recent_clusters

    user = _seed_user(db_session, "below@example.com")
    ch = _seed_channel(db_session, "@news1")
    # Threshold set far above any achievable score for this single quiet post.
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="news", threshold=10_000.0))
    cluster = _seed_cluster(db_session, user_id=user.id, topic="news")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="b1",
        views=1,
        forwards=0,
        reactions=0,
        minutes_ago=10,
    )
    db_session.commit()

    created = score_recent_clusters()

    assert created == 0  # AC3 — no alert
    assert _alerts_for(db_session, user_id=user.id, cluster_id=cluster.id) == []


def test_topic_mismatch_creates_no_alert(db_session: Session) -> None:
    from scorer.tasks import score_recent_clusters

    user = _seed_user(db_session, "mismatch@example.com")
    ch = _seed_channel(db_session, "@sports1")
    # User watches "sports"; the fresh cluster's topic is "politics" → mismatch.
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="sports", threshold=0.0))
    cluster = _seed_cluster(db_session, user_id=user.id, topic="politics")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="c1",
        views=5000,
        forwards=500,
        reactions=900,
        minutes_ago=15,
    )
    db_session.commit()

    created = score_recent_clusters()

    assert created == 0  # AC5 — topic mismatch, no alert
    assert _alerts_for(db_session, user_id=user.id, cluster_id=cluster.id) == []
