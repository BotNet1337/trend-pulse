"""Unit tests for scorer.feature_snapshots pure logic (TASK-109, B1).

The forward feature-snapshot capture decides, from a cluster's age and the windows
already captured, which early observation windows (15m/30m/1h) are now DUE — and
computes the metrics-only snapshot fields. These are pure, DB-free functions so the
opportunistic-capture contract is testable without a live Postgres.
"""

from __future__ import annotations

import pytest

from scorer.feature_snapshots import (
    OBSERVATION_WINDOW_SECONDS,
    SnapshotMetrics,
    breadth_velocity,
    build_snapshot_metrics,
    windows_due,
)


@pytest.mark.unit
def test_windows_ordered_and_named() -> None:
    # exactly the three early windows, ascending, named (no magic literals)
    assert list(OBSERVATION_WINDOW_SECONDS) == ["15m", "30m", "1h"]
    assert OBSERVATION_WINDOW_SECONDS["15m"] == 15 * 60
    assert OBSERVATION_WINDOW_SECONDS["30m"] == 30 * 60
    assert OBSERVATION_WINDOW_SECONDS["1h"] == 60 * 60


@pytest.mark.unit
def test_no_window_due_before_first_window() -> None:
    assert windows_due(age_seconds=14 * 60, captured=frozenset()) == ()


@pytest.mark.unit
def test_first_window_due_at_boundary() -> None:
    assert windows_due(age_seconds=15 * 60, captured=frozenset()) == ("15m",)


@pytest.mark.unit
def test_only_uncaptured_windows_are_due() -> None:
    # aged 31 min, already captured 15m → only 30m due (not 1h yet)
    assert windows_due(age_seconds=31 * 60, captured=frozenset({"15m"})) == ("30m",)


@pytest.mark.unit
def test_all_crossed_windows_backfilled_when_earlier_ticks_missed() -> None:
    # aged 65 min, nothing captured → all three crossed windows due, ascending
    assert windows_due(age_seconds=65 * 60, captured=frozenset()) == ("15m", "30m", "1h")


@pytest.mark.unit
def test_already_captured_returns_empty() -> None:
    assert windows_due(age_seconds=65 * 60, captured=frozenset({"15m", "30m", "1h"})) == ()


@pytest.mark.unit
def test_negative_age_clock_skew_yields_no_windows() -> None:
    assert windows_due(age_seconds=-10, captured=frozenset()) == ()


@pytest.mark.unit
def test_breadth_velocity_channels_per_hour() -> None:
    # 4 channels over exactly 1 hour → 4.0 channels/hr
    assert breadth_velocity(distinct_channels=4, age_seconds=3600) == pytest.approx(4.0)


@pytest.mark.unit
def test_breadth_velocity_clamps_tiny_age_no_divzero() -> None:
    # zero / sub-clamp age must not divide by zero; denominator floored
    v = breadth_velocity(distinct_channels=2, age_seconds=0)
    assert v >= 0.0
    assert v != float("inf")


@pytest.mark.unit
def test_build_snapshot_metrics_aggregates() -> None:
    metrics = build_snapshot_metrics(
        post_views=[100, 50, 30],
        post_forwards=[2, 1, 0],
        post_reactions=[10, 5, 3],
        channel_ids=[1, 1, 2],
        age_seconds=1800,
    )
    assert isinstance(metrics, SnapshotMetrics)
    assert metrics.post_count == 3
    assert metrics.views == 180
    assert metrics.forwards == 3
    assert metrics.reactions == 18
    assert metrics.distinct_channels == 2
    assert metrics.breadth_velocity == pytest.approx(2 / 0.5)  # 2 ch over 0.5h = 4.0


@pytest.mark.unit
def test_build_snapshot_metrics_empty_is_zero() -> None:
    metrics = build_snapshot_metrics(
        post_views=[], post_forwards=[], post_reactions=[], channel_ids=[], age_seconds=900
    )
    assert metrics.post_count == 0
    assert metrics.distinct_channels == 0
    assert metrics.breadth_velocity == 0.0


@pytest.mark.unit
def test_build_snapshot_metrics_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        build_snapshot_metrics(
            post_views=[1, 2],
            post_forwards=[1],
            post_reactions=[1, 2],
            channel_ids=[1, 2],
            age_seconds=900,
        )
