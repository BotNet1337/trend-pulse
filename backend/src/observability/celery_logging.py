"""Celery task lifecycle logging via signals (task-011, overview §7).

Connects `task_prerun`/`task_postrun` to emit structured, aggregate-only events:
task name, task id, state, and duration. NEVER logs task args/kwargs or return
values — those could carry raw content; only the metadata shape + timing. Wire it
once at worker startup by calling `register_celery_logging()`.
"""

import time
from typing import cast

from celery.signals import task_postrun, task_prerun

from observability.logging import log_event

_MS_PER_SECOND = 1000
# task_id -> monotonic start time, set in prerun and consumed in postrun.
_starts: dict[str, float] = {}


def _on_prerun(task_id: str | None = None, **_: object) -> None:
    """Record the task start time keyed by id (aggregate bookkeeping only)."""
    if task_id is not None:
        _starts[task_id] = time.perf_counter()


def _on_postrun(
    task_id: str | None = None,
    task: object = None,
    state: str | None = None,
    **_: object,
) -> None:
    """Emit one aggregate event with the task name, state, and duration."""
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


def register_celery_logging() -> None:
    """Connect the task signals (idempotent: Celery dedupes identical receivers)."""
    task_prerun.connect(_on_prerun, weak=False)
    task_postrun.connect(_on_postrun, weak=False)
