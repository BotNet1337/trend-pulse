"""Analytics Celery task — daily business-metrics aggregate (TASK-050).

Beat task `aggregate_business_metrics` fires every
`settings.business_metrics_interval_seconds` (default 86400 = 24h).

It computes:
1. Yesterday's full day (all data is in; idempotent re-run is safe via upsert).
2. Today's partial day (running total; upserted again tomorrow for the full count).

Both days use the same `compute_day → upsert_row` path (ON CONFLICT upsert),
so a restarted beat or double-tick is always safe (AC3).

Invariants:
- Task args: none (JSON-serializable; no ORM objects — CONVENTIONS).
- Failures are re-raised loudly so Sentry captures them (TASK-024 pattern).
  We do NOT swallow exceptions — "Beat-таск падает 'громко'" (task Invariants).
- Each SQL aggregate uses bind params (CONVENTIONS: no f-string SQL).
- Day boundaries are UTC.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from analytics.aggregate import compute_day, upsert_row
from analytics.constants import AGGREGATE_BUSINESS_METRICS_TASK
from celery_app import celery_app
from storage.database import get_session

logger = logging.getLogger(__name__)


@celery_app.task(name=AGGREGATE_BUSINESS_METRICS_TASK)
def aggregate_business_metrics() -> dict[str, object]:
    """Beat task: compute yesterday's + today's partial business metrics.

    Computes and upserts:
    - Yesterday (UTC): full day — all events for that day are in.
    - Today (UTC): partial day — running total; will be overwritten tomorrow.

    Returns a dict with the computed day labels for task-result inspection.
    Raises on any error so Sentry captures it (Beat-task invariant: loud failures).
    """
    now = datetime.now(UTC)
    today = now.date()
    yesterday = today - timedelta(days=1)

    logger.info(
        "aggregate_business_metrics: starting",
        extra={"yesterday": yesterday.isoformat(), "today": today.isoformat()},
    )

    with get_session() as session:
        # Yesterday — full day.
        row_yesterday = compute_day(session, yesterday)
        upsert_row(session, row_yesterday)
        logger.info(
            "aggregate_business_metrics: yesterday done",
            extra={
                "day": yesterday.isoformat(),
                "registrations": row_yesterday.registrations,
                "first_alerts_delivered": row_yesterday.first_alerts_delivered,
            },
        )

        # Today — partial day (running total).
        row_today = compute_day(session, today)
        upsert_row(session, row_today)
        logger.info(
            "aggregate_business_metrics: today (partial) done",
            extra={
                "day": today.isoformat(),
                "registrations": row_today.registrations,
            },
        )

    return {
        "yesterday": yesterday.isoformat(),
        "today": today.isoformat(),
    }
