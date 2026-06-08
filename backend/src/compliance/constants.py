"""Compliance orchestration constants (task name) — import-cycle-free.

Lives apart from `compliance.tasks` (which imports `celery_app`) so `scheduler`
can reference the purge task name in `beat_schedule` without a circular import
(mirrors `pipeline.constants`).
"""

# Celery task name for the hourly raw-content retention sweep (task-011). Routed
# to no explicit queue → lands on the default `celery` queue the worker already
# consumes (no compose change), same approach as `alerts.tasks.dispatch_alert`.
PURGE_EXPIRED_RAW_CONTENT_TASK = "compliance.tasks.purge_expired_raw_content"
