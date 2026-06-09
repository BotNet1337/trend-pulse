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
from observability.signal_latency import emit_redis_memory, emit_signal_latency
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

    # --- Part 2: Redis memory metric ---
    try:
        redis = get_redis_client()
        emit_redis_memory(redis)
    except Exception as exc:
        logger.warning(
            "emit_signal_latency_task: Redis metric failed",
            extra={"exc_type": type(exc).__name__},
        )
