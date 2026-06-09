"""Observability task constants — import-cycle-free leaf module.

This module MUST NOT import `celery_app` or any module that imports it.
`scheduler.py` imports this file; if it imported `celery_app` → cycle
(same pattern as `alerts.constants`, `compliance.constants`, `billing.constants`).
Only stdlib / string constants here.
"""

# Celery task name for the signal-latency + redis-memory emit (TASK-036).
# Routed to no explicit queue → lands on the default `celery` queue the worker
# already consumes (same pattern as compliance / billing tasks, no compose change).
EMIT_SIGNAL_LATENCY_TASK: str = "observability.tasks.emit_signal_latency_task"
