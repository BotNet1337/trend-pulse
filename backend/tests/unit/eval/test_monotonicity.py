"""Monotonicity / property tests for the viral-score formula (TASK-085, layer 1).

These prove -- deterministically, no labels needed -- that the REAL scorer
(`scorer.score.compute_components`, imported, never reimplemented) RESPONDS to each
driver of virality in the correct direction:

  * more distinct channels  -> higher velocity
  * faster spread (smaller delta_hours) -> higher velocity
  * engagement above channel_avg -> engagement > 1 and rising with the numerator
  * broader watched-channel coverage -> higher cross_channel
  * the composite viral_score is monotonic NON-DECREASING in each component

`hypothesis` is not a dependency of this repo, so these use parametrized "property"
cases over representative ranges (the property-based style without the library).
"""

from __future__ import annotations

import pytest

from scorer.score import (
    CROSS_CHANNEL_WEIGHT,
    ENGAGEMENT_WEIGHT,
    VELOCITY_WEIGHT,
    ScoreInputs,
    compute_components,
)


def _inputs(**overrides: object) -> ScoreInputs:
    """Build ScoreInputs from a neutral baseline, overriding only the driver under test."""
    base: dict[str, object] = {
        "views": 1000,
        "forwards": 10,
        "reactions": 20,
        "channel_avg": 1000.0,
        "delta_channel_count": 3,
        "delta_hours": 2.0,
        "unique_channels_count": 3,
        "watched_channels_count": 10,
    }
    base.update(overrides)
    return ScoreInputs(**base)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize("channels", [(1, 2), (2, 5), (5, 15), (15, 50)])
def test_more_distinct_channels_raises_velocity(channels: tuple[int, int]) -> None:
    low, high = channels
    v_low = compute_components(_inputs(delta_channel_count=low)).velocity
    v_high = compute_components(_inputs(delta_channel_count=high)).velocity
    assert v_high > v_low


@pytest.mark.unit
@pytest.mark.parametrize("hours", [(0.5, 1.0), (1.0, 2.0), (2.0, 6.0), (6.0, 24.0)])
def test_faster_spread_raises_velocity(hours: tuple[float, float]) -> None:
    fast, slow = hours
    v_fast = compute_components(_inputs(delta_hours=fast)).velocity
    v_slow = compute_components(_inputs(delta_hours=slow)).velocity
    assert v_fast > v_slow


@pytest.mark.unit
def test_engagement_above_baseline_exceeds_one() -> None:
    # weighted numerator = views + 3*fwd + 2*rx; set it well above channel_avg
    comp = compute_components(_inputs(views=5000, forwards=100, reactions=200, channel_avg=1000.0))
    assert comp.engagement > 1.0


@pytest.mark.unit
def test_engagement_below_baseline_under_one() -> None:
    comp = compute_components(_inputs(views=200, forwards=1, reactions=2, channel_avg=1000.0))
    assert comp.engagement < 1.0


@pytest.mark.unit
@pytest.mark.parametrize("views", [(500, 1000), (1000, 5000), (5000, 20000)])
def test_engagement_rises_with_numerator(views: tuple[int, int]) -> None:
    low, high = views
    e_low = compute_components(_inputs(views=low)).engagement
    e_high = compute_components(_inputs(views=high)).engagement
    assert e_high > e_low


@pytest.mark.unit
@pytest.mark.parametrize("unique", [(1, 3), (3, 5), (5, 10)])
def test_broader_coverage_raises_cross_channel(unique: tuple[int, int]) -> None:
    low, high = unique
    c_low = compute_components(_inputs(unique_channels_count=low, watched_channels_count=10))
    c_high = compute_components(_inputs(unique_channels_count=high, watched_channels_count=10))
    assert c_high.cross_channel > c_low.cross_channel


@pytest.mark.unit
def test_composite_non_decreasing_in_velocity() -> None:
    # raising delta_channel_count raises velocity and must not lower viral_score
    low = compute_components(_inputs(delta_channel_count=2))
    high = compute_components(_inputs(delta_channel_count=20))
    assert high.velocity > low.velocity
    assert high.viral_score >= low.viral_score


@pytest.mark.unit
def test_composite_non_decreasing_in_engagement() -> None:
    low = compute_components(_inputs(views=500))
    high = compute_components(_inputs(views=50_000))
    assert high.engagement > low.engagement
    assert high.viral_score >= low.viral_score


@pytest.mark.unit
def test_composite_non_decreasing_in_cross_channel() -> None:
    low = compute_components(_inputs(unique_channels_count=1, watched_channels_count=10))
    high = compute_components(_inputs(unique_channels_count=10, watched_channels_count=10))
    assert high.cross_channel > low.cross_channel
    assert high.viral_score >= low.viral_score


@pytest.mark.unit
def test_weights_sum_to_one() -> None:
    # the composite is a convex combination -> a component delta maps proportionally
    assert pytest.approx(1.0) == VELOCITY_WEIGHT + ENGAGEMENT_WEIGHT + CROSS_CHANNEL_WEIGHT


@pytest.mark.unit
def test_all_drivers_maxed_beats_all_drivers_floored() -> None:
    """End-to-end: a clearly-viral input outranks a clearly-noise input."""
    viral = compute_components(
        _inputs(
            views=80_000,
            forwards=4_000,
            reactions=6_000,
            delta_channel_count=15,
            delta_hours=20 / 60,
            unique_channels_count=15,
        )
    )
    noise = compute_components(
        _inputs(
            views=50,
            forwards=0,
            reactions=0,
            delta_channel_count=1,
            delta_hours=24.0,
            unique_channels_count=1,
        )
    )
    assert viral.viral_score > noise.viral_score
