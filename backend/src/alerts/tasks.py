"""Celery tasks for alert delivery + pending-alert resweep (task-009, task-023).

`dispatch_alert(alert_id)` is enqueued by the scorer (`scorer.tasks`) right after a
NEW alert row is created. It takes a JSON-serializable id (CONVENTIONS), loads the
alert, and delegates to `alerts.notifier.deliver`:

- `TransientDeliveryError` (network/timeout/429/5xx) → Celery retry with
  exponential backoff up to `ALERT_MAX_RETRIES`. When retries are exhausted the
  alert is marked `failed` (AC5).
- `PermanentDeliveryError` / `WebhookValidationError` (bad token, 4xx, SSRF
  reject, no channel) → immediate `failed`, NO retry (AC7).
- Success → `notifier.deliver` has already set `delivered` + `delivered_at` (AC6).

`resweep_pending_alerts` (task-023) is a beat-driven sweep that re-enqueues
`dispatch_alert` for any `pending` alert older than the grace window. This closes
the reliability footgun where a broker/worker crash leaves alerts stuck in `pending`
forever. Idempotent: only `pending` is swept (never `delivered`/`failed`); the
grace window skips in-flight dispatches; `notifier.deliver` guards re-delivery.

Both tasks are routed to the default `celery` queue (no compose change needed).
"""

import logging
from datetime import timedelta

from celery import Task
from sqlalchemy import select

from alerts.constants import RESWEEP_PENDING_ALERTS_TASK
from alerts.errors import PermanentDeliveryError, TransientDeliveryError
from alerts.notifier import deliver
from celery_app import celery_app
from config import get_settings
from observability.alert_status import emit_alerts_by_status
from storage.database import get_session
from storage.models.alerts import DELIVERY_STATUS_FAILED, DELIVERY_STATUS_PENDING, Alert
from storage.models.base import utcnow

logger = logging.getLogger(__name__)

DISPATCH_ALERT_TASK = "alerts.tasks.dispatch_alert"


def _mark_failed(alert_id: int) -> None:
    """Best-effort terminal `failed` write in its own session (no secrets logged)."""
    with get_session() as session:
        alert = session.get(Alert, alert_id)
        if alert is not None:
            alert.delivery_status = DELIVERY_STATUS_FAILED


def _dispatch(task: "Task[..., object]", alert_id: int) -> str:
    """Body of `dispatch_alert` (testable without a Celery worker / broker).

    `task` is the bound Celery task (`self`): it supplies `request.retries` and
    `retry(...)`. Retries transient failures with exponential backoff; permanent
    failures and exhausted retries become a terminal `failed` (AC5/AC7).
    """
    settings = get_settings()
    try:
        with get_session() as session:
            alert = session.get(Alert, alert_id)
            if alert is None:
                logger.warning("dispatch_alert: alert %d not found", alert_id)
                return DELIVERY_STATUS_FAILED
            return deliver(session, alert)
    except TransientDeliveryError as exc:
        # Retry with exponential backoff; on the last attempt, mark failed (AC5).
        if task.request.retries >= settings.alert_max_retries:
            logger.warning("dispatch_alert: alert %d failed after retries", alert_id)
            _mark_failed(alert_id)
            return DELIVERY_STATUS_FAILED
        countdown = min(
            settings.alert_retry_backoff_seconds * (2**task.request.retries),
            settings.alert_retry_backoff_max_seconds,
        )
        raise task.retry(
            exc=exc, countdown=countdown, max_retries=settings.alert_max_retries
        ) from exc
    except PermanentDeliveryError:
        # Bad token / 4xx / SSRF reject / no channel → terminal failure, no retry.
        logger.warning("dispatch_alert: alert %d permanent failure", alert_id)
        _mark_failed(alert_id)
        return DELIVERY_STATUS_FAILED


@celery_app.task(name=DISPATCH_ALERT_TASK, bind=True)
def dispatch_alert(self: "Task[..., object]", alert_id: int) -> str:
    """Deliver alert `alert_id`; retry transient failures, fail permanent ones.

    Thin Celery seam over `_dispatch` (the testable body). Returns the final
    delivery status string.
    """
    return _dispatch(self, alert_id)


def _resweep_pending_alerts() -> int:
    """Body of `resweep_pending_alerts` (testable without a Celery worker/broker).

    Finds all `pending` alerts older than `pending_resweep_grace_seconds` and
    re-enqueues `dispatch_alert` for each. Returns the number of alerts re-enqueued.

    Idempotency guarantees:
    - Only `pending` rows are selected (delivered/failed are untouched).
    - The grace window skips alerts that may still be in-flight.
    - `notifier.deliver` guards against double-delivery on `DELIVERED` status.
    - A DB-level LIMIT cap (`pending_resweep_max_batch`) prevents queue flooding
      after a long outage.
    """
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.pending_resweep_grace_seconds)

    with get_session() as session:
        stale_ids: list[int] = list(
            session.execute(
                select(Alert.id)
                .where(Alert.delivery_status == DELIVERY_STATUS_PENDING)
                .where(Alert.first_seen < cutoff)
                .order_by(Alert.first_seen)
                .limit(settings.pending_resweep_max_batch)
            )
            .scalars()
            .all()
        )

        reenqueued = 0
        for alert_id in stale_ids:
            try:
                dispatch_alert.apply_async(args=(alert_id,))
            except Exception:
                # Broker unreachable mid-sweep is the very failure this sweep exists
                # to recover from — it must NOT abort the loop (the next tick retries,
                # idempotently) nor skip the status metric below. Logged, not swallowed.
                logger.warning(
                    "resweep_pending_alerts: enqueue failed for alert_id=%s (retried next tick)",
                    alert_id,
                )
                continue
            reenqueued += 1
        logger.info("resweep_pending_alerts reenqueued=%d", reenqueued)

        # Emit aggregate alerts-by-status signal for observability/alerting (AC4).
        # Runs even if some enqueues failed — the backlog signal matters most then.
        emit_alerts_by_status(session)

    return reenqueued


@celery_app.task(name=RESWEEP_PENDING_ALERTS_TASK)
def resweep_pending_alerts() -> int:
    """Re-enqueue stale `pending` alerts (beat-driven, task-023).

    Thin Celery seam over `_resweep_pending_alerts` (the testable body).
    Returns the count of alerts re-enqueued this tick.
    """
    return _resweep_pending_alerts()
