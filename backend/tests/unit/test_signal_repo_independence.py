"""Unit tests: signal_repo carries `effective_sources` onto the live signal (TASK-126).

DB-free: exercises `_build_signal` directly with hand-built per-cluster score points
(now carrying `effective_sources`), proving the latest in-window score's
`effective_sources` is surfaced onto `WatchlistSignalData`, and that it is `None` when
there are no in-window scores (graceful, pre-migration rows / no data — INV2).
"""

from datetime import UTC, datetime, timedelta

import pytest

from storage.repositories.signal_repo import (
    EMPTY_SIGNAL,
    WatchlistSignalData,
    _build_signal,
)

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_empty_signal_effective_sources_is_none() -> None:
    """The shared empty signal carries `effective_sources=None` (no data)."""
    assert EMPTY_SIGNAL.effective_sources is None


@pytest.mark.unit
def test_build_signal_no_points_effective_sources_none() -> None:
    """No in-window score points -> effective_sources None (graceful)."""
    signal = _build_signal(
        {1},
        scores_by_cluster={},
        last_alert_by_cluster={},
    )
    assert signal.effective_sources is None
    assert signal.live_score is None


@pytest.mark.unit
def test_build_signal_carries_latest_effective_sources() -> None:
    """effective_sources is taken from the LATEST in-window score point."""
    older = (_NOW - timedelta(hours=2), 30.0, 0.4, 1.0)
    latest = (_NOW, 55.0, 0.6, 3.0)
    signal = _build_signal(
        {1},
        scores_by_cluster={1: [older, latest]},
        last_alert_by_cluster={},
    )
    assert isinstance(signal, WatchlistSignalData)
    # latest point wins for live_score AND effective_sources (same source point).
    assert signal.live_score == pytest.approx(55.0)
    assert signal.effective_sources == pytest.approx(3.0)


@pytest.mark.unit
def test_build_signal_effective_sources_can_be_none_on_old_row() -> None:
    """A score point with a NULL effective_sources (pre-migration) surfaces as None."""
    point = (_NOW, 40.0, 0.5, None)
    signal = _build_signal(
        {1},
        scores_by_cluster={1: [point]},
        last_alert_by_cluster={},
    )
    assert signal.live_score == pytest.approx(40.0)
    assert signal.effective_sources is None
