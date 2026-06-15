"""Integration (G2) — forward feature-snapshot capture (TASK-109, B1).

Seeds a user + watchlist + cluster (controlled `first_seen`) + posts in a live
Postgres, runs the scorer tick body (`scorer.score_recent_clusters`), and asserts the
`cluster_feature_snapshots` rows are captured for exactly the crossed observation
windows, idempotently, and scoped per user. `score_recent_clusters` opens its own
`storage.get_session()` against the SAME test DB the `db_session` fixture binds to;
seed data is committed so the scorer's sessions see it. Skipped without a DB.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from scorer.tasks import score_recent_clusters
from storage.models import Channel, Cluster, ClusterFeatureSnapshot, Post, User, Watchlist
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


def _seed_watchlist(session: Session, *, user_id: int, topic: str, channel_id: int) -> None:
    # A watchlist is required so `_score_user` does not early-return; capture is
    # independent of topic-match, but the user must have at least one watchlist for
    # the scorer to iterate their clusters.
    session.add(
        Watchlist(
            user_id=user_id,
            topic=topic,
            channel_id=channel_id,
            threshold=0.0,
        )
    )
    session.flush()


def _seed_cluster(
    session: Session,
    *,
    user_id: int,
    topic: str,
    first_seen_minutes_ago: int,
    updated_minutes_ago: int = 0,
) -> Cluster:
    first_seen = _NOW - timedelta(minutes=first_seen_minutes_ago)
    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        embedding=_embedding(),
        first_seen=first_seen,
        # default: fresh by updated_at so the scorer scores it this tick. Override to
        # simulate a cluster that has gone quiet (aged out of the freshness window).
        updated_at=_NOW - timedelta(minutes=updated_minutes_ago),
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
    cluster_id: int,
    minutes_ago: int,
    views: int = 100,
    forwards: int = 2,
    reactions: int = 5,
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
            cluster_id=cluster_id,
        )
    )


def _snapshots_for(
    session: Session, *, user_id: int, cluster_id: int
) -> list[ClusterFeatureSnapshot]:
    session.expire_all()
    return (
        session.query(ClusterFeatureSnapshot)
        .filter(
            ClusterFeatureSnapshot.user_id == user_id,
            ClusterFeatureSnapshot.cluster_id == cluster_id,
        )
        .all()
    )


def test_captures_only_crossed_windows(db_session: Session) -> None:
    user = _seed_user(db_session, "snap16@example.com")
    channel = _seed_channel(db_session, "@snap16")
    _seed_watchlist(db_session, user_id=user.id, topic="crypto", channel_id=channel.id)
    cluster = _seed_cluster(db_session, user_id=user.id, topic="story", first_seen_minutes_ago=16)
    # two channels reached, posts since first_seen
    other = _seed_channel(db_session, "@snap16b")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        external_id="p1",
        cluster_id=cluster.id,
        minutes_ago=15,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=other.id,
        external_id="p2",
        cluster_id=cluster.id,
        minutes_ago=10,
    )
    db_session.commit()

    score_recent_clusters()

    snaps = _snapshots_for(db_session, user_id=user.id, cluster_id=cluster.id)
    labels = {s.window_label for s in snaps}
    assert labels == {"15m"}  # 16 min old → only the 15m window crossed
    snap = snaps[0]
    assert snap.post_count == 2
    assert snap.views == 200
    assert snap.distinct_channels == 2
    assert snap.age_seconds >= 15 * 60


def test_backfills_all_crossed_windows_and_is_idempotent(db_session: Session) -> None:
    user = _seed_user(db_session, "snap65@example.com")
    channel = _seed_channel(db_session, "@snap65")
    _seed_watchlist(db_session, user_id=user.id, topic="crypto", channel_id=channel.id)
    cluster = _seed_cluster(db_session, user_id=user.id, topic="story", first_seen_minutes_ago=65)
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        external_id="q1",
        cluster_id=cluster.id,
        minutes_ago=60,
    )
    db_session.commit()

    score_recent_clusters()
    score_recent_clusters()  # re-run → must NOT duplicate

    snaps = _snapshots_for(db_session, user_id=user.id, cluster_id=cluster.id)
    labels = sorted(s.window_label for s in snaps)
    assert labels == ["15m", "1h", "30m"]  # all three crossed, one each (idempotent)


def test_young_cluster_gets_no_snapshot(db_session: Session) -> None:
    user = _seed_user(db_session, "snapyoung@example.com")
    channel = _seed_channel(db_session, "@snapyoung")
    _seed_watchlist(db_session, user_id=user.id, topic="crypto", channel_id=channel.id)
    cluster = _seed_cluster(db_session, user_id=user.id, topic="story", first_seen_minutes_ago=5)
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        external_id="y1",
        cluster_id=cluster.id,
        minutes_ago=4,
    )
    db_session.commit()

    score_recent_clusters()

    assert _snapshots_for(db_session, user_id=user.id, cluster_id=cluster.id) == []


def test_stale_cluster_aged_out_of_freshness_window_is_not_snapshotted(
    db_session: Session,
) -> None:
    """KNOWN LIMITATION (documented): capture is coupled to scoring freshness. A cluster
    that has gone quiet (updated_at older than scorer_recent_window_seconds, default 1h)
    is not iterated by the scorer, so its windows are not captured — even though it is
    old enough to have crossed them. This makes the explicit freshness boundary a test."""
    user = _seed_user(db_session, "snapstale@example.com")
    channel = _seed_channel(db_session, "@snapstale")
    _seed_watchlist(db_session, user_id=user.id, topic="crypto", channel_id=channel.id)
    # old enough for all windows, but updated_at is 2h ago → outside the 1h freshness window
    cluster = _seed_cluster(
        db_session,
        user_id=user.id,
        topic="story",
        first_seen_minutes_ago=120,
        updated_minutes_ago=120,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        external_id="st1",
        cluster_id=cluster.id,
        minutes_ago=119,
    )
    db_session.commit()

    score_recent_clusters()

    assert _snapshots_for(db_session, user_id=user.id, cluster_id=cluster.id) == []


def test_per_user_isolation(db_session: Session) -> None:
    user_a = _seed_user(db_session, "snapA@example.com")
    user_b = _seed_user(db_session, "snapB@example.com")
    ch_a = _seed_channel(db_session, "@snapA")
    ch_b = _seed_channel(db_session, "@snapB")
    _seed_watchlist(db_session, user_id=user_a.id, topic="crypto", channel_id=ch_a.id)
    _seed_watchlist(db_session, user_id=user_b.id, topic="crypto", channel_id=ch_b.id)
    cl_a = _seed_cluster(db_session, user_id=user_a.id, topic="s", first_seen_minutes_ago=20)
    cl_b = _seed_cluster(db_session, user_id=user_b.id, topic="s", first_seen_minutes_ago=20)
    _seed_post(
        db_session,
        user_id=user_a.id,
        channel_id=ch_a.id,
        external_id="a1",
        cluster_id=cl_a.id,
        minutes_ago=18,
    )
    _seed_post(
        db_session,
        user_id=user_b.id,
        channel_id=ch_b.id,
        external_id="b1",
        cluster_id=cl_b.id,
        minutes_ago=18,
    )
    db_session.commit()

    score_recent_clusters()

    snaps_a = _snapshots_for(db_session, user_id=user_a.id, cluster_id=cl_a.id)
    snaps_b = _snapshots_for(db_session, user_id=user_b.id, cluster_id=cl_b.id)
    assert {s.window_label for s in snaps_a} == {"15m"}
    assert {s.window_label for s in snaps_b} == {"15m"}
    # no cross-user rows
    assert all(s.user_id == user_a.id for s in snaps_a)
    assert all(s.user_id == user_b.id for s in snaps_b)
