"""Celery Beat schedule (ADR-002): per-user batch dispatch + scorer tick.

Beat enqueues active-user batches every `BATCH_INTERVAL_SECONDS` (the dispatcher
fans them out to per-user `batch:user_{id}` queues) and fires the scorer tick
every `SCORER_INTERVAL_SECONDS`. Intervals come from settings, never magic
literals (CONVENTIONS). Kept in its own module so `celery_app` imports it without
a cycle; task *names* come from `pipeline.constants` (no `celery_app` import).
"""

from config import get_settings
from pipeline.constants import ENQUEUE_BATCHES_TASK, SCORE_TICK_TASK

_settings = get_settings()

# Mapping of schedule entry name -> celery beat entry config. Beat entries are
# heterogeneous (schedule float/seconds, task name, args/kwargs), so the value
# type is `dict[str, object]` rather than a bare `Any`.
beat_schedule: dict[str, dict[str, object]] = {
    "enqueue-active-user-batches": {
        "task": ENQUEUE_BATCHES_TASK,
        "schedule": float(_settings.batch_interval_seconds),
    },
    "score-tick": {
        "task": SCORE_TICK_TASK,
        "schedule": float(_settings.scorer_interval_seconds),
    },
}
