"""Unit tests for eval.distribution pure helpers (TASK-081)."""

from __future__ import annotations

import pytest

from eval.distribution import (
    count_at_or_above,
    histogram,
    percentile,
    summarize,
)


@pytest.mark.unit
def test_percentile_matches_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 4.0
    # median of 1..4 by linear interpolation = 2.5
    assert percentile(values, 50) == pytest.approx(2.5)


@pytest.mark.unit
def test_percentile_empty_is_zero() -> None:
    assert percentile([], 90) == 0.0


@pytest.mark.unit
def test_percentile_single_value() -> None:
    assert percentile([7.0], 90) == 7.0


@pytest.mark.unit
def test_percentile_rejects_out_of_range_q() -> None:
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], 101)


@pytest.mark.unit
def test_summarize_shape_and_values() -> None:
    summary = summarize([0.0, 10.0])
    assert summary.count == 2
    assert summary.minimum == 0.0
    assert summary.maximum == 10.0
    assert summary.mean == 5.0
    assert summary.p50 == pytest.approx(5.0)


@pytest.mark.unit
def test_summarize_empty_is_all_zero() -> None:
    summary = summarize([])
    assert summary.count == 0
    assert summary.maximum == 0.0


@pytest.mark.unit
def test_count_at_or_above_is_inclusive() -> None:
    values = [84.9, 85.0, 90.0, 99.9]
    assert count_at_or_above(values, 85.0) == 3
    assert count_at_or_above(values, 90.0) == 2


@pytest.mark.unit
def test_histogram_buckets_and_overflow() -> None:
    # edges: [0,1),[1,5),[5,∞)
    counts = histogram([0.0, 0.5, 1.0, 4.9, 5.0, 100.0], edges=[0.0, 1.0, 5.0])
    assert counts == [2, 2, 2]


@pytest.mark.unit
def test_histogram_rejects_bad_edges() -> None:
    with pytest.raises(ValueError):
        histogram([1.0], edges=[1.0])
    with pytest.raises(ValueError):
        histogram([1.0], edges=[5.0, 1.0])
