"""Scorer orchestration constants (task names) — import-cycle-free.

Lives apart from ``scorer.adaptation`` (which imports ``celery_app``) so
``scheduler`` can reference the adapt-thresholds task name in ``beat_schedule``
without a circular import (same pattern as ``alerts.constants``,
``compliance.constants``, ``pipeline.constants``).
"""

# Celery task name for the adaptive threshold beat task (TASK-043).
# Routed to no explicit queue → lands on the default ``celery`` queue the
# worker already consumes (no compose change, same approach as compliance/
# billing/observability tasks).
ADAPT_THRESHOLDS_TASK: str = "scorer.adaptation.adapt_thresholds_task"
