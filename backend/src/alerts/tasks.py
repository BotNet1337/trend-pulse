"""Celery task: dispatch one alert to its user's channels (task-009).

`dispatch_alert(alert_id)` is enqueued by the scorer (`scorer.tasks`) right after a
NEW alert row is created. It takes a JSON-serializable id (CONVENTIONS), loads the
alert, and delegates to `alerts.notifier.deliver`:

- `TransientDeliveryError` (network/timeout/429/5xx) → Celery retry with
  exponential backoff up to `ALERT_MAX_RETRIES`. When retries are exhausted the
  alert is marked `failed` (AC5).
- `PermanentDeliveryError` / `WebhookValidationError` (bad token, 4xx, SSRF
  reject, no channel) → immediate `failed`, NO retry (AC7).
- Success → `notifier.deliver` has already set `delivered` + `delivered_at` (AC6).

Routed to the default `celery` queue (which the worker already consumes via
`-Q celery,batch,score:global`), so no compose change is needed.
"""

import logging

from celery import Task

from alerts.errors import PermanentDeliveryError, TransientDeliveryError
from alerts.notifier import deliver
from celery_app import celery_app
from config import get_settings
from storage.database import get_session
from storage.models.alerts import DELIVERY_STATUS_FAILED, Alert

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
