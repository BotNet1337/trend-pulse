"""Celery task for the hourly raw-content retention sweep (task-011).

`purge_expired_raw_content_task` takes no args (id-only contract — CONVENTIONS:
JSON-serializable args, never ORM objects), runs the purge inside a committing
session, and logs ONLY the aggregate count purged via the hygiene logger (never
raw text). Routed to the default `celery` queue the worker already consumes
(no explicit route → no compose change), like `alerts.tasks.dispatch_alert`.

`celery_app` includes this module at worker startup, binding the task.
"""

from celery_app import celery_app
from compliance.constants import PURGE_EXPIRED_RAW_CONTENT_TASK
from compliance.retention import purge_expired_raw_content
from observability.logging import log_event
from storage.database import get_session


@celery_app.task(name=PURGE_EXPIRED_RAW_CONTENT_TASK)
def purge_expired_raw_content_task() -> int:
    """Sweep expired raw post text; return the count purged (logged as an aggregate)."""
    with get_session() as session:
        purged = purge_expired_raw_content(session)
    log_event("retention.purge", purged=purged)
    return purged
