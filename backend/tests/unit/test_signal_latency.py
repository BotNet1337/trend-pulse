"""Unit tests for signal_latency — log-format + redis_memory (AC2, AC4).

These tests are DB-free: they verify the log_event format (AC2) and the
redis_memory emit (AC4) without touching Postgres. SQL-percentile correctness
(AC1) lives in tests/integration/test_signal_latency.py where the db_session
fixture is available.

Follows the caplog pattern from test_log_hygiene.py.
"""

import logging
from unittest.mock import MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture
def caplog_tp(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="trendpulse")
    return caplog


def _rec_attr(record: logging.LogRecord, key: str) -> object:
    """Read an extra field injected into a LogRecord via log_event(**fields)."""
    return getattr(record, key)


# ---------------------------------------------------------------------------
# AC2 — log_event format (emit_signal_latency log output)
# ---------------------------------------------------------------------------


def test_emit_signal_latency_log_format_all_none(
    caplog_tp: pytest.LogCaptureFixture,
) -> None:
    """Empty window → count=0, p50/p95=None, log_event called with correct keys."""
    from observability.signal_latency import emit_signal_latency

    mock_session = MagicMock(name="session")
    # Simulate DB returning a row with all-None percentiles and count=0.
    row = MagicMock()
    row.e2e_p50 = None
    row.e2e_p95 = None
    row.delivery_p50 = None
    row.delivery_p95 = None
    row.cnt = 0
    row.cnt_negative = 0
    result = MagicMock()
    result.one.return_value = row
    mock_session.execute.return_value = result

    settings = MagicMock()
    settings.latency_window_seconds = 3600

    result_dict = emit_signal_latency(mock_session, settings)

    assert result_dict["count"] == 0
    assert result_dict["e2e_p50_s"] is None
    assert result_dict["e2e_p95_s"] is None
    assert result_dict["delivery_p50_s"] is None
    assert result_dict["delivery_p95_s"] is None

    # AC2 — log record must exist with the right keys
    records = [r for r in caplog_tp.records if r.getMessage() == "signal_latency"]
    assert len(records) == 1
    rec = records[0]
    assert _rec_attr(rec, "count") == 0
    assert _rec_attr(rec, "e2e_p50_s") is None
    assert _rec_attr(rec, "e2e_p95_s") is None
    assert _rec_attr(rec, "delivery_p50_s") is None
    assert _rec_attr(rec, "delivery_p95_s") is None
    assert _rec_attr(rec, "window_s") == 3600


def test_emit_signal_latency_log_format_with_values(
    caplog_tp: pytest.LogCaptureFixture,
) -> None:
    """Non-empty window → float seconds in log_event."""
    from observability.signal_latency import emit_signal_latency

    mock_session = MagicMock(name="session")
    row = MagicMock()
    row.e2e_p50 = 180.0
    row.e2e_p95 = 420.0
    row.delivery_p50 = 30.0
    row.delivery_p95 = 90.0
    row.cnt = 5
    row.cnt_negative = 0
    result = MagicMock()
    result.one.return_value = row
    mock_session.execute.return_value = result

    settings = MagicMock()
    settings.latency_window_seconds = 3600

    result_dict = emit_signal_latency(mock_session, settings)

    assert result_dict["count"] == 5
    assert isinstance(result_dict["e2e_p50_s"], float)
    assert isinstance(result_dict["e2e_p95_s"], float)

    records = [r for r in caplog_tp.records if r.getMessage() == "signal_latency"]
    assert len(records) == 1
    rec = records[0]
    assert _rec_attr(rec, "e2e_p50_s") == pytest.approx(180.0)
    assert _rec_attr(rec, "e2e_p95_s") == pytest.approx(420.0)
    assert _rec_attr(rec, "delivery_p50_s") == pytest.approx(30.0)
    assert _rec_attr(rec, "delivery_p95_s") == pytest.approx(90.0)
    assert _rec_attr(rec, "count") == 5
    assert _rec_attr(rec, "window_s") == 3600


def test_emit_signal_latency_negative_clamped_reported(
    caplog_tp: pytest.LogCaptureFixture,
) -> None:
    """Negative deltas clamped to 0; count_negative reported in log."""
    from observability.signal_latency import emit_signal_latency

    mock_session = MagicMock(name="session")
    row = MagicMock()
    row.e2e_p50 = 0.0
    row.e2e_p95 = 0.0
    row.delivery_p50 = 0.0
    row.delivery_p95 = 0.0
    row.cnt = 3
    row.cnt_negative = 2
    result = MagicMock()
    result.one.return_value = row
    mock_session.execute.return_value = result

    settings = MagicMock()
    settings.latency_window_seconds = 3600

    result_dict = emit_signal_latency(mock_session, settings)

    assert result_dict["count_negative"] == 2

    records = [r for r in caplog_tp.records if r.getMessage() == "signal_latency"]
    assert len(records) == 1
    rec = records[0]
    assert _rec_attr(rec, "count_negative") == 2


# ---------------------------------------------------------------------------
# AC4 — emit_redis_memory
# ---------------------------------------------------------------------------


def test_emit_redis_memory_success(caplog_tp: pytest.LogCaptureFixture) -> None:
    """Redis INFO memory → log_event('redis_memory', used=…, peak=…, max=…)."""
    from observability.signal_latency import emit_redis_memory

    mock_redis = MagicMock(name="redis")
    mock_redis.info.return_value = {
        "used_memory": 1_048_576,
        "used_memory_peak": 2_097_152,
        "maxmemory": 0,
    }

    result = emit_redis_memory(mock_redis)

    assert result["used"] == 1_048_576
    assert result["peak"] == 2_097_152
    assert result["max"] == 0

    records = [r for r in caplog_tp.records if r.getMessage() == "redis_memory"]
    assert len(records) == 1
    rec = records[0]
    assert _rec_attr(rec, "used") == 1_048_576
    assert _rec_attr(rec, "peak") == 2_097_152
    assert _rec_attr(rec, "max") == 0


def test_emit_redis_memory_redis_error_warns_no_raise(
    caplog_tp: pytest.LogCaptureFixture,
) -> None:
    """Redis unavailable → WARNING log, no raise, returns empty dict."""
    from observability.signal_latency import emit_redis_memory

    mock_redis = MagicMock(name="redis")
    mock_redis.info.side_effect = RedisConnectionError("conn refused")

    result = emit_redis_memory(mock_redis)

    assert result == {}
    warnings = [r for r in caplog_tp.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# AC3 variant — Beat entry exists in scheduler (no DB needed)
# ---------------------------------------------------------------------------


def test_beat_schedule_has_emit_signal_latency_entry() -> None:
    """Beat schedule must contain the 'emit-signal-latency' entry."""
    from observability.constants import EMIT_SIGNAL_LATENCY_TASK
    from scheduler import beat_schedule

    entry = beat_schedule.get("emit-signal-latency")
    assert entry is not None, "missing 'emit-signal-latency' in beat_schedule"
    assert entry["task"] == EMIT_SIGNAL_LATENCY_TASK


def test_beat_schedule_emit_signal_latency_uses_settings_interval() -> None:
    """Beat interval comes from settings (no magic literals)."""
    from config import get_settings
    from scheduler import beat_schedule

    settings = get_settings()
    entry = beat_schedule["emit-signal-latency"]
    assert entry["schedule"] == float(settings.latency_emit_interval_seconds)


def test_settings_latency_defaults() -> None:
    """Settings have correct defaults for latency emit/window intervals."""
    from config import get_settings

    settings = get_settings()
    assert settings.latency_emit_interval_seconds == 300
    assert settings.latency_window_seconds == 3600
