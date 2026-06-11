"""Analytics package — business-metrics aggregation (TASK-050).

Provides:
- constants: task name + funnel event name constants.
- aggregate: compute_day() pure SQL aggregates + upsert_row() for idempotent upsert.
- tasks: Celery beat task that computes yesterday + today (partial).
"""
