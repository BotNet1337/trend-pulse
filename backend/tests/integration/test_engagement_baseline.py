"""Integration tests - historical engagement baseline (TASK-041, AC1-AC4).

Seeds posts with controlled `posted_at` timestamps in a live Postgres, then
calls `_build_score_inputs` directly to verify the historical channel_avg
COMPUTATION without running a full scorer tick.

NOTE (scoring v2): the `channel_avg` 7d baseline is still computed here and carried
on `ScoreInputs` (these tests still assert it is correct), but the viral score no
longer DIVIDES engagement by it — the real-data eval (eval_offline/) showed absolute
log-engagement predicts virality better than per-channel normalization (ROC-AUC 0.91
vs 0.86; 0.83 vs 0.62 on single-channel early movers). So `_engagement` is now
`min(log1p(weighted_sum)/LOG_ENGAGEMENT_SCALE, 1)` — bounded and independent of
channel_avg. The AC1/AC2 assertions below were updated from the old ratio semantics
(≈1.0 flat / ≈10 spike) to the v2 bounded-absolute semantics; the channel_avg
computation they exercise is unchanged.

AC1 — flat channel: 7d-history ≈ X computed correctly; engagement = bounded log(X).
AC2 — spike: 7d-history ≈ X; a 10X cluster post yields strictly higher engagement.
AC3 — cold channel (< min_posts in window): fallback to batch-avg +
       log_event("baseline_fallback").
AC4 — window slides: posts older than the window do NOT affect baseline.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from config import get_settings
from storage.models import Channel, Cluster, Post, User, Watchlist
from storage.models.channels import SourceKind as ChannelSourceKind

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_NOW = datetime.now(UTC)

# Anchor window/min_posts to the real Settings so test boundaries (6d inside /
# 10d outside, min_posts seeding) never desync from production defaults.
_WINDOW_SECONDS = get_settings().engagement_baseline_window_seconds
_MIN_POSTS = get_settings().engagement_baseline_min_posts


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
    posted_at: datetime,
    cluster_id: int | None = None,
) -> Post:
    post = Post(
        user_id=user_id,
        channel_id=channel_id,
        external_id=external_id,
        views=views,
        forwards=forwards,
        reactions=reactions,
        posted_at=posted_at,
        cluster_id=cluster_id,
    )
    session.add(post)
    session.flush()
    return post


def _numerator(views: int, forwards: int, reactions: int) -> float:
    """Weighted engagement numerator matching score.py formula."""
    from scorer.score import FORWARD_FACTOR, REACTION_FACTOR

    return views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR


def test_ac1_flat_channel_engagement_approx_one(db_session: Session) -> None:
    """AC1: 7-day history ≈ X, new post ≈ X → channel_avg ≈ numerator → engagement ≈ 1.

    Seeds MIN_POSTS historical posts with identical metrics inside the window,
    then creates a cluster post with the same metrics. The historical avg equals
    the cluster numerator, so engagement should be ≈1.0.
    """
    from scorer.score import FORWARD_FACTOR, REACTION_FACTOR
    from scorer.tasks import _build_score_inputs

    user = _seed_user(db_session, "ac1@example.com")
    ch = _seed_channel(db_session, "@flat1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="tech", threshold=0.0))

    # Seed _MIN_POSTS historical posts evenly inside the window (3-day-old posts).
    base_views, base_fwd, base_rxn = 1000, 20, 50
    days_ago_3 = _NOW - timedelta(days=3)
    for i in range(_MIN_POSTS):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"ac1_hist_{i}",
            views=base_views,
            forwards=base_fwd,
            reactions=base_rxn,
            posted_at=days_ago_3 - timedelta(hours=i),
            cluster_id=None,  # history posts — not in the cluster
        )

    # The new cluster post has the same metrics as the historical average.
    cluster = _seed_cluster(db_session, user_id=user.id, topic="tech")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="ac1_new",
        views=base_views,
        forwards=base_fwd,
        reactions=base_rxn,
        posted_at=_NOW - timedelta(minutes=5),
        cluster_id=cluster.id,
    )
    db_session.commit()

    inputs = _build_score_inputs(
        db_session,
        user_id=user.id,
        cluster_id=cluster.id,
        watched_channels_count=1,
    )

    # Expected numerator = avg of history = same as new post numerator
    expected_avg = float(base_views + base_fwd * FORWARD_FACTOR + base_rxn * REACTION_FACTOR)
    assert inputs.channel_avg == pytest.approx(expected_avg, rel=0.01), (
        f"channel_avg {inputs.channel_avg} should ≈ historical avg {expected_avg}"
    )
    # v2: engagement is the bounded log of the weighted sum, independent of channel_avg.
    import math

    from scorer.score import LOG_ENGAGEMENT_SCALE, _engagement

    engagement = _engagement(
        views=inputs.views,
        forwards=inputs.forwards,
        reactions=inputs.reactions,
    )
    weighted = inputs.views + inputs.forwards * FORWARD_FACTOR + inputs.reactions * REACTION_FACTOR
    assert engagement == pytest.approx(min(math.log1p(weighted) / LOG_ENGAGEMENT_SCALE, 1.0))
    assert 0.0 <= engagement <= 1.0


def test_ac2_spike_detected_engagement_approx_ten(db_session: Session) -> None:
    """AC2: history ≈ X, cluster post ≈ 10X → engagement ≈ 10.

    Seeds MIN_POSTS historical posts with base metrics, then a cluster post
    with 10x the metrics. The ratio should be ≈10.
    """
    from scorer.tasks import _build_score_inputs

    user = _seed_user(db_session, "ac2@example.com")
    ch = _seed_channel(db_session, "@spike1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="news", threshold=0.0))

    base_views, base_fwd, base_rxn = 500, 10, 20
    days_ago_3 = _NOW - timedelta(days=3)
    for i in range(_MIN_POSTS):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"ac2_hist_{i}",
            views=base_views,
            forwards=base_fwd,
            reactions=base_rxn,
            posted_at=days_ago_3 - timedelta(hours=i),
            cluster_id=None,
        )

    # Spike post: 10x the base metrics.
    cluster = _seed_cluster(db_session, user_id=user.id, topic="news")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="ac2_new",
        views=base_views * 10,
        forwards=base_fwd * 10,
        reactions=base_rxn * 10,
        posted_at=_NOW - timedelta(minutes=5),
        cluster_id=cluster.id,
    )
    db_session.commit()

    inputs = _build_score_inputs(
        db_session,
        user_id=user.id,
        cluster_id=cluster.id,
        watched_channels_count=1,
    )

    from scorer.score import _engagement

    engagement = _engagement(
        views=inputs.views,
        forwards=inputs.forwards,
        reactions=inputs.reactions,
    )
    # v2: a 10x spike yields strictly HIGHER (bounded) engagement than the flat baseline
    # — absolute magnitude, not a ratio. channel_avg is computed but no longer divides it.
    flat = _engagement(views=base_views, forwards=base_fwd, reactions=base_rxn)
    assert engagement > flat
    assert 0.0 <= engagement <= 1.0


def test_ac3_cold_channel_falls_back_to_batch_avg_and_logs(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """AC3: < min_posts history → fallback to batch-avg + log_event("baseline_fallback").

    Seeds fewer than min_posts historical posts, then checks that channel_avg
    equals the batch-avg of the cluster posts (old behaviour), and that the
    baseline_fallback event was logged.
    """
    import logging

    from scorer.tasks import _build_score_inputs

    user = _seed_user(db_session, "ac3@example.com")
    ch = _seed_channel(db_session, "@cold1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="crypto", threshold=0.0))

    # Seed only 2 historical posts (< min_posts=10).
    days_ago_2 = _NOW - timedelta(days=2)
    for i in range(2):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"ac3_hist_{i}",
            views=300,
            forwards=5,
            reactions=10,
            posted_at=days_ago_2 - timedelta(hours=i),
            cluster_id=None,
        )

    # Two cluster posts; batch-avg should be their average numerator.
    cluster = _seed_cluster(db_session, user_id=user.id, topic="crypto")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="ac3_p1",
        views=800,
        forwards=20,
        reactions=40,
        posted_at=_NOW - timedelta(minutes=10),
        cluster_id=cluster.id,
    )
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="ac3_p2",
        views=1200,
        forwards=30,
        reactions=60,
        posted_at=_NOW - timedelta(minutes=5),
        cluster_id=cluster.id,
    )
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="trendpulse"):
        inputs = _build_score_inputs(
            db_session,
            user_id=user.id,
            cluster_id=cluster.id,
            watched_channels_count=1,
        )

    # Batch-avg fallback: old behaviour = sum(views) / len(posts) for the cluster.
    # The fallback uses batch views avg (legacy behaviour).
    total_views = 800 + 1200
    batch_views_avg = total_views / 2
    assert inputs.channel_avg == pytest.approx(batch_views_avg, rel=0.01), (
        f"Cold channel should fall back to batch views avg {batch_views_avg}, "
        f"got {inputs.channel_avg}"
    )
    # The baseline_fallback event must have been logged.
    assert any("baseline_fallback" in record.message for record in caplog.records), (
        "Expected log_event('baseline_fallback') for cold channel, not found in caplog"
    )


def test_ac4_posts_outside_window_do_not_affect_baseline(db_session: Session) -> None:
    """AC4: posts older than the window do NOT influence the historical average.

    Seeds two sets of history posts:
    - 5 posts at 6 days ago (INSIDE 7-day window) with low metrics.
    - 5 posts at 10 days ago (OUTSIDE 7-day window) with very high metrics.
    + 5 more posts inside window to reach min_posts.

    If old posts were included the avg would be inflated; with correct windowing
    only the inside-window posts contribute.
    """
    from scorer.score import FORWARD_FACTOR, REACTION_FACTOR
    from scorer.tasks import _build_score_inputs

    user = _seed_user(db_session, "ac4@example.com")
    ch = _seed_channel(db_session, "@window1")
    db_session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="finance", threshold=0.0))

    # Inside-window posts (6 days ago): 10 posts with low metrics.
    inside_views, inside_fwd, inside_rxn = 100, 2, 5
    six_days_ago = _NOW - timedelta(days=6)
    for i in range(_MIN_POSTS):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"ac4_in_{i}",
            views=inside_views,
            forwards=inside_fwd,
            reactions=inside_rxn,
            posted_at=six_days_ago - timedelta(hours=i),
            cluster_id=None,
        )

    # Outside-window posts (10 days ago): very high metrics — must be ignored.
    outside_views, outside_fwd, outside_rxn = 100_000, 5_000, 10_000
    ten_days_ago = _NOW - timedelta(days=10)
    for i in range(5):
        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=ch.id,
            external_id=f"ac4_out_{i}",
            views=outside_views,
            forwards=outside_fwd,
            reactions=outside_rxn,
            posted_at=ten_days_ago - timedelta(hours=i),
            cluster_id=None,
        )

    # Cluster post with metrics matching inside-window avg → engagement ≈ 1.0
    cluster = _seed_cluster(db_session, user_id=user.id, topic="finance")
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=ch.id,
        external_id="ac4_new",
        views=inside_views,
        forwards=inside_fwd,
        reactions=inside_rxn,
        posted_at=_NOW - timedelta(minutes=5),
        cluster_id=cluster.id,
    )
    db_session.commit()

    inputs = _build_score_inputs(
        db_session,
        user_id=user.id,
        cluster_id=cluster.id,
        watched_channels_count=1,
    )

    # channel_avg should reflect only inside-window posts.
    expected_avg = float(inside_views + inside_fwd * FORWARD_FACTOR + inside_rxn * REACTION_FACTOR)
    assert inputs.channel_avg == pytest.approx(expected_avg, rel=0.01), (
        f"channel_avg {inputs.channel_avg} should match inside-window avg {expected_avg}; "
        "outside-window posts must not contribute"
    )

    from scorer.score import _engagement

    # The window-slide invariant is asserted directly on channel_avg above; engagement
    # is v2-bounded (independent of channel_avg) and only sanity-checked here.
    engagement = _engagement(
        views=inputs.views,
        forwards=inputs.forwards,
        reactions=inputs.reactions,
    )
    assert 0.0 <= engagement <= 1.0
