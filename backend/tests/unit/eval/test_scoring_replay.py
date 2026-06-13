"""Unit tests for eval.scoring_replay (TASK-081).

These assert that the replay (a) reuses the REAL scorer formula (a known input
produces the exact `compute_components` output) and (b) applies the production
rolling-window + skip-empty rules from `scorer.tasks._build_score_inputs`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eval.corpus import ClusterRecord, PostRecord
from eval.scoring_replay import (
    lead_time_proxy_hours,
    replay_scores,
)
from scorer.score import ScoreInputs, compute_components

_ANCHOR = datetime(2026, 6, 12, 18, 0, 0, tzinfo=UTC)


def _post(
    pid: int, cluster_id: int | None, *, channel_id: int, when: datetime, views: int = 100
) -> PostRecord:
    return PostRecord(
        id=pid,
        posted_at=when,
        channel_id=channel_id,
        user_id=10,
        cluster_id=cluster_id,
        views=views,
        forwards=0,
        reactions=0,
    )


def _cluster(cid: int, *, updated_at: datetime = _ANCHOR) -> ClusterRecord:
    return ClusterRecord(
        id=cid,
        user_id=10,
        first_seen=updated_at,
        updated_at=updated_at,
        topic=f"topic-{cid}",
        centroid=(0.0,),
    )


@pytest.mark.unit
def test_replay_matches_real_compute_components() -> None:
    # Two channels, two posts inside the window → reconstruct ScoreInputs by hand
    # and assert the replay equals the REAL compute_components on those inputs.
    posts = [
        _post(1, 1, channel_id=4, when=_ANCHOR - timedelta(hours=2), views=200),
        _post(2, 1, channel_id=5, when=_ANCHOR - timedelta(hours=1), views=100),
    ]
    scores = replay_scores(
        [_cluster(1)], posts, score_window_seconds=86_400, watched_channels_count=10
    )
    assert len(scores) == 1
    expected = compute_components(
        ScoreInputs(
            views=300,
            forwards=0,
            reactions=0,
            channel_avg=300 / 2,  # documented fallback: sum(views)/len(posts)
            delta_channel_count=2,
            delta_hours=1.0,  # 2h ago .. 1h ago
            unique_channels_count=2,
            watched_channels_count=10,
        )
    )
    assert scores[0].components == expected
    assert scores[0].posts_in_window == 2


@pytest.mark.unit
def test_replay_excludes_out_of_window_posts() -> None:
    # An ancient post must not leak into the score (TASK-079 rolling window).
    posts = [
        _post(1, 1, channel_id=4, when=_ANCHOR - timedelta(hours=1), views=100),
        _post(2, 1, channel_id=4, when=_ANCHOR - timedelta(days=10), views=999_999),
    ]
    scores = replay_scores(
        [_cluster(1)], posts, score_window_seconds=86_400, watched_channels_count=10
    )
    assert scores[0].posts_in_window == 1
    # engagement reflects only the in-window post (fallback channel_avg == its views)
    assert scores[0].components.engagement == pytest.approx(1.0)


@pytest.mark.unit
def test_replay_skips_cluster_with_no_in_window_posts() -> None:
    posts = [_post(1, 1, channel_id=4, when=_ANCHOR - timedelta(days=10))]
    scores = replay_scores(
        [_cluster(1)], posts, score_window_seconds=86_400, watched_channels_count=10
    )
    assert scores == []  # mirrors production return None → continue


@pytest.mark.unit
def test_replay_ignores_orphan_posts() -> None:
    posts = [_post(1, None, channel_id=4, when=_ANCHOR - timedelta(hours=1))]
    scores = replay_scores(
        [_cluster(1)], posts, score_window_seconds=86_400, watched_channels_count=10
    )
    assert scores == []


@pytest.mark.unit
def test_lead_time_proxy_median_hours() -> None:
    # cluster 1: first .. peak engagement spread 3h; cluster 2: 1h; median = 2h
    posts = [
        _post(1, 1, channel_id=4, when=_ANCHOR, views=10),
        _post(2, 1, channel_id=4, when=_ANCHOR + timedelta(hours=3), views=999),
        _post(3, 2, channel_id=4, when=_ANCHOR, views=10),
        _post(4, 2, channel_id=4, when=_ANCHOR + timedelta(hours=1), views=999),
    ]
    assert lead_time_proxy_hours(posts) == pytest.approx(2.0)


@pytest.mark.unit
def test_lead_time_proxy_none_when_all_singletons() -> None:
    posts = [_post(1, 1, channel_id=4, when=_ANCHOR)]
    assert lead_time_proxy_hours(posts) is None
