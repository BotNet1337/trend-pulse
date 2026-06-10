"""Showcase autoposting constants — task name (leaf, no celery import).

Lives in its own module (pattern: scorer/constants.py, alerts/constants.py)
so `scheduler.py` can reference the task name in `beat_schedule` without a
circular import through `celery_app`.
"""

# Celery task name for the showcase autopost beat task (TASK-044).
# No explicit queue route → lands on the default `celery` queue the worker
# already consumes (same approach as compliance/billing/observability tasks).
SHOWCASE_AUTOPOST_TASK: str = "showcase.tasks.showcase_autopost_tick"
