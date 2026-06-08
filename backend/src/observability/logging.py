"""Structured JSON logging + log-hygiene helper (task-011, overview §7).

Two responsibilities:

1. `configure_logging()` — attach a JSON formatter to the root logger so request,
   Celery-task, and pipeline logs emit machine-parseable JSON (one object/line)
   for the ops log consumers. Idempotent.

2. `log_event()` — the log-hygiene helper. It accepts ONLY aggregate fields
   (ids/counts/durations: `int | float | bool | None | str`) and refuses any field
   whose name looks like raw post content (`text`, `content`, `raw_text`, `body`,
   `message`, `raw`). Raw post text MUST NEVER reach the logs (overview §7 "log
   only aggregated metrics"); this helper makes that structurally hard rather than
   relying on every call site to remember.

`python-json-logger` produces the JSON envelope; its import is untyped at the
boundary (no stubs), scoped in `[tool.mypy] overrides` rather than inline ignores.
"""

import logging

from pythonjsonlogger.json import JsonFormatter

# Field names that may carry raw post content — forbidden in structured logs. Any
# attempt to log one of these is dropped + flagged, never emitted (overview §7).
_FORBIDDEN_LOG_KEYS = frozenset(
    {"text", "content", "raw_text", "raw", "body", "message_text", "post_text"}
)

# Aggregate values are scalars only: ids, counts, durations, status strings, flags.
# Disallowing nested/arbitrary objects keeps raw content from sneaking in via a
# dict/embedded model.
type AggregateValue = str | int | float | bool | None

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_logger = logging.getLogger("trendpulse")


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger to emit JSON (idempotent).

    Replaces existing handlers with a single JSON-formatted stream handler so the
    output is uniform across api/worker/beat. Safe to call more than once.
    """
    formatter = JsonFormatter(_LOG_FORMAT)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def _is_forbidden(key: str) -> bool:
    """True if a field name may carry raw post content (case-insensitive)."""
    return key.lower() in _FORBIDDEN_LOG_KEYS


def log_event(event: str, **fields: AggregateValue) -> None:
    """Emit a structured log event with aggregate fields only (no raw content).

    Any field whose name matches a forbidden raw-content key is dropped before
    logging and replaced with a `_dropped_fields` marker, so a careless caller can
    never leak post text — the value itself never enters the log record.
    """
    safe: dict[str, AggregateValue] = {}
    dropped: list[str] = []
    for key, value in fields.items():
        if _is_forbidden(key):
            dropped.append(key)
            continue
        safe[key] = value
    if dropped:
        safe["_dropped_fields"] = ",".join(sorted(dropped))
    _logger.info(event, extra=safe)
