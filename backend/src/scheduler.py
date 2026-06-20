"""Celery Beat schedule (ADR-002): per-user batch dispatch + scorer tick.

Beat enqueues active-user batches every `BATCH_INTERVAL_SECONDS` (the dispatcher
fans them out to per-user `batch:user_{id}` queues) and fires the scorer tick
every `SCORER_INTERVAL_SECONDS`. Intervals come from settings, never magic
literals (CONVENTIONS). Kept in its own module so `celery_app` imports it without
a cycle; task *names* come from `pipeline.constants` (no `celery_app` import).
"""

import logging

from celery.beat import PersistentScheduler
from redis import RedisError

from alerts.constants import RESWEEP_PENDING_ALERTS_TASK
from analytics.constants import AGGREGATE_BUSINESS_METRICS_TASK
from billing.constants import CHECK_EXPIRING_SUBSCRIPTIONS_TASK
from collector.constants import COLLECT_TICK_TASK
from compliance.constants import PURGE_EXPIRED_RAW_CONTENT_TASK
from config import get_settings
from factory.constants import FACTORY_TICK_TASK
from notifications.constants import SEND_LIFECYCLE_EMAILS_TASK
from observability.constants import EMIT_SIGNAL_LATENCY_TASK
from pipeline.constants import ENQUEUE_BATCHES_TASK, SCORE_TICK_TASK
from scorer.constants import ADAPT_THRESHOLDS_TASK
from showcase.constants import SHOWCASE_AUTOPOST_TASK
from storage.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_settings = get_settings()

# Redis key the beat scheduler stamps on every tick (TASK-098). Beat is the SINGLE
# scheduler (replicas:1); a hung beat freezes every periodic task. `inspect ping`
# only probes workers, so beat needs its own liveness signal — this key, with a TTL
# greater than beat's max_interval, vanishes only if beat stops ticking.
BEAT_HEARTBEAT_KEY = "beat:heartbeat"


class HeartbeatScheduler(PersistentScheduler):
    """PersistentScheduler that stamps a TTL'd Redis heartbeat on every tick.

    Wired via `celery -A celery_app beat --scheduler scheduler:HeartbeatScheduler`.
    The heartbeat is written by BEAT ITSELF (not a worker-run task) so the signal is
    beat-only and does not conflate worker health. The beat container's Docker
    healthcheck checks `BEAT_HEARTBEAT_KEY` existence; the TTL
    (`beat_heartbeat_ttl_seconds` > 300s max_interval) is the freshness window, so no
    clock arithmetic is needed in the probe.
    """

    # PersistentScheduler.__init__ forwards *args/**kwargs to Scheduler(app, ...);
    # `object` (not Any) keeps the passthrough real-typed without re-stating Celery's
    # internal constructor signature.
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._redis = get_redis_client()
        self._heartbeat_ttl: int = _settings.beat_heartbeat_ttl_seconds

    # Override accepts *args/**kwargs (real `object`, not Any) only to stay
    # Liskov-compatible with the base's optional params; Celery's beat Service always
    # calls `tick()` with NO arguments, so we delegate to `super().tick()` and let the
    # base use its own internal defaults (event_t/min/heappush).
    def tick(self, *args: object, **kwargs: object) -> float:
        # Best-effort heartbeat: a Redis blip must NEVER crash the scheduler loop
        # (enqueuing periodic tasks matters more), so catch RedisError, log, continue.
        try:
            self._redis.set(BEAT_HEARTBEAT_KEY, "1", ex=self._heartbeat_ttl)
        except RedisError:
            logger.warning("beat heartbeat write failed (Redis); continuing tick", exc_info=True)
        return super().tick()


# Mapping of schedule entry name -> celery beat entry config. Beat entries are
# heterogeneous (schedule float/seconds, task name, args/kwargs), so the value
# type is `dict[str, object]` rather than a bare `Any`.
beat_schedule: dict[str, dict[str, object]] = {
    # Ingest tick (launch-blocker fix): read every watched source via the
    # collector registry into the by-source raw buffer the per-user batch
    # drains. MUST tick at least as often as the batch (config validator) —
    # without this entry every batch is a `no-op (empty buffer)` and trending
    # stays `warming_up` forever. Overlap is prevented by the global Redis
    # collect lock (max_instances=1 — one Telethon pool, FLOOD_WAIT safety).
    "collect-tick": {
        "task": COLLECT_TICK_TASK,
        "schedule": float(_settings.collect_interval_seconds),
    },
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
    # Lifecycle emails (TASK-069): daily tick scanning verified, non-opted-out
    # users for a due weekly digest / win-back. Due-selection is driven by
    # per-user `digest_last_sent_at`/`winback_last_sent_at` DB state, so the
    # tick is idempotent across restarts and interval drift (TASK-027 pattern).
    # Unrouted → default `celery` queue the worker already consumes.
    "lifecycle-emails-tick": {
        "task": SEND_LIFECYCLE_EMAILS_TASK,
        "schedule": float(_settings.lifecycle_email_interval_seconds),
    },
    # Business-metrics daily aggregate (TASK-050): compute funnel counters
    # (registrations, packs_attached, first_alerts_delivered, first_feedback,
    # new_paid, churned, active_paid) from source-of-truth DB tables and upsert
    # into business_metrics_daily. Default 86400s = once per day. Idempotent
    # (ON CONFLICT upsert) — a double-tick or restart is always safe.
    "aggregate-business-metrics": {
        "task": AGGREGATE_BUSINESS_METRICS_TASK,
        "schedule": float(_settings.business_metrics_interval_seconds),
    },
    # Account-factory tick (TASK-134): top up the live pool when below target within a
    # hard USD budget (buy → register → probation → promote with source='auto'). A no-op
    # when `account_factory_provider` is unset/empty (provider-driven activation) and the
    # budget hard-cap refuses every buy at the default $0 budget. Unrouted → default
    # `celery` queue the worker already consumes (no compose change).
    "factory-tick": {
        "task": FACTORY_TICK_TASK,
        "schedule": float(_settings.account_factory_tick_interval_seconds),
    },
}
