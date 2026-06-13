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
    cluster_id: int | None = None,
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
        cluster_id=cluster.id,
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
        cluster_id=cluster.id,
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
        cluster_id=cluster.id,
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
        cluster_id=cluster.id,
    )
    db_session.commit()

    created = score_recent_clusters()

    assert created == 0  # AC5 — topic mismatch, no alert
    assert _alerts_for(db_session, user_id=user.id, cluster_id=cluster.id) == []


def test_per_cluster_engagement_not_per_topic(db_session: Session) -> None:
    """AC1 anchor: per-cluster scoring distinguishes high vs low engagement clusters.

    One user watches "crypto" on two channels (low threshold).
    Two clusters for the same topic: clusterA has HIGH engagement posts,
    clusterB has LOW engagement posts on the same channels.
    Per-cluster scoring → different viral_score.
    Per-topic scoring (current) → both clusters share the same aggregated inputs
    → viral_score will be EQUAL → this test FAILS (RED).
    """
    from scorer.tasks import score_recent_clusters
    from storage.models import Score

    user = _seed_user(db_session, "percl@example.com")
    ch1 = _seed_channel(db_session, "@percl1")
    ch2 = _seed_channel(db_session, "@percl2")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch1.id, topic="crypto", threshold=0.0))
    db_session.add(Watchlist(user_id=user.id, channel_id=ch2.id, topic="crypto", threshold=0.0))

    cluster_a = _seed_cluster(db_session, user_id=user.id, topic="crypto")
    cluster_b = _seed_cluster(db_session, user_id=user.id, topic="crypto")

    # clusterA — HIGH engagement
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch1.id,
        external_id="pa1",
        views=50000,
        forwards=2000,
        reactions=5000,
        minutes_ago=30,
        cluster_id=cluster_a.id,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch2.id,
        external_id="pa2",
        views=40000,
        forwards=1500,
        reactions=4000,
        minutes_ago=5,
        cluster_id=cluster_a.id,
    )

    # clusterB — LOW engagement on the SAME channels
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch1.id,
        external_id="pb1",
        views=10,
        forwards=0,
        reactions=1,
        minutes_ago=28,
        cluster_id=cluster_b.id,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch2.id,
        external_id="pb2",
        views=5,
        forwards=0,
        reactions=0,
        minutes_ago=3,
        cluster_id=cluster_b.id,
    )
    db_session.commit()

    score_recent_clusters()

    db_session.expire_all()
    score_a = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster_a.id)
        .first()
    )
    score_b = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster_b.id)
        .first()
    )

    assert score_a is not None, "Score for clusterA must exist"
    assert score_b is not None, "Score for clusterB must exist"
    # Per-cluster: high-engagement cluster must score strictly higher.
    assert score_a.viral_score > score_b.viral_score, (
        f"Expected clusterA viral_score ({score_a.viral_score}) > "
        f"clusterB viral_score ({score_b.viral_score}), got equal (per-topic bug)"
    )


def test_persist_score_upsert_no_growth(db_session: Session) -> None:
    """AC3: repeated scorer ticks for same (user_id, cluster_id) → exactly 1 Score row.

    Current code inserts a new Score row each tick → this test FAILS (RED).
    After upsert implementation → GREEN.
    """
    from sqlalchemy import func

    from scorer.tasks import score_recent_clusters
    from storage.models import Score

    user = _seed_user(db_session, "upsert@example.com")
    ch = _seed_channel(db_session, "@upsert1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="tech", threshold=0.0))
    cluster = _seed_cluster(db_session, user_id=user.id, topic="tech")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="u1",
        views=100,
        forwards=5,
        reactions=10,
        minutes_ago=15,
        cluster_id=cluster.id,
    )
    db_session.commit()

    # Run scorer twice.
    score_recent_clusters()
    score_recent_clusters()

    db_session.expire_all()
    count = (
        db_session.query(func.count(Score.id))
        .filter(Score.user_id == user.id, Score.cluster_id == cluster.id)
        .scalar()
    )
    assert count == 1, (
        f"Expected 1 Score row after two ticks (upsert), got {count} (insert-each-tick bug)"
    )


def test_persist_score_channels_count_real_and_upsert_updates(db_session: Session) -> None:
    """TASK-066 AC1: scores.channels_count carries the real unique-channel count.

    Given a cluster with posts from 3 distinct channels, a scorer tick persists
    channels_count == 3 in the Score row. After a post from a 4th channel joins
    the cluster, the next tick's upsert updates the same row to 4.
    """
    from scorer.tasks import score_recent_clusters
    from storage.models import Score

    user = _seed_user(db_session, "chcount@example.com")
    channels = [_seed_channel(db_session, f"@chcount{i}") for i in range(4)]
    for ch in channels:
        db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="crypto", threshold=0.0))
    cluster = _seed_cluster(db_session, user_id=user.id, topic="crypto")
    # Posts from 3 distinct channels.
    for i, ch in enumerate(channels[:3]):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"cc{i}",
            views=1000,
            forwards=50,
            reactions=100,
            minutes_ago=30 - i * 5,
            cluster_id=cluster.id,
        )
    db_session.commit()

    score_recent_clusters()

    db_session.expire_all()
    row = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster.id)
        .one()
    )
    assert row.channels_count == 3, (
        f"Expected channels_count == 3 (real unique channels), got {row.channels_count}"
    )

    # A 4th channel joins the cluster → upsert must update the counter in place.
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channels[3].id,
        external_id="cc3",
        views=500,
        forwards=20,
        reactions=40,
        minutes_ago=2,
        cluster_id=cluster.id,
    )
    db_session.commit()

    score_recent_clusters()

    db_session.expire_all()
    row = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster.id)
        .one()
    )
    assert row.channels_count == 4, (
        f"Expected upsert to update channels_count to 4, got {row.channels_count}"
    )


def test_score_window_excludes_old_posts(db_session: Session) -> None:
    """TASK-079: score inputs come ONLY from posts inside score_window_seconds.

    A cluster accrues posts across days; an OLD high-engagement post far outside
    the score window must NOT inflate the cluster's score, and stale `posted_at`
    on an old post must NOT widen `delta_hours` (collapsing velocity).

    Two identical clusters with the SAME recent burst:
      - clusterA: only the recent burst (2 posts ~30 min apart).
      - clusterB: the same recent burst PLUS one massive post ~3 days ago.
    With unbounded lifetime aggregation (the OLD behaviour) clusterB's huge old
    post inflates views/reactions AND stretches delta_hours over 3 days → its
    score diverges from clusterA. With a bounded window both clusters see only
    the recent burst → IDENTICAL score. This test asserts equality, so it FAILS
    (RED) on the unbounded code and passes (GREEN) once the window is applied.
    """
    from scorer.tasks import score_recent_clusters
    from storage.models import Score

    user = _seed_user(db_session, "scwin@example.com")
    ch1 = _seed_channel(db_session, "@scwin1")
    ch2 = _seed_channel(db_session, "@scwin2")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch1.id, topic="crypto", threshold=0.0))
    db_session.add(Watchlist(user_id=user.id, channel_id=ch2.id, topic="crypto", threshold=0.0))

    cluster_a = _seed_cluster(db_session, user_id=user.id, topic="crypto")
    cluster_b = _seed_cluster(db_session, user_id=user.id, topic="crypto")

    # The SAME recent burst for both clusters (inside the 24h window).
    for cl, prefix in ((cluster_a, "a"), (cluster_b, "b")):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch1.id,
            external_id=f"scwin-{prefix}1",
            views=1000,
            forwards=50,
            reactions=100,
            minutes_ago=40,
            cluster_id=cl.id,
        )
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch2.id,
            external_id=f"scwin-{prefix}2",
            views=900,
            forwards=40,
            reactions=90,
            minutes_ago=10,
            cluster_id=cl.id,
        )

    # clusterB ALSO carries a massive OLD post ~3 days ago — outside the 24h window.
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch1.id,
        external_id="scwin-b-old",
        views=10_000_000,
        forwards=500_000,
        reactions=2_000_000,
        minutes_ago=3 * 24 * 60,  # 3 days ago
        cluster_id=cluster_b.id,
    )
    db_session.commit()

    score_recent_clusters()

    db_session.expire_all()
    score_a = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster_a.id)
        .one()
    )
    score_b = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster_b.id)
        .one()
    )
    # The old post is out-of-window, so it must not affect ANY component.
    assert score_b.viral_score == pytest.approx(score_a.viral_score), (
        f"Out-of-window post leaked into the score: clusterB ({score_b.viral_score}) "
        f"!= clusterA ({score_a.viral_score}) — lifetime aggregation bug"
    )
    assert score_b.channels_count == score_a.channels_count == 2, (
        "Out-of-window post must not change the unique-channel count"
    )


def test_score_window_empty_skips_cleanly(db_session: Session) -> None:
    """TASK-079 edge case: a fresh cluster with NO posts inside the score window.

    The cluster is still "fresh" (updated_at within scorer_recent_window) but every
    one of its posts is older than score_window_seconds. The scorer must SKIP it
    cleanly: no Score row, no Alert, no ZeroDivision / 0-score pollution.
    """
    from scorer.tasks import score_recent_clusters
    from storage.models import Score

    user = _seed_user(db_session, "scempty@example.com")
    ch = _seed_channel(db_session, "@scempty1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="tech", threshold=0.0))
    # Cluster is fresh (updated_at = _NOW) but its only post is ~2 days old.
    cluster = _seed_cluster(db_session, user_id=user.id, topic="tech")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="scempty-old",
        views=100_000,
        forwards=5_000,
        reactions=10_000,
        minutes_ago=2 * 24 * 60,  # 2 days ago — outside the 24h window
        cluster_id=cluster.id,
    )
    db_session.commit()

    score_recent_clusters()

    db_session.expire_all()
    score = (
        db_session.query(Score)
        .filter(Score.user_id == user.id, Score.cluster_id == cluster.id)
        .first()
    )
    assert score is None, (
        "A cluster with no posts inside the score window must not emit a Score row"
    )
    alerts = _alerts_for(db_session, user_id=user.id, cluster_id=cluster.id)
    assert alerts == [], "Empty-window cluster must not create an alert"
