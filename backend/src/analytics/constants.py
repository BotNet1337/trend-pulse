"""Analytics constants — import-cycle-free leaf module (TASK-050).

This module MUST NOT import `celery_app` or any module that imports it.
`scheduler.py` imports this file; if it imported `celery_app` → cycle
(same pattern as `alerts.constants`, `compliance.constants`, `billing.constants`,
`observability.constants`). Only stdlib / string constants here.

Funnel event names: owned by analytics (business domain), not by observability
(technical domain). The names follow the `funnel.<action>` convention from the
task Discussion doc.
"""

# Celery task name for the daily business-metrics aggregate (TASK-050).
# Routed to no explicit queue → lands on the default `celery` queue the worker
# already consumes (same pattern as compliance / billing tasks, no compose change).
AGGREGATE_BUSINESS_METRICS_TASK: str = "analytics.tasks.aggregate_business_metrics"

# Funnel event names — emitted via log_event() at 4 hook points (TASK-050 AC1).
# These are real-time observability breadcrumbs; the aggregate is computed
# from tables (not from logs). Named constants — no magic strings at call sites.
FUNNEL_USER_REGISTERED: str = "funnel.user_registered"
FUNNEL_PACK_ATTACHED: str = "funnel.pack_attached"
FUNNEL_ALERT_DELIVERED: str = "funnel.alert_delivered"
FUNNEL_FEEDBACK_GIVEN: str = "funnel.feedback_given"
