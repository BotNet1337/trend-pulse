"""`alerts` — alert delivery: formatting, backends, SSRF guard, notifier, dispatch.

Public surface (CONVENTIONS: cross-module via service interfaces). The scorer
(task-008) talks to this module ONLY through `dispatch_alert` (enqueued on alert
creation); everything else is the delivery domain's internals.
"""

from alerts.backends import (
    DeliveryBackend,
    DeliveryResult,
    TelegramBotBackend,
    TelegramTarget,
    WebhookBackend,
    WebhookTarget,
)
from alerts.errors import (
    DeliveryError,
    PermanentDeliveryError,
    TransientDeliveryError,
    WebhookValidationError,
)
from alerts.formatting import AlertView, build_webhook_payload, format_alert_message
from alerts.notifier import deliver
from alerts.security import validate_webhook_url
from alerts.tasks import DISPATCH_ALERT_TASK, dispatch_alert

__all__ = [
    "DISPATCH_ALERT_TASK",
    "AlertView",
    "DeliveryBackend",
    "DeliveryError",
    "DeliveryResult",
    "PermanentDeliveryError",
    "TelegramBotBackend",
    "TelegramTarget",
    "TransientDeliveryError",
    "WebhookBackend",
    "WebhookTarget",
    "WebhookValidationError",
    "build_webhook_payload",
    "deliver",
    "dispatch_alert",
    "format_alert_message",
    "validate_webhook_url",
]
