"""Integration (G2) — per-watchlist live signal aggregation (TASK-096).

Seeds a user + watchlist + clusters (matching and non-matching channel) + scores
across timestamps (inside and outside the 24h window) + alerts, then asserts the
aggregation in `storage.repositories.signal_repo.aggregate_for_user`:

- `live_velocity` / `live_score` = the LATEST in-window score's velocity / viral,
- `sparkline_24h` = the correct per-hour max viral_score buckets (oldest→newest),
- `last_alert_at` = the most recent alert's `first_seen`,
- cross-user data and clusters on a NON-matching channel are EXCLUDED,
- a channel with no in-window data is graceful (None / empty).

The join is by CHANNEL OVERLAP (TASK-084), not topic equality: a cluster
contributes to a watchlist's signal iff it has an in-window post on the
watchlist's channel.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from storage.models import Alert, Channel, Cluster, Post, Score, User
from storage.models.channels import SourceKind as ChannelSourceKind
from storage.repositories.signal_repo import aggregate_for_user

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
    cluster_id: int,
    external_id: str,
    minutes_ago: int,
) -> None:
    session.add(
        Post(
            user_id=user_id,
            channel_id=channel_id,
            external_id=external_id,
            views=100,
            forwards=5,
            reactions=10,
            posted_at=_NOW - timedelta(minutes=minutes_ago),
            cluster_id=cluster_id,
        )
    )


def _seed_score(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    viral_score: float,
    velocity: float,
    minutes_ago: int,
) -> None:
    session.add(
        Score(
            user_id=user_id,
            cluster_id=cluster_id,
            velocity=velocity,
            engagement=0.5,
            cross_channel=0.5,
            channels_count=1,
            viral_score=viral_score,
            computed_at=_NOW - timedelta(minutes=minutes_ago),
        )
    )


def _seed_alert(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    score: float,
    minutes_ago: int,
) -> None:
    session.add(
        Alert(
            user_id=user_id,
            cluster_id=cluster_id,
            score=score,
            channels_count=1,
            first_seen=_NOW - timedelta(minutes=minutes_ago),
        )
    )


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def test_aggregate_for_user_full_signal(db_session: Session) -> None:
    """Latest in-window velocity/score, hourly sparkline buckets, last-alert; with
    cross-user and non-matching-channel data correctly EXCLUDED.

    NB: `scores` is unique per `(user_id, cluster_id)` (upsert), so an hourly
    series comes from DISTINCT clusters at different hours, never multiple score
    rows on one cluster — this mirrors the production data model (Discussion).
    The three time buckets are deliberately placed in three DIFFERENT clock hours.
    """
    user = _seed_user(db_session, "signal@example.com")
    watched_ch = _seed_channel(db_session, "@watched")
    other_ch = _seed_channel(db_session, "@other")

    # Anchor offsets to clock-hour boundaries so the three buckets land in three
    # distinct hours regardless of the current minute-of-hour.
    base = _floor_hour(_NOW)
    # cluster_a at hour H-3 (score 40), cluster_b at hour H-2 (score 55),
    # cluster_c at hour H (latest, score 72), cluster_d ALSO at hour H but lower
    # (30) so the H bucket keeps max=72.
    min_h3 = int((_NOW - (base - timedelta(hours=3))).total_seconds() // 60)
    min_h2 = int((_NOW - (base - timedelta(hours=2))).total_seconds() // 60)

    # Cluster A — oldest in-window bucket (hour H-3).
    cluster_a = _seed_cluster(db_session, user_id=user.id, topic="Story A")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_a.id,
        external_id="pa1",
        minutes_ago=min_h3,
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_a.id,
        viral_score=40.0,
        velocity=0.2,
        minutes_ago=min_h3,
    )

    # Cluster B — middle bucket (hour H-2).
    cluster_b = _seed_cluster(db_session, user_id=user.id, topic="Story B")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_b.id,
        external_id="pb1",
        minutes_ago=min_h2,
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_b.id,
        viral_score=55.0,
        velocity=0.3,
        minutes_ago=min_h2,
    )

    # Cluster C — latest bucket (current hour H), drives live_* and the top sparkline point.
    cluster_c = _seed_cluster(db_session, user_id=user.id, topic="Story C")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_c.id,
        external_id="pc1",
        minutes_ago=2,
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_c.id,
        viral_score=72.0,
        velocity=0.65,
        minutes_ago=2,
    )

    # Cluster D — SAME current hour as C but lower → max-per-hour keeps 72.0.
    cluster_d = _seed_cluster(db_session, user_id=user.id, topic="Story D")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_d.id,
        external_id="pd1",
        minutes_ago=4,
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_d.id,
        viral_score=30.0,
        velocity=0.1,
        minutes_ago=4,
    )

    # Cluster OUTSIDE the 24h window — must be excluded entirely.
    cluster_old = _seed_cluster(db_session, user_id=user.id, topic="Old story")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_old.id,
        external_id="pold",
        minutes_ago=48 * 60,  # 2 days ago
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_old.id,
        viral_score=99.0,
        velocity=0.99,
        minutes_ago=48 * 60,
    )

    # Cluster on the NON-matching channel — must be excluded from @watched's signal.
    cluster_other = _seed_cluster(db_session, user_id=user.id, topic="Off-channel")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=other_ch.id,
        cluster_id=cluster_other.id,
        external_id="poth",
        minutes_ago=15,
    )
    _seed_score(
        db_session,
        user_id=user.id,
        cluster_id=cluster_other.id,
        viral_score=88.0,
        velocity=0.88,
        minutes_ago=15,
    )

    # Cross-USER data on the watched channel — must never leak.
    other_user = _seed_user(db_session, "intruder@example.com")
    cluster_x = _seed_cluster(db_session, user_id=other_user.id, topic="Tenant X")
    _seed_post(
        db_session,
        user_id=other_user.id,
        channel_id=watched_ch.id,
        cluster_id=cluster_x.id,
        external_id="px1",
        minutes_ago=5,
    )
    _seed_score(
        db_session,
        user_id=other_user.id,
        cluster_id=cluster_x.id,
        viral_score=95.0,
        velocity=0.95,
        minutes_ago=5,
    )
    _seed_alert(
        db_session,
        user_id=other_user.id,
        cluster_id=cluster_x.id,
        score=95.0,
        minutes_ago=5,
    )

    # Alerts for our user: most recent is 30 min ago (on cluster_b).
    _seed_alert(db_session, user_id=user.id, cluster_id=cluster_a.id, score=72.0, minutes_ago=120)
    _seed_alert(db_session, user_id=user.id, cluster_id=cluster_b.id, score=60.0, minutes_ago=30)
    db_session.commit()

    signals = aggregate_for_user(
        db_session, user_id=user.id, channel_ids=[watched_ch.id, other_ch.id]
    )

    sig = signals[watched_ch.id]
    # Latest in-window score (cluster_c, 2 min ago) drives live velocity + score —
    # NOT the out-of-window 99.0 / 0.99, NOT the cross-user 95.0 / 0.95.
    assert sig.live_score == 72.0
    assert sig.live_velocity == 0.65
    # Sparkline: max viral_score per hour bucket, oldest→newest. Three in-window
    # hours hold {H-3: 40.0, H-2: 55.0, H: max(72.0, 30.0)=72.0}, excluding the
    # 99.0 out-of-window point and the cross-user / off-channel points.
    assert sig.sparkline_24h == (40.0, 55.0, 72.0)
    # The most recent alert for OUR user is 30 min ago (cluster_b), not 120 (cluster_a),
    # and not the cross-user alert.
    expected_last = _NOW - timedelta(minutes=30)
    assert sig.last_alert_at is not None
    assert abs((sig.last_alert_at - expected_last).total_seconds()) < 1.0

    # The non-matching channel sees ONLY its own cluster's signal (88.0 / 0.88),
    # never @watched's data.
    sig_other = signals[other_ch.id]
    assert sig_other.live_score == 88.0
    assert sig_other.live_velocity == 0.88
    assert sig_other.last_alert_at is None  # no alert on cluster_other


def test_aggregate_for_user_graceful_empty(db_session: Session) -> None:
    """A watched channel with NO in-window posts/scores/alerts → graceful empty."""
    user = _seed_user(db_session, "empty@example.com")
    ch = _seed_channel(db_session, "@quiet")
    db_session.commit()

    signals = aggregate_for_user(db_session, user_id=user.id, channel_ids=[ch.id])

    sig = signals[ch.id]
    assert sig.live_velocity is None
    assert sig.live_score is None
    assert sig.sparkline_24h == ()
    assert sig.last_alert_at is None


def test_aggregate_for_user_no_channels_returns_empty(db_session: Session) -> None:
    """No channels requested → empty mapping (no queries needed)."""
    user = _seed_user(db_session, "nochan@example.com")
    db_session.commit()
    assert aggregate_for_user(db_session, user_id=user.id, channel_ids=[]) == {}
