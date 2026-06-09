"""Celery task lifecycle logging via signals (task-011, overview §7; TASK-024 AC5).

Connects ``task_prerun``/``task_postrun`` to emit structured, aggregate-only events:
task name, task id, state, and duration. NEVER logs task args/kwargs or return
values — those could carry raw content; only the metadata shape + timing. Wire it
once at worker startup by calling ``register_celery_logging()``.

TASK-024 -- cross-process trace-id via Celery:
- ``before_task_publish``: publisher reads the current ``request_id`` contextvar
  and stores it in the task's AMQP headers so the receiving worker can inherit it.
- ``task_prerun``: inherit the id from task headers if present; otherwise generate
  a fresh trace id (Beat-initiated chains get their own independent trace).
- ``task_postrun``: reset the contextvar so the id never leaks to the next task
  on the same worker thread/process (Celery prefork safety).
"""

import time
from contextvars import Token
from typing import cast

from celery.signals import (
    before_task_publish,
    setup_logging,
    task_postrun,
    task_prerun,
)

from observability.context import (
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from observability.logging import configure_logging, log_event

_MS_PER_SECOND = 1000
# task_id -> monotonic start time, set in prerun and consumed in postrun.
_starts: dict[str, float] = {}
# task_id -> contextvar reset token (so postrun can clean up exactly what prerun set).
_tokens: dict[str, Token[str | None]] = {}

# Header key used to propagate the trace id across AMQP messages.
_TRACE_HEADER = "x_request_id"


def _on_publish(headers: dict[str, object] | None = None, **_: object) -> None:
    """Before a task is published: inject the current request_id into headers.

    Called by the ``before_task_publish`` signal on the *publisher* side (API
    process or another worker).  If there is no active request context the
    header is simply omitted — the receiving worker will generate a new id.
    """
    rid = get_request_id()
    if headers is not None and rid is not None:
        headers[_TRACE_HEADER] = rid


def _on_prerun(
    task_id: str | None = None,
    task: object = None,
    **_: object,
) -> None:
    """Record task start time and bind the trace id into the contextvar.

    Reads the ``x_request_id`` value from the Celery task request headers (set by
    ``_on_publish`` on the publisher side).  If absent (Beat-initiated chain)
    a fresh uuid4 is generated so the entire Beat-→scorer→dispatch_alert→notifier
    chain shares one trace id.
    """
    if task_id is not None:
        _starts[task_id] = time.perf_counter()

    # Inherit or generate trace id.
    rid: str | None = None
    if task is not None:
        task_request = getattr(task, "request", None)
        if task_request is not None:
            rid = cast(str | None, getattr(task_request, _TRACE_HEADER, None))
    if rid is None:
        rid = new_request_id()

    if task_id is not None:
        token = set_request_id(rid)
        _tokens[task_id] = token


def _on_postrun(
    task_id: str | None = None,
    task: object = None,
    state: str | None = None,
    **_: object,
) -> None:
    """Emit one aggregate event with the task name, state, and duration; clear trace."""
    start = _starts.pop(task_id, None) if task_id is not None else None
    duration_ms = (
        round((time.perf_counter() - start) * _MS_PER_SECOND, 2) if start is not None else None
    )
    task_name = cast(str | None, getattr(task, "name", None))
    log_event(
        "celery.task",
        task=task_name,
        task_id=task_id,
        state=state,
        duration_ms=duration_ms,
    )

    # Reset the trace contextvar so the id cannot bleed into the next task on
    # this worker (Celery prefork: each child handles tasks serially, so this
    # clear is sufficient for process-pool isolation).
    if task_id is not None:
        token = _tokens.pop(task_id, None)
        if token is not None:
            reset_request_id(token)


def _on_setup_logging(**_: object) -> None:
    """Own the worker/beat logging config (TASK-024).

    Celery hijacks the root logger at worker/beat startup, which would overwrite the
    JSON handler + `RequestIdFilter` that `configure_logging()` installed at import
    time — worker logs would revert to Celery's text format with no `request_id`.
    Connecting a receiver to `setup_logging` tells Celery NOT to configure logging
    itself and to leave it to us, so our JSON shape + trace id survive in the worker.
    """
    configure_logging()


def register_celery_logging() -> None:
    """Connect the task signals (idempotent: Celery dedupes identical receivers)."""
    setup_logging.connect(_on_setup_logging, weak=False)
    before_task_publish.connect(_on_publish, weak=False)
    task_prerun.connect(_on_prerun, weak=False)
    task_postrun.connect(_on_postrun, weak=False)
