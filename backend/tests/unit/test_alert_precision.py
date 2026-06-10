"""Unit tests for emit_alert_precision — AC4 (TASK-042).

AC4: Given 3 up + 1 down over the 7d window, emit_alert_precision logs
     alert_precision with precision=0.75, rated=4.

Pure compute via mocked DB (no live DB needed for unit) — runs under
`make ci-fast` with sqlalchemy in-memory or via mock.

We test the compute logic via a MagicMock session that returns a known query
result, similar to test_signal_latency unit tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from observability.signal_latency import emit_alert_precision

# Verdict constants
_VERDICT_UP = 1
_VERDICT_DOWN = 0


def _make_settings(
    precision_window_seconds: int = 604800,
    latency_emit_interval_seconds: int = 300,
) -> MagicMock:
    s = MagicMock()
    s.precision_window_seconds = precision_window_seconds
    s.latency_emit_interval_seconds = latency_emit_interval_seconds
    return s


def test_precision_three_up_one_down() -> None:
    """3 up + 1 down → precision=0.75, rated=4, logged correctly."""
    # Mock session returning rows via _mapping (matches _COL_* key access in production).
    mock_row_1 = MagicMock()
    mock_row_1._mapping = {
        "user_id": 1,
        "up_count": 3,
        "down_count": 1,
        "total_alerts": 10,  # total alerts in window (rated+unrated)
    }

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row_1]

    session = MagicMock()
    session.execute.return_value = mock_result

    settings = _make_settings()

    with patch("observability.signal_latency.log_event") as mock_log:
        results = emit_alert_precision(session, settings)

    assert len(results) == 1
    entry = results[0]
    assert entry["user_id"] == 1
    assert entry["precision"] == pytest.approx(0.75)
    assert entry["rated"] == 4
    assert entry["total"] == 10

    # Verify log_event was called
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs[0][0] == "alert_precision"  # event name
    assert call_kwargs[1]["user_id"] == 1
    assert call_kwargs[1]["precision"] == pytest.approx(0.75)
    assert call_kwargs[1]["rated"] == 4
    assert call_kwargs[1]["total"] == 10


def test_precision_all_up() -> None:
    """All up → precision=1.0."""
    mock_row = MagicMock()
    mock_row._mapping = {"user_id": 2, "up_count": 5, "down_count": 0, "total_alerts": 5}

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    session = MagicMock()
    session.execute.return_value = mock_result

    with patch("observability.signal_latency.log_event"):
        results = emit_alert_precision(session, _make_settings())

    assert results[0]["precision"] == pytest.approx(1.0)
    assert results[0]["rated"] == 5


def test_precision_all_down() -> None:
    """All down → precision=0.0."""
    mock_row = MagicMock()
    mock_row._mapping = {"user_id": 3, "up_count": 0, "down_count": 3, "total_alerts": 3}

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    session = MagicMock()
    session.execute.return_value = mock_result

    with patch("observability.signal_latency.log_event"):
        results = emit_alert_precision(session, _make_settings())

    assert results[0]["precision"] == pytest.approx(0.0)
    assert results[0]["rated"] == 3


def test_precision_empty_returns_empty_list() -> None:
    """No feedback rows in window → empty list returned, no error."""
    mock_result = MagicMock()
    mock_result.all.return_value = []

    session = MagicMock()
    session.execute.return_value = mock_result

    with patch("observability.signal_latency.log_event") as mock_log:
        results = emit_alert_precision(session, _make_settings())

    assert results == []
    mock_log.assert_not_called()


def test_precision_total_independent_from_rated() -> None:
    """Regression guard: total comes from alerts table, not alert_feedback COUNT.

    The SQL must return total_alerts as a correlated subquery over the alerts
    table — NOT COUNT(*) over alert_feedback.  Here rated=4 but total=5 (one
    unrated alert in window).  If total==rated this test will catch the regression.
    """
    mock_row = MagicMock()
    mock_row._mapping = {
        "user_id": 10,
        "up_count": 3,
        "down_count": 1,
        "total_alerts": 5,  # 5 alerts in window, only 4 rated
    }

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    session = MagicMock()
    session.execute.return_value = mock_result

    with patch("observability.signal_latency.log_event"):
        results = emit_alert_precision(session, _make_settings())

    assert len(results) == 1
    entry = results[0]
    assert entry["rated"] == 4, "rated = up+down"
    assert entry["total"] == 5, "total must differ from rated — comes from alerts table"
    assert entry["precision"] == pytest.approx(0.75)


def test_precision_multiple_users() -> None:
    """Multiple users each get their own precision logged."""
    rows = []
    for i, (up, down, total) in enumerate([(2, 1, 5), (4, 0, 4), (0, 2, 3)], start=1):
        row = MagicMock()
        row._mapping = {
            "user_id": i,
            "up_count": up,
            "down_count": down,
            "total_alerts": total,
        }
        rows.append(row)

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    session = MagicMock()
    session.execute.return_value = mock_result

    log_calls: list[tuple[object, ...]] = []

    with patch(
        "observability.signal_latency.log_event",
        side_effect=lambda *a, **kw: log_calls.append((a, kw)),
    ):
        results = emit_alert_precision(session, _make_settings())

    assert len(results) == 3
    assert len(log_calls) == 3

    precisions = [r["precision"] for r in results]
    assert precisions[0] == pytest.approx(2 / 3)
    assert precisions[1] == pytest.approx(1.0)
    assert precisions[2] == pytest.approx(0.0)
