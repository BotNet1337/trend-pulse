"""Unit tests for eval.quality — the B0 data-quality gate (TASK-108).

These encode the gate's truth table: a cluster is "quality" iff it survives every
named gate (size, channel breadth, near-duplicate, recurring boilerplate, co-channel
self-amplification, field completeness, temporal sanity). The gate is the prerequisite
for Track C training ("train only on quality data"). All inputs are EARLY/STRUCTURAL
(leak-free — no future-label field), so the gate can run at feature time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eval.corpus import PostRecord
from eval.quality import (
    ClusterQualityFeatures,
    QualityInputError,
    QualityThresholds,
    QualityVerdict,
    assess_cluster,
    build_cluster_features,
    is_quality_cluster,
    summarize_quality,
)

_TH = QualityThresholds()
_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _features(
    *,
    cluster_id: int = 1,
    post_count: int = 8,
    unique_channels: int = 4,
    span_seconds: int = 3 * 3600,
    max_cross_cluster_cosine: float = 0.40,
    top_channel_share: float = 0.40,
    completeness_ok: bool = True,
    max_fetch_lag_seconds: float = 120.0,
) -> ClusterQualityFeatures:
    """A healthy, multi-channel, medium-sized, recent cluster - each kwarg tweaks one gate."""
    return ClusterQualityFeatures(
        cluster_id=cluster_id,
        post_count=post_count,
        unique_channels=unique_channels,
        span_seconds=span_seconds,
        max_cross_cluster_cosine=max_cross_cluster_cosine,
        top_channel_share=top_channel_share,
        completeness_ok=completeness_ok,
        max_fetch_lag_seconds=max_fetch_lag_seconds,
    )


# --- is_quality_cluster: truth table -------------------------------------------------


@pytest.mark.unit
def test_healthy_cluster_passes_all_gates() -> None:
    verdict = assess_cluster(_features(), thresholds=_TH)
    assert verdict.is_quality is True
    assert verdict.failed_gates == ()
    assert is_quality_cluster(_features(), thresholds=_TH) is True


@pytest.mark.unit
def test_too_small_singleton_fails() -> None:
    verdict = assess_cluster(_features(post_count=1, unique_channels=1), thresholds=_TH)
    assert verdict.is_quality is False
    assert "too_small" in verdict.failed_gates


@pytest.mark.unit
def test_mega_bucket_fails() -> None:
    verdict = assess_cluster(_features(post_count=4102, unique_channels=50), thresholds=_TH)
    assert verdict.is_quality is False
    assert "mega_bucket" in verdict.failed_gates


@pytest.mark.unit
def test_near_duplicate_fails() -> None:
    verdict = assess_cluster(_features(max_cross_cluster_cosine=0.95), thresholds=_TH)
    assert verdict.is_quality is False
    assert "near_duplicate" in verdict.failed_gates


@pytest.mark.unit
def test_single_channel_fails() -> None:
    verdict = assess_cluster(_features(unique_channels=1, top_channel_share=1.0), thresholds=_TH)
    assert verdict.is_quality is False
    assert "single_channel" in verdict.failed_gates


@pytest.mark.unit
def test_recurring_boilerplate_fails() -> None:
    # huge span but low channel breadth → daily-market / "Доброе утро" chain
    verdict = assess_cluster(
        _features(span_seconds=40 * 24 * 3600, unique_channels=2, post_count=200),
        thresholds=_TH,
    )
    assert verdict.is_quality is False
    assert "recurring_boilerplate" in verdict.failed_gates


@pytest.mark.unit
def test_co_channel_self_amplification_fails() -> None:
    # one channel dominates the cluster → coordinated/self-amplified, not organic spread
    verdict = assess_cluster(_features(unique_channels=3, top_channel_share=0.95), thresholds=_TH)
    assert verdict.is_quality is False
    assert "co_channel_dominated" in verdict.failed_gates


@pytest.mark.unit
def test_incomplete_fields_fails() -> None:
    verdict = assess_cluster(_features(completeness_ok=False), thresholds=_TH)
    assert verdict.is_quality is False
    assert "incomplete" in verdict.failed_gates


@pytest.mark.unit
def test_temporal_insanity_backfill_fails() -> None:
    # fetched months after posted → backfill fingerprint
    verdict = assess_cluster(_features(max_fetch_lag_seconds=200 * 24 * 3600.0), thresholds=_TH)
    assert verdict.is_quality is False
    assert "temporally_insane" in verdict.failed_gates


@pytest.mark.unit
def test_multiple_gates_fail_are_all_reported() -> None:
    verdict = assess_cluster(
        _features(post_count=1, unique_channels=1, top_channel_share=1.0), thresholds=_TH
    )
    assert verdict.is_quality is False
    # singleton trips too_small AND single_channel (and co_channel is guarded by min channels)
    assert "too_small" in verdict.failed_gates
    assert "single_channel" in verdict.failed_gates


# --- boundary values -----------------------------------------------------------------


@pytest.mark.unit
def test_min_posts_boundary_inclusive() -> None:
    at = _features(post_count=_TH.min_posts, unique_channels=2)
    below = _features(post_count=_TH.min_posts - 1, unique_channels=2)
    assert is_quality_cluster(at, thresholds=_TH) is True
    assert is_quality_cluster(below, thresholds=_TH) is False


@pytest.mark.unit
def test_min_channels_boundary_inclusive() -> None:
    at = _features(unique_channels=_TH.min_channels, top_channel_share=0.5)
    below = _features(unique_channels=_TH.min_channels - 1)
    assert is_quality_cluster(at, thresholds=_TH) is True
    assert is_quality_cluster(below, thresholds=_TH) is False


@pytest.mark.unit
def test_max_posts_boundary_exclusive() -> None:
    # gate is strictly `>`: at the cap passes, one above fails
    at = _features(post_count=_TH.max_posts, unique_channels=5)
    above = _features(post_count=_TH.max_posts + 1, unique_channels=5)
    assert is_quality_cluster(at, thresholds=_TH) is True
    assert "mega_bucket" in assess_cluster(above, thresholds=_TH).failed_gates


@pytest.mark.unit
def test_top_channel_share_boundary_exclusive() -> None:
    # gate is strictly `>`: exactly at the cap passes, just above is co-channel-dominated
    at = _features(unique_channels=3, top_channel_share=_TH.max_top_channel_share)
    above = _features(unique_channels=3, top_channel_share=_TH.max_top_channel_share + 0.05)
    assert is_quality_cluster(at, thresholds=_TH) is True
    assert "co_channel_dominated" in assess_cluster(above, thresholds=_TH).failed_gates


@pytest.mark.unit
def test_co_channel_gate_suppressed_for_single_channel_cluster() -> None:
    # a 1-channel cluster has share 1.0 but the co_channel guard must NOT fire it
    # (it is already rejected by single_channel; no double-count).
    verdict = assess_cluster(_features(unique_channels=1, top_channel_share=1.0), thresholds=_TH)
    assert "single_channel" in verdict.failed_gates
    assert "co_channel_dominated" not in verdict.failed_gates


@pytest.mark.unit
def test_recurring_span_boundary_exclusive() -> None:
    # gate is strictly `>`: exactly at the span cap (low breadth) passes
    at = _features(span_seconds=_TH.recurring_span_seconds, unique_channels=2, post_count=50)
    above = _features(span_seconds=_TH.recurring_span_seconds + 1, unique_channels=2, post_count=50)
    assert "recurring_boilerplate" not in assess_cluster(at, thresholds=_TH).failed_gates
    assert "recurring_boilerplate" in assess_cluster(above, thresholds=_TH).failed_gates


@pytest.mark.unit
def test_fetch_lag_boundary_exclusive() -> None:
    # gate is strictly `>`: exactly at the lag cap passes, just above is backfill
    at = _features(max_fetch_lag_seconds=float(_TH.max_fetch_lag_seconds))
    above = _features(max_fetch_lag_seconds=float(_TH.max_fetch_lag_seconds) + 1.0)
    assert "temporally_insane" not in assess_cluster(at, thresholds=_TH).failed_gates
    assert "temporally_insane" in assess_cluster(above, thresholds=_TH).failed_gates


@pytest.mark.unit
def test_summarize_histogram_counts_each_failed_gate_of_a_multi_fail_cluster() -> None:
    # one cluster that fails 2 distinct gates → both buckets increment (additive contract)
    multi = assess_cluster(
        _features(unique_channels=1, max_cross_cluster_cosine=0.95, top_channel_share=1.0),
        thresholds=_TH,
    )
    summary = summarize_quality([multi])
    assert summary.quality_count == 0
    assert summary.gate_failures["single_channel"] == 1
    assert summary.gate_failures["near_duplicate"] == 1


@pytest.mark.unit
def test_dup_cosine_boundary_inclusive() -> None:
    # at-threshold cosine is a duplicate (>=), just-below passes
    at = _features(max_cross_cluster_cosine=_TH.duplicate_cosine)
    below = _features(max_cross_cluster_cosine=_TH.duplicate_cosine - 0.01)
    assert is_quality_cluster(at, thresholds=_TH) is False
    assert is_quality_cluster(below, thresholds=_TH) is True


# --- input validation ----------------------------------------------------------------


@pytest.mark.unit
def test_negative_post_count_raises() -> None:
    with pytest.raises(QualityInputError):
        ClusterQualityFeatures(
            cluster_id=1,
            post_count=-1,
            unique_channels=1,
            span_seconds=0,
            max_cross_cluster_cosine=0.0,
            top_channel_share=1.0,
            completeness_ok=True,
            max_fetch_lag_seconds=0.0,
        )


@pytest.mark.unit
def test_share_out_of_range_raises() -> None:
    with pytest.raises(QualityInputError):
        ClusterQualityFeatures(
            cluster_id=1,
            post_count=2,
            unique_channels=2,
            span_seconds=0,
            max_cross_cluster_cosine=0.0,
            top_channel_share=1.5,
            completeness_ok=True,
            max_fetch_lag_seconds=0.0,
        )


@pytest.mark.unit
def test_cosine_out_of_range_raises() -> None:
    with pytest.raises(QualityInputError):
        ClusterQualityFeatures(
            cluster_id=1,
            post_count=2,
            unique_channels=2,
            span_seconds=0,
            max_cross_cluster_cosine=1.5,
            top_channel_share=0.5,
            completeness_ok=True,
            max_fetch_lag_seconds=0.0,
        )


# --- summarize_quality ---------------------------------------------------------------


@pytest.mark.unit
def test_summarize_counts_and_gate_histogram() -> None:
    verdicts = [
        assess_cluster(_features(cluster_id=1), thresholds=_TH),  # quality
        assess_cluster(_features(cluster_id=2), thresholds=_TH),  # quality
        assess_cluster(_features(cluster_id=3, post_count=1, unique_channels=1), thresholds=_TH),
        assess_cluster(_features(cluster_id=4, max_cross_cluster_cosine=0.95), thresholds=_TH),
    ]
    summary = summarize_quality(verdicts)
    assert summary.total == 4
    assert summary.quality_count == 2
    assert summary.quality_pct == pytest.approx(50.0)
    assert summary.gate_failures["too_small"] == 1
    assert summary.gate_failures["near_duplicate"] == 1


@pytest.mark.unit
def test_summarize_empty_is_honest_zero() -> None:
    summary = summarize_quality([])
    assert summary.total == 0
    assert summary.quality_count == 0
    assert summary.quality_pct == 0.0


# --- build_cluster_features from PostRecord clusters ---------------------------------


def _post(pid: int, channel: int, minutes: int, *, fetch_lag_min: float = 1.0) -> PostRecord:
    posted = _T0 + timedelta(minutes=minutes)
    return PostRecord(
        id=pid,
        posted_at=posted,
        channel_id=channel,
        user_id=10,
        cluster_id=1,
        views=100,
        forwards=2,
        reactions=5,
    )


@pytest.mark.unit
def test_build_features_from_posts_computes_breadth_span_and_dominance() -> None:
    # 6 posts across 3 channels over 2 hours; channel 1 has 3 of 6 posts (share 0.5)
    posts = [
        _post(1, 1, 0),
        _post(2, 1, 30),
        _post(3, 1, 60),
        _post(4, 2, 90),
        _post(5, 3, 100),
        _post(6, 2, 120),
    ]
    feats = build_cluster_features(
        cluster_id=1, posts=posts, max_cross_cluster_cosine=0.3, max_fetch_lag_seconds=60.0
    )
    assert feats.post_count == 6
    assert feats.unique_channels == 3
    assert feats.span_seconds == 120 * 60  # 2h
    assert feats.top_channel_share == pytest.approx(0.5)  # 3/6
    assert feats.completeness_ok is True


@pytest.mark.unit
def test_build_features_empty_cluster_is_too_small() -> None:
    feats = build_cluster_features(
        cluster_id=9, posts=[], max_cross_cluster_cosine=0.0, max_fetch_lag_seconds=0.0
    )
    assert feats.post_count == 0
    assert is_quality_cluster(feats, thresholds=_TH) is False


@pytest.mark.unit
def test_build_features_single_post_zero_span_no_divzero() -> None:
    feats = build_cluster_features(
        cluster_id=1,
        posts=[_post(1, 1, 0)],
        max_cross_cluster_cosine=0.0,
        max_fetch_lag_seconds=0.0,
    )
    assert feats.post_count == 1
    assert feats.span_seconds == 0
    assert feats.top_channel_share == pytest.approx(1.0)
    # recurring-boilerplate heuristic must not raise on zero span
    verdict = assess_cluster(feats, thresholds=_TH)
    assert isinstance(verdict, QualityVerdict)
