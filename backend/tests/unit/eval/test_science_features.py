"""Unit tests for eval.science_features — C2 early-window virality features (TASK-113).

Hand-computed cases so each feature's lift is reproducible from first principles.
"""

from __future__ import annotations

import math

import pytest

from eval.science_features import (
    ScienceFeatureError,
    TimedEvent,
    breadth_velocity,
    channel_authority,
    compute_science_features,
    effective_independent_sources,
    ewma_acceleration,
    ewma_velocity,
    hawkes_branching_ratio,
    source_entropy,
    time_of_day_phase,
)

_HOUR = 3600.0


def _e(epoch: float, source_id: int = 1, weight: float = 1.0) -> TimedEvent:
    return TimedEvent(epoch=epoch, source_id=source_id, weight=weight)


# --- validation ----------------------------------------------------------------------


@pytest.mark.unit
def test_event_rejects_negative_weight() -> None:
    with pytest.raises(ScienceFeatureError):
        _e(0.0, weight=-1.0)


@pytest.mark.unit
def test_event_rejects_nonfinite_epoch() -> None:
    with pytest.raises(ScienceFeatureError):
        _e(math.inf)


@pytest.mark.unit
def test_ewma_rejects_nonpositive_half_life() -> None:
    with pytest.raises(ScienceFeatureError):
        ewma_velocity([_e(0.0)], half_life_seconds=0.0)


@pytest.mark.unit
def test_hawkes_rejects_nonpositive_decay() -> None:
    with pytest.raises(ScienceFeatureError):
        hawkes_branching_ratio([_e(0.0), _e(1.0)], decay_seconds=0.0)


# --- empties -------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_window_features_are_zero() -> None:
    assert ewma_velocity([], half_life_seconds=_HOUR) == 0.0
    assert breadth_velocity([]) == 0.0
    assert hawkes_branching_ratio([], decay_seconds=_HOUR) == 0.0
    assert source_entropy([]) == 0.0
    assert effective_independent_sources([]) == 0.0
    assert channel_authority([]) == 0.0


# --- EWMA ----------------------------------------------------------------------------


@pytest.mark.unit
def test_ewma_velocity_positive_for_activity() -> None:
    events = [_e(0.0), _e(_HOUR), _e(2 * _HOUR)]
    assert ewma_velocity(events, half_life_seconds=_HOUR) > 0.0


@pytest.mark.unit
def test_ewma_acceleration_positive_when_back_loaded() -> None:
    # events cluster in the second half -> accelerating -> positive
    back = [_e(0.0), _e(9 * _HOUR), _e(9.5 * _HOUR), _e(10 * _HOUR)]
    assert ewma_acceleration(back, half_life_seconds=_HOUR) > 0.0


@pytest.mark.unit
def test_ewma_acceleration_single_event_is_zero() -> None:
    assert ewma_acceleration([_e(0.0)], half_life_seconds=_HOUR) == 0.0


# --- breadth velocity ----------------------------------------------------------------


@pytest.mark.unit
def test_breadth_velocity_counts_distinct_sources_per_hour() -> None:
    # 3 distinct sources over a 2-hour span -> 1.5 sources/hour
    events = [_e(0.0, 1), _e(_HOUR, 2), _e(2 * _HOUR, 3)]
    assert breadth_velocity(events) == pytest.approx(1.5)


# --- Hawkes branching ----------------------------------------------------------------


@pytest.mark.unit
def test_hawkes_branching_counts_offspring() -> None:
    # 3 events within one decay window: event0 has 2 offspring, event1 has 1, event2 has
    # 0 -> total 3 / n=3 -> n* = 1.0
    events = [_e(0.0), _e(10.0), _e(20.0)]
    assert hawkes_branching_ratio(events, decay_seconds=100.0) == pytest.approx(1.0)


@pytest.mark.unit
def test_hawkes_branching_zero_when_spread_out() -> None:
    # events spaced beyond the decay window -> no offspring -> n* = 0
    events = [_e(0.0), _e(1000.0), _e(2000.0)]
    assert hawkes_branching_ratio(events, decay_seconds=100.0) == pytest.approx(0.0)


# --- time of day ---------------------------------------------------------------------


@pytest.mark.unit
def test_time_of_day_phase_midnight_is_zero() -> None:
    # epoch 0 = 1970-01-01T00:00:00Z -> phase 0
    assert time_of_day_phase(0.0) == pytest.approx(0.0)


@pytest.mark.unit
def test_time_of_day_phase_noon_is_half() -> None:
    assert time_of_day_phase(12 * _HOUR) == pytest.approx(0.5)


# --- entropy / independence ----------------------------------------------------------


@pytest.mark.unit
def test_source_entropy_single_source_is_zero() -> None:
    events = [_e(0.0, 1), _e(1.0, 1), _e(2.0, 1)]
    assert source_entropy(events) == pytest.approx(0.0)
    assert effective_independent_sources(events) == pytest.approx(1.0)


@pytest.mark.unit
def test_effective_sources_uniform_equals_count() -> None:
    # 4 sources each once -> entropy ln(4) -> exp = 4 effective sources
    events = [_e(float(i), i) for i in range(4)]
    assert effective_independent_sources(events) == pytest.approx(4.0)


@pytest.mark.unit
def test_effective_sources_collusion_collapses() -> None:
    # one dominant source + a couple of others -> effective << raw count
    events = [_e(0.0, 1), _e(1.0, 1), _e(2.0, 1), _e(3.0, 1), _e(4.0, 2), _e(5.0, 3)]
    raw_distinct = 3
    assert effective_independent_sources(events) < raw_distinct


# --- channel authority ---------------------------------------------------------------


@pytest.mark.unit
def test_channel_authority_higher_for_dominant_source() -> None:
    dominant = [_e(0.0, 1), _e(1.0, 1), _e(2.0, 1), _e(3.0, 2)]
    even = [_e(0.0, 1), _e(1.0, 2), _e(2.0, 3), _e(3.0, 4)]
    assert channel_authority(dominant) > channel_authority(even)


# --- bundle --------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_science_features_bundle() -> None:
    events = [_e(0.0, 1), _e(_HOUR, 2), _e(2 * _HOUR, 3)]
    bundle = compute_science_features(
        events, birth_epoch=0.0, ewma_half_life_seconds=_HOUR, hawkes_decay_seconds=_HOUR
    )
    assert bundle.breadth_velocity == pytest.approx(1.5)
    assert bundle.time_of_day_phase == pytest.approx(0.0)
    assert bundle.effective_independent_sources == pytest.approx(3.0)
