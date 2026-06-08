"""Celery Beat schedule definition.

Empty skeleton for task-001; periodic tasks (collection, scoring) are wired in
later tasks. Kept in its own module so `celery_app` can import it without a cycle.
"""

# Mapping of schedule entry name -> celery beat entry config.
# Beat entries are heterogeneous (schedule object, task name, args/kwargs), so the
# value type is `dict[str, object]` rather than a bare `Any`; concrete entries
# (collection, scoring) arrive in later tasks.
beat_schedule: dict[str, dict[str, object]] = {}
