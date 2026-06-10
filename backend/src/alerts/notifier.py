"""Delivery orchestrator: resolve config → send via channels → record status.

`deliver(session, alert)` is the heart of task-009:

1. Idempotency guard (AC4): if the alert is already `delivered`, no-op.
2. Build the immutable `AlertView` from the alert row + its linked `Cluster`
   (topic / title) + the latest `Score` row (velocity). The Alert row itself
   carries only score/channels_count/first_seen.
3. Resolve the user's delivery config: Telegram (bot token + chat id) on every
   plan; webhook ONLY if `plan ∈ {pro, team}` AND a webhook URL is set. SSRF
   validation happens inside `WebhookBackend.send`.
4. Send via each selected backend. A permanent failure on one channel (bad token)
   does NOT abort the others. Success in ≥1 channel → `delivered` + `delivered_at`.
   A transient failure propagates so the Celery task can retry (alerts.tasks).
5. Record `delivery_attempts`.

Secrets (bot token, webhook URL) are never logged (overview §7).
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from alerts.backends import (
    DeliveryBackend,
    DeliveryResult,
    TelegramBotBackend,
    TelegramTarget,
    WebhookBackend,
    WebhookTarget,
)
from alerts.errors import PermanentDeliveryError, TransientDeliveryError
from alerts.formatting import AlertView
from config import Settings, get_settings
from storage.models.alerts import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    Alert,
)
from storage.models.base import utcnow
from storage.models.clusters import Cluster
from storage.models.scores import Score
from storage.models.users import PLAN_PRO, PLAN_TEAM, User

logger = logging.getLogger(__name__)

# Plans on which webhook delivery is available (overview §6). Telegram is on every
# plan. Hard enforcement is task-010; this is the gating membership check.
_WEBHOOK_PLANS = frozenset({PLAN_PRO, PLAN_TEAM})


@dataclass(frozen=True)
class _Channel:
    """A backend paired with its resolved target."""

    backend: DeliveryBackend
    target: object


class NoChannelConfiguredError(PermanentDeliveryError):
    """The user has no usable delivery channel — permanent (never retry)."""


def _build_view(session: Session, alert: Alert) -> AlertView:
    """Project an alert (+ its cluster + latest score) into an `AlertView`.

    Topic and title come from the linked `Cluster` (the Alert row has no topic);
    the title defaults to the cluster topic when no richer title exists. Velocity
    comes from the latest `Score` row for `(user_id, cluster_id)`, defaulting to
    0.0 when absent (the alert can still be delivered).
    """
    cluster = session.get(Cluster, alert.cluster_id)
    topic = cluster.topic if cluster is not None else ""
    velocity = session.scalar(
        select(Score.velocity)
        .where(Score.user_id == alert.user_id)
        .where(Score.cluster_id == alert.cluster_id)
        .order_by(Score.computed_at.desc())
        .limit(1)
    )
    return AlertView(
        topic=topic,
        # No standalone post title is linked yet (task-008 approximation); the topic
        # is the best available human label. Refined when a post↔cluster link lands.
        title=topic,
        score=alert.score,
        channels_count=alert.channels_count,
        first_seen=alert.first_seen,
        velocity=float(velocity) if velocity is not None else 0.0,
    )


def _resolve_channels(user: User, settings: Settings) -> list[_Channel]:
    """Select the backends+targets the user has configured (Telegram, then webhook)."""
    channels: list[_Channel] = []
    if user.telegram_bot_token and user.telegram_chat_id:
        channels.append(
            _Channel(
                backend=TelegramBotBackend(
                    base_url=settings.telegram_api_base_url,
                    timeout_seconds=settings.alert_http_timeout_seconds,
                    jwt_secret=settings.jwt_secret,
                    public_base_url=settings.public_base_url,
                    feedback_token_ttl_seconds=settings.feedback_token_ttl_seconds,
                ),
                target=TelegramTarget(
                    bot_token=user.telegram_bot_token, chat_id=user.telegram_chat_id
                ),
            )
        )
    # Webhook is gated to Pro/Team AND requires a configured URL.
    if user.plan in _WEBHOOK_PLANS and user.webhook_url:
        channels.append(
            _Channel(
                backend=WebhookBackend(timeout_seconds=settings.alert_http_timeout_seconds),
                target=WebhookTarget(url=user.webhook_url),
            )
        )
    return channels


def deliver(session: Session, alert: Alert) -> str:
    """Deliver an alert to the user's channels; return the final delivery status.

    Raises `TransientDeliveryError` if a channel fails transiently (so the Celery
    task can retry). Permanent per-channel failures are recorded but do not abort
    the remaining channels.
    """
    # AC4 — idempotency guard: an already-delivered alert is a strict no-op.
    if alert.delivery_status == DELIVERY_STATUS_DELIVERED:
        return DELIVERY_STATUS_DELIVERED

    settings = get_settings()
    user = session.get(User, alert.user_id)
    if user is None:
        # The owning user vanished — nothing to deliver to (permanent).
        alert.delivery_status = DELIVERY_STATUS_FAILED
        raise NoChannelConfiguredError("alert has no owning user")

    channels = _resolve_channels(user, settings)
    if not channels:
        # No configured channel → mark failed with a reason; do NOT retry-loop.
        alert.delivery_status = DELIVERY_STATUS_FAILED
        raise NoChannelConfiguredError("user has no configured delivery channel")

    view = _build_view(session, alert)
    any_success = False
    transient: TransientDeliveryError | None = None
    for channel in channels:
        alert.delivery_attempts += 1
        try:
            result: DeliveryResult = channel.backend.send(view, channel.target, alert_id=alert.id)
        except TransientDeliveryError as exc:
            # Remember the transient failure; keep trying other channels, then
            # re-raise so the task retries (a later attempt may succeed).
            transient = exc
            continue
        except PermanentDeliveryError:
            # Bad token / SSRF reject / 4xx — log a status (no secrets) and move on.
            logger.warning("alert %d permanent failure on backend", alert.id)
            continue
        if result.ok:
            any_success = True

    if any_success:
        alert.delivery_status = DELIVERY_STATUS_DELIVERED
        alert.delivered_at = utcnow()
        return DELIVERY_STATUS_DELIVERED

    if transient is not None:
        # No channel succeeded but at least one was transient → let the task retry.
        raise transient

    # Every channel failed permanently → terminal failure (no retry).
    alert.delivery_status = DELIVERY_STATUS_FAILED
    return DELIVERY_STATUS_FAILED
