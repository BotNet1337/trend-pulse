"""Celery Beat schedule (ADR-002): per-user batch dispatch + scorer tick.

Beat enqueues active-user batches every `BATCH_INTERVAL_SECONDS` (the dispatcher
fans them out to per-user `batch:user_{id}` queues) and fires the scorer tick
every `SCORER_INTERVAL_SECONDS`. Intervals come from settings, never magic
literals (CONVENTIONS). Kept in its own module so `celery_app` imports it without
a cycle; task *names* come from `pipeline.constants` (no `celery_app` import).
"""

from alerts.constants import RESWEEP_PENDING_ALERTS_TASK
from billing.constants import CHECK_EXPIRING_SUBSCRIPTIONS_TASK
from compliance.constants import PURGE_EXPIRED_RAW_CONTENT_TASK
from config import get_settings
from observability.constants import EMIT_SIGNAL_LATENCY_TASK
from pipeline.constants import ENQUEUE_BATCHES_TASK, SCORE_TICK_TASK
from scorer.constants import ADAPT_THRESHOLDS_TASK
from showcase.constants import SHOWCASE_AUTOPOST_TASK

_settings = get_settings()

# Mapping of schedule entry name -> celery beat entry config. Beat entries are
# heterogeneous (schedule float/seconds, task name, args/kwargs), so the value
# type is `dict[str, object]` rather than a bare `Any`.
beat_schedule: dict[str, dict[str, object]] = {
    "enqueue-active-user-batches": {
        "task": ENQUEUE_BATCHES_TASK,
        "schedule": float(_settings.batch_interval_seconds),
    },
    "score-tick": {
        "task": SCORE_TICK_TASK,
        "schedule": float(_settings.scorer_interval_seconds),
    },
    # Hourly raw-content retention sweep (task-011): NULL `posts.text` past the 48h
    # window. Lands on the default `celery` queue the worker consumes (no route).
    "purge-expired-raw-content": {
        "task": PURGE_EXPIRED_RAW_CONTENT_TASK,
        "schedule": float(_settings.retention_purge_interval_seconds),
    },
    # Pending-alert re-sweep (task-023): re-enqueue dispatch_alert for any
    # `pending` alert older than `pending_resweep_grace_seconds`. Closes the
    # reliability footgun where a broker/worker crash leaves alerts stuck in
    # `pending` forever. Interval from settings, never a magic literal.
    "resweep-pending-alerts": {
        "task": RESWEEP_PENDING_ALERTS_TASK,
        "schedule": float(_settings.pending_resweep_interval_seconds),
    },
    # Renewal notifications (task-027): scan subscriptions expiring within
    # RENEWAL_REMINDER_DAYS (7/3/1) and send idempotent renewal reminder emails.
    # Runs once per day (default) — sufficient for day-granularity reminder windows.
    "check-expiring-subscriptions": {
        "task": CHECK_EXPIRING_SUBSCRIPTIONS_TASK,
        "schedule": float(_settings.renewal_check_interval_seconds),
    },
    # Signal latency + Redis memory metric (task-036): emit p50/p95 for delivered
    # alerts (e2e and delivery cuts) plus Redis INFO memory. Read-only, lightweight
    # (single SQL aggregate + Redis INFO). Default every 300s, window default 3600s.
    "emit-signal-latency": {
        "task": EMIT_SIGNAL_LATENCY_TASK,
        "schedule": float(_settings.latency_emit_interval_seconds),
    },
    # Adaptive threshold adaptation (TASK-043): for users with ≥K 👎 ratings in
    # the 7d window, shifts per-user watchlist thresholds up/down by a fixed step.
    # Rate-guard + group-guard in scorer/tasks.py gate alert CREATION separately.
    # Default interval 21600s = 6h — slow feedback loop by design.
    "adapt-thresholds": {
        "task": ADAPT_THRESHOLDS_TASK,
        "schedule": float(_settings.threshold_adapt_interval_seconds),
    },
    # Showcase autopost (TASK-044): post best showcase-tenant cluster to the
    # public TG channel with delay + CTA + anti-spam. Default every 900s (15 min).
    # Empty showcase_bot_token / showcase_channel_chat_id → task is a no-op
    # (graceful degradation — deploy without the showcase channel is valid).
    "showcase-autopost": {
        "task": SHOWCASE_AUTOPOST_TASK,
        "schedule": float(_settings.showcase_post_interval_seconds),
    },
}
