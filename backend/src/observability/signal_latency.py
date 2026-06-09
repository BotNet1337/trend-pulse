"""Signal latency p50/p95 metric + Redis memory watch (TASK-036).

Two public functions:

- ``emit_signal_latency(session, settings) -> dict[str, object]``
  Computes p50/p95 in SECONDS for delivered alerts within a sliding window,
  in two cuts:
  - **e2e**: ``delivered_at - min(posted_at)`` of cluster posts (product metric).
  - **delivery**: ``delivered_at - alert.first_seen`` (diagnostic metric).
  Uses a single SQL query with PERCENTILE_CONT WITHIN GROUP and GREATEST(…, 0)
  clamping to handle source-clock skew. Logs aggregates-only via ``log_event``.
  Returns the aggregates dict.

- ``emit_redis_memory(redis) -> dict[str, object]``
  Reads ``INFO memory`` from Redis and emits ``log_event("redis_memory", …)``.
  Best-effort: warns and returns ``{}`` on any Redis error, never raises.

Design notes:
- Read-only: no rows are written or mutated (Invariant).
- Aggregates-only in logs — compliance §7.
- Never raises on empty data or Redis unavailability (Invariant).
- Import-safe: does NOT import ``celery_app`` or ``alerts.tasks`` — can be
  imported from any context (tests, API, beat worker) without cycles.
- TASK-040 ``deliver_after`` field not yet merged → no filter applied (Discussion).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from observability.logging import log_event
from storage.models.alerts import DELIVERY_STATUS_DELIVERED

if TYPE_CHECKING:
    from redis import Redis

    from config import Settings

logger = logging.getLogger(__name__)

# Column label names produced by the SQL query — named constants, not magic strings.
_COL_E2E_P50 = "e2e_p50"
_COL_E2E_P95 = "e2e_p95"
_COL_DELIVERY_P50 = "delivery_p50"
_COL_DELIVERY_P95 = "delivery_p95"
_COL_CNT = "cnt"
_COL_CNT_NEGATIVE = "cnt_negative"

# PERCENTILE_CONT fractions — named constants, not magic literals.
_PERCENTILE_50 = 0.5
_PERCENTILE_95 = 0.95

# Redis INFO section for memory stats.
_REDIS_INFO_SECTION = "memory"


def _extract_seconds(value: object) -> float | None:
    """Convert a PERCENTILE_CONT result to float seconds.

    Postgres returns PERCENTILE_CONT over an EXTRACT(EPOCH …) expression as a
    ``float`` (or ``Decimal``).  Returns ``None`` when ``value`` is ``None``
    (empty window).

    We route through ``str()`` so that mypy is satisfied regardless of the
    concrete numeric type returned by the DB driver (float, Decimal, int).
    """
    if value is None:
        return None
    return float(str(value))


def emit_signal_latency(session: Session, settings: Settings) -> dict[str, object]:
    """Compute and log signal-latency aggregates for delivered alerts.

    Issues a single SQL query against ``alerts`` JOIN ``posts`` using
    ``PERCENTILE_CONT(0.5/0.95) WITHIN GROUP`` to avoid Python-side row
    iteration.  Negative deltas (source clock skew) are clamped to 0 via
    ``GREATEST(…, 0)`` inside the aggregate; ``count_negative`` is reported
    separately via a ``FILTER`` clause.

    The e2e cut uses a sub-select for ``min(posts.posted_at)`` per cluster so
    multiple posts per cluster are reduced to the earliest before joining with
    alerts.  Alerts for clusters with no posts are excluded from the e2e cut
    (the inner join on the subquery) but are still counted in the delivery cut.

    Args:
        session:  Open SQLAlchemy ``Session`` (caller manages lifecycle).
        settings: Application settings; reads ``latency_window_seconds``.

    Returns:
        Dict with keys: ``e2e_p50_s``, ``e2e_p95_s``, ``delivery_p50_s``,
        ``delivery_p95_s``, ``count``, ``count_negative``, ``window_s``.
    """
    window_seconds: int = settings.latency_window_seconds

    # Build the query using SQLAlchemy text() with named bind params.
    # The query structure:
    #
    # WITH min_post AS (
    #   SELECT cluster_id, MIN(posted_at) AS earliest_posted_at
    #   FROM posts
    #   WHERE cluster_id IS NOT NULL
    #   GROUP BY cluster_id
    # )
    # SELECT
    #   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
    #     GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)), 0)
    #   ) AS e2e_p50,
    #   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY
    #     GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)), 0)
    #   ) AS e2e_p95,
    #   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
    #     GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)), 0)
    #   ) AS delivery_p50,
    #   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY
    #     GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)), 0)
    #   ) AS delivery_p95,
    #   COUNT(*) AS cnt,
    #   COUNT(*) FILTER (WHERE
    #     (EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)) < 0)
    #     OR (EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)) < 0)
    #   ) AS cnt_negative
    # FROM alerts AS a
    # LEFT JOIN min_post AS mp ON mp.cluster_id = a.cluster_id
    # WHERE a.delivery_status = :status
    #   AND a.delivered_at IS NOT NULL
    #   AND a.delivered_at >= NOW() - INTERVAL ':window seconds'
    #
    # Note: INTERVAL construction with a bind param uses the Postgres
    # ``make_interval(secs => :n)`` function (avoids f-string SQL).

    sql = text(
        """
        WITH min_post AS (
            SELECT cluster_id, MIN(posted_at) AS earliest_posted_at
            FROM posts
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
        )
        SELECT
            PERCENTILE_CONT(:p50) WITHIN GROUP (ORDER BY
                GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)), 0)
            ) AS e2e_p50,
            PERCENTILE_CONT(:p95) WITHIN GROUP (ORDER BY
                GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)), 0)
            ) AS e2e_p95,
            PERCENTILE_CONT(:p50) WITHIN GROUP (ORDER BY
                GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)), 0)
            ) AS delivery_p50,
            PERCENTILE_CONT(:p95) WITHIN GROUP (ORDER BY
                GREATEST(EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)), 0)
            ) AS delivery_p95,
            COUNT(*) AS cnt,
            COUNT(*) FILTER (WHERE
                EXTRACT(EPOCH FROM (a.delivered_at - a.first_seen)) < 0
                OR (
                    mp.earliest_posted_at IS NOT NULL
                    AND EXTRACT(EPOCH FROM (a.delivered_at - mp.earliest_posted_at)) < 0
                )
            ) AS cnt_negative
        FROM alerts AS a
        LEFT JOIN min_post AS mp ON mp.cluster_id = a.cluster_id
        WHERE a.delivery_status = :status
          AND a.delivered_at IS NOT NULL
          AND a.delivered_at >= NOW() - make_interval(secs => :window_seconds)
        """
    )

    row = session.execute(
        sql,
        {
            "p50": _PERCENTILE_50,
            "p95": _PERCENTILE_95,
            "status": DELIVERY_STATUS_DELIVERED,
            "window_seconds": float(window_seconds),
        },
    ).one()

    e2e_p50_s: float | None = _extract_seconds(row.e2e_p50)
    e2e_p95_s: float | None = _extract_seconds(row.e2e_p95)
    delivery_p50_s: float | None = _extract_seconds(row.delivery_p50)
    delivery_p95_s: float | None = _extract_seconds(row.delivery_p95)
    count: int = int(row.cnt) if row.cnt is not None else 0
    count_negative: int = int(row.cnt_negative) if row.cnt_negative is not None else 0

    log_event(
        "signal_latency",
        e2e_p50_s=e2e_p50_s,
        e2e_p95_s=e2e_p95_s,
        delivery_p50_s=delivery_p50_s,
        delivery_p95_s=delivery_p95_s,
        count=count,
        count_negative=count_negative,
        window_s=window_seconds,
    )

    return {
        "e2e_p50_s": e2e_p50_s,
        "e2e_p95_s": e2e_p95_s,
        "delivery_p50_s": delivery_p50_s,
        "delivery_p95_s": delivery_p95_s,
        "count": count,
        "count_negative": count_negative,
        "window_s": window_seconds,
    }


def emit_redis_memory(redis: Redis) -> dict[str, object]:
    """Read Redis memory stats and emit a structured log event.

    Reads ``INFO memory`` (``used_memory``, ``used_memory_peak``, ``maxmemory``)
    and emits ``log_event("redis_memory", used=…, peak=…, max=…)``.

    Best-effort: any Redis error is caught, logged as WARNING, and the function
    returns an empty dict — the caller tick must not fail due to Redis being
    temporarily unavailable (Invariant).

    Args:
        redis: A connected ``Redis`` client (caller provides/manages it).

    Returns:
        Dict with keys ``used``, ``peak``, ``max`` on success; ``{}`` on error.
    """
    try:
        # redis-py stubs type .info() as returning Any; cast to the concrete
        # shape so mypy can reason about .get() call return types without Any
        # propagation.  All INFO memory fields are integers in every Redis version.
        raw_info: dict[str, int] = cast(dict[str, int], redis.info(_REDIS_INFO_SECTION))
        used: int = int(raw_info.get("used_memory", 0))
        peak: int = int(raw_info.get("used_memory_peak", 0))
        maxmemory: int = int(raw_info.get("maxmemory", 0))
    except Exception as exc:
        logger.warning(
            "emit_redis_memory: Redis error — skipping metric",
            extra={"exc_type": type(exc).__name__},
        )
        return {}

    log_event("redis_memory", used=used, peak=peak, max=maxmemory)
    return {"used": used, "peak": peak, "max": maxmemory}
