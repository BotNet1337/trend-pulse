"""Orchestration contract constants (task names + queues) — import-cycle-free.

Lives apart from `pipeline.tasks` (which imports `celery_app`) so `scheduler` and
`celery_app` can reference task names / queue names without a circular import.
"""

# Celery task names — the orchestration contract consumed by routes + beat.
RUN_USER_BATCH_TASK = "pipeline.tasks.run_user_batch"
ENQUEUE_BATCHES_TASK = "pipeline.tasks.enqueue_active_user_batches"
SCORE_TICK_TASK = "pipeline.tasks.score_tick"

# Batch queue. ADR-002 envisioned per-user queues (`batch:user_{id}`), but dynamic
# per-tenant queues can't be consumed by a static worker `-Q` and would accumulate
# unconsumed. The per-USER `max_instances=1` isolation is instead enforced by the
# Redis per-user lock (pipeline.locks), so batches share ONE consumable `batch`
# queue and the lock serializes each user; workers scale on this queue.
# (Refinement of ADR-002 §2 — see task-006 Details.)
BATCH_QUEUE = "batch"
# Static scorer queue (ADR-002 §2): a single global tick, not per-tenant.
SCORE_QUEUE = "score:global"
