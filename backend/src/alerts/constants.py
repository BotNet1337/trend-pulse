"""Alert orchestration constants (task names) — import-cycle-free.

Lives apart from `alerts.tasks` (which imports `celery_app`) so `scheduler`
can reference the resweep task name in `beat_schedule` without a circular
import (mirrors `compliance.constants` / `pipeline.constants`).
"""

# Celery task name for the pending-alert re-sweep (task-023). Routed to no
# explicit queue → lands on the default `celery` queue the worker already
# consumes (same approach as `compliance.tasks.purge_expired_raw_content`).
RESWEEP_PENDING_ALERTS_TASK = "alerts.tasks.resweep_pending_alerts"
