"""Observability Celery tasks (TASK-036): signal-latency + Redis memory metric.

Beat task ``emit_signal_latency_task`` fires every
``settings.latency_emit_interval_seconds`` (default 300s).  It:

1. Opens a DB session and calls ``emit_signal_latency`` (p50/p95 for both cuts).
2. Gets a Redis client and calls ``emit_redis_memory`` (used/peak/maxmemory).

Each part is wrapped best-effort so a DB failure does not prevent the Redis
metric and vice-versa.  Failures are logged as warnings (exc type only — no
raw content, no secrets).

Task args: none (no JSON args needed — Invariant: JSON-serializable args only).
Routed to default ``celery`` queue (no explicit route → no compose change).

Import note: this module imports ``celery_app`` (Celery task registration),
but NOT ``alerts.tasks`` or ``pipeline.tasks``, keeping the dependency graph
clean.  ``observability.signal_latency`` does NOT import ``celery_app``, so it
remains safe to import from tests and the API process.
"""

import logging

from celery_app import celery_app
from config import get_settings
from observability.constants import EMIT_SIGNAL_LATENCY_TASK
from observability.pool_health import notify_ops
from observability.signal_latency import (
    emit_alert_precision,
    emit_ingest_staleness,
    emit_redis_memory,
    emit_signal_latency,
    is_redis_memory_critical,
    publish_ingest_staleness,
)
from storage.database import get_session
from storage.redis_client import get_redis_client

logger = logging.getLogger(__name__)


@celery_app.task(name=EMIT_SIGNAL_LATENCY_TASK)
def emit_signal_latency_task() -> None:
    """Beat task: emit signal-latency p50/p95 + Redis memory stats.

    Best-effort: DB and Redis parts run independently so one failure cannot
    suppress the other metric.  Logs warnings with exc type only (no secrets,
    no raw content).

    Scheduled via ``scheduler.beat_schedule`` at
    ``settings.latency_emit_interval_seconds`` (default 300s).
    """
    settings = get_settings()

    # --- Part 1: DB percentile metric ---
    try:
        with get_session() as session:
            emit_signal_latency(session, settings)
    except Exception as exc:
        logger.warning(
            "emit_signal_latency_task: DB metric failed",
            extra={"exc_type": type(exc).__name__},
        )

    # --- Part 2: Redis memory metric (+ near-cap ops alert, TASK-100) ---
    try:
        redis = get_redis_client()
        mem = emit_redis_memory(redis)
        used = mem.get("used", 0)
        maxmemory = mem.get("max", 0)
        if (
            isinstance(used, int)
            and isinstance(maxmemory, int)
            and is_redis_memory_critical(used, maxmemory, settings.redis_memory_alert_ratio)
        ):
            pct = used / maxmemory * 100 if maxmemory else 0
            notify_ops(
                "redis_memory_high",
                f"Redis memory {pct:.0f}% of cap ({used} / {maxmemory} bytes) - "
                "approaching the noeviction limit; broker writes will be rejected at 100%.",
                settings,
                redis,
            )
    except Exception as exc:
        logger.warning(
            "emit_signal_latency_task: Redis metric failed",
            extra={"exc_type": type(exc).__name__},
        )

    # --- Part 3: Alert precision per user (TASK-042) — best-effort. ---
    # Computes up/(up+down) for each user's rated alerts in the 7d window and
    # emits log_event("alert_precision", ...) per user.  DB failure is logged
    # as a warning and does not interrupt the other metrics above.
    try:
        with get_session() as session:
            emit_alert_precision(session, settings)
    except Exception as exc:
        logger.warning(
            "emit_signal_latency_task: alert_precision metric failed",
            extra={"exc_type": type(exc).__name__},
        )

    # --- Part 4: Ingest staleness (+ ops alert, TASK-100) — best-effort. ---
    # Alerts when no post has been ingested for `ingest_staleness_alert_seconds`
    # (dead pool / undrained buffer / wedged collector). Empty corpus (NULL) → no alert.
    try:
        with get_session() as session:
            ingest = emit_ingest_staleness(session, settings)
        # Bridge the latest {stale, age_s} to Redis so the collector's pool-health
        # snapshot can derive the ingest-contradiction flag cross-process (TASK-118),
        # without a Postgres query on the hot collect-tick path. Best-effort.
        publish_ingest_staleness(get_redis_client(), ingest)
        if ingest.get("stale"):
            age_s = ingest.get("age_s")
            age_min = int(float(age_s) // 60) if isinstance(age_s, (int, float)) else "?"
            notify_ops(
                "ingest_stale",
                f"Ingest stalled - no post ingested for ~{age_min} min "
                f"(threshold {settings.ingest_staleness_alert_seconds // 60} min). "
                "Check the TG pool / collector / raw buffer.",
                settings,
                get_redis_client(),
            )
    except Exception as exc:
        logger.warning(
            "emit_signal_latency_task: ingest_staleness metric failed",
            extra={"exc_type": type(exc).__name__},
        )
