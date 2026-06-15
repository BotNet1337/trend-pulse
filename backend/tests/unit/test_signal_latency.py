"""Unit tests for signal_latency — log-format + redis_memory (AC2, AC4).

These tests are DB-free: they verify the log_event format (AC2) and the
redis_memory emit (AC4) without touching Postgres. SQL-percentile correctness
(AC1) lives in tests/integration/test_signal_latency.py where the db_session
fixture is available.

Follows the caplog pattern from test_log_hygiene.py.
"""

import logging
from unittest.mock import MagicMock, patch

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
    # Row access uses row._mapping[_COL_*] keys (consistent with production code).
    row = MagicMock()
    row._mapping = {
        "e2e_p50": None,
        "e2e_p95": None,
        "delivery_p50": None,
        "delivery_p95": None,
        "cnt": 0,
        "cnt_negative": 0,
    }
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
    row._mapping = {
        "e2e_p50": 180.0,
        "e2e_p95": 420.0,
        "delivery_p50": 30.0,
        "delivery_p95": 90.0,
        "cnt": 5,
        "cnt_negative": 0,
    }
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
    row._mapping = {
        "e2e_p50": 0.0,
        "e2e_p95": 0.0,
        "delivery_p50": 0.0,
        "delivery_p95": 0.0,
        "cnt": 3,
        "cnt_negative": 2,
    }
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


# ---------------------------------------------------------------------------
# TASK-100 — is_redis_memory_critical predicate
# ---------------------------------------------------------------------------


def test_is_redis_memory_critical_truth_table() -> None:
    from observability.signal_latency import is_redis_memory_critical

    # at/above ratio → critical
    assert is_redis_memory_critical(used=90, maxmemory=100, ratio=0.9) is True
    assert is_redis_memory_critical(used=95, maxmemory=100, ratio=0.9) is True
    # below ratio → not critical
    assert is_redis_memory_critical(used=80, maxmemory=100, ratio=0.9) is False
    # unbounded Redis (no cap) → never critical
    assert is_redis_memory_critical(used=10_000, maxmemory=0, ratio=0.9) is False
    assert is_redis_memory_critical(used=10_000, maxmemory=-1, ratio=0.9) is False


# ---------------------------------------------------------------------------
# TASK-100 — emit_ingest_staleness
# ---------------------------------------------------------------------------


def _staleness_session(age_s: float | None) -> MagicMock:
    mock_session = MagicMock(name="session")
    row = MagicMock()
    row._mapping = {"age_s": age_s}
    result = MagicMock()
    result.one.return_value = row
    mock_session.execute.return_value = result
    return mock_session


def test_emit_ingest_staleness_stale_when_old() -> None:
    from observability.signal_latency import emit_ingest_staleness

    settings = MagicMock()
    settings.ingest_staleness_alert_seconds = 1800
    out = emit_ingest_staleness(_staleness_session(2000.0), settings)
    assert out["stale"] is True
    assert out["age_s"] == 2000.0
    assert out["threshold_s"] == 1800


def test_emit_ingest_staleness_fresh_when_recent() -> None:
    from observability.signal_latency import emit_ingest_staleness

    settings = MagicMock()
    settings.ingest_staleness_alert_seconds = 1800
    out = emit_ingest_staleness(_staleness_session(120.0), settings)
    assert out["stale"] is False


def test_emit_ingest_staleness_empty_corpus_not_stale() -> None:
    """NULL MAX(fetched_at) (no posts yet, cold start) must NOT alert."""
    from observability.signal_latency import emit_ingest_staleness

    settings = MagicMock()
    settings.ingest_staleness_alert_seconds = 1800
    out = emit_ingest_staleness(_staleness_session(None), settings)
    assert out["stale"] is False
    assert out["age_s"] is None


# ---------------------------------------------------------------------------
# TASK-100 — redis_memory_alert_ratio validator
# ---------------------------------------------------------------------------


def test_redis_memory_alert_ratio_validator() -> None:
    from pydantic import ValidationError

    from config import Settings

    assert Settings(redis_memory_alert_ratio=0.5).redis_memory_alert_ratio == 0.5
    assert Settings(redis_memory_alert_ratio=1.0).redis_memory_alert_ratio == 1.0
    for bad in (0.0, -0.1, 1.1, 2.0):
        with pytest.raises(ValidationError):
            Settings(redis_memory_alert_ratio=bad)


def test_ingest_staleness_alert_seconds_validator() -> None:
    from pydantic import ValidationError

    from config import Settings

    assert Settings(ingest_staleness_alert_seconds=60).ingest_staleness_alert_seconds == 60
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            Settings(ingest_staleness_alert_seconds=bad)


# ---------------------------------------------------------------------------
# TASK-100 — task-level alert wiring (emit_signal_latency_task -> notify_ops)
# ---------------------------------------------------------------------------


def test_task_fires_redis_alert_when_critical() -> None:
    """Redis near the cap -> the metric tick calls notify_ops('redis_memory_high')."""
    from observability import tasks

    with (
        patch.object(tasks, "get_session"),
        patch.object(tasks, "emit_signal_latency"),
        patch.object(tasks, "emit_alert_precision"),
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "emit_redis_memory", return_value={"used": 95, "peak": 95, "max": 100}),
        patch.object(tasks, "emit_ingest_staleness", return_value={"stale": False, "age_s": 1.0}),
        patch.object(tasks, "notify_ops") as notify,
    ):
        tasks.emit_signal_latency_task()

    reasons = [c.args[0] for c in notify.call_args_list]
    assert "redis_memory_high" in reasons
    assert "ingest_stale" not in reasons


def test_task_fires_ingest_alert_when_stale_only() -> None:
    """Ingest stale + Redis healthy -> only the ingest alert fires."""
    from observability import tasks

    with (
        patch.object(tasks, "get_session"),
        patch.object(tasks, "emit_signal_latency"),
        patch.object(tasks, "emit_alert_precision"),
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "emit_redis_memory", return_value={"used": 10, "peak": 10, "max": 100}),
        patch.object(tasks, "emit_ingest_staleness", return_value={"stale": True, "age_s": 2000.0}),
        patch.object(tasks, "notify_ops") as notify,
    ):
        tasks.emit_signal_latency_task()

    reasons = [c.args[0] for c in notify.call_args_list]
    assert "ingest_stale" in reasons
    assert "redis_memory_high" not in reasons


def test_task_no_alerts_when_all_healthy() -> None:
    """Healthy Redis + fresh ingest -> no ops alerts at all."""
    from observability import tasks

    with (
        patch.object(tasks, "get_session"),
        patch.object(tasks, "emit_signal_latency"),
        patch.object(tasks, "emit_alert_precision"),
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "emit_redis_memory", return_value={"used": 10, "peak": 10, "max": 100}),
        patch.object(tasks, "emit_ingest_staleness", return_value={"stale": False, "age_s": 5.0}),
        patch.object(tasks, "notify_ops") as notify,
    ):
        tasks.emit_signal_latency_task()

    notify.assert_not_called()
