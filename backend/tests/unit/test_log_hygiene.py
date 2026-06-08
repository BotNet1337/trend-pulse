"""AC5: the hygiene logger emits aggregates but NEVER raw post text.

Captures the emitted log records and asserts a unique raw-text marker does not
appear anywhere in the output, while aggregate fields (ids/counts/durations) do.
"""

import logging

import pytest

from observability.logging import log_event

_MARKER = "VIRAL_RAW_TEXT_MARKER_must_never_be_logged"


@pytest.fixture
def caplog_json(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="trendpulse")
    return caplog


def test_aggregate_fields_are_logged(caplog_json: pytest.LogCaptureFixture) -> None:
    log_event("pipeline.batch", user_id=7, posts=3, clusters=1, duration_ms=12.5)
    record = caplog_json.records[-1]
    assert record.user_id == 7  # type: ignore[attr-defined]
    assert record.posts == 3  # type: ignore[attr-defined]
    assert record.clusters == 1  # type: ignore[attr-defined]


def test_forbidden_text_field_is_dropped(caplog_json: pytest.LogCaptureFixture) -> None:
    # A careless caller tries to log raw post text under a forbidden key.
    log_event("pipeline.post", post_id=99, text=_MARKER, content=_MARKER)

    record = caplog_json.records[-1]
    # The raw marker must not appear anywhere on the record (message or extras).
    serialized = " ".join(f"{k}={v}" for k, v in vars(record).items())
    assert _MARKER not in serialized
    # The aggregate id survives; the dropped keys are flagged, not their values.
    assert record.post_id == 99  # type: ignore[attr-defined]
    assert "content" in record._dropped_fields  # type: ignore[attr-defined]
    assert "text" in record._dropped_fields  # type: ignore[attr-defined]
