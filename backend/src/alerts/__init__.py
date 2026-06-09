"""`alerts` — alert delivery: formatting, backends, SSRF guard, notifier, dispatch.

Public surface (CONVENTIONS: cross-module via service interfaces). The scorer
(task-008) talks to this module ONLY through `dispatch_alert` (enqueued on alert
creation); everything else is the delivery domain's internals.

`alerts.tasks` is NOT re-exported here: it imports `celery_app`, and `celery_app`
imports `scheduler`, which references the resweep task name. Re-exporting tasks at
package init would make `from alerts.constants import ...` (in `scheduler`) drag in
`celery_app` mid-initialisation → circular import that crashes the worker (task-023).
Import the Celery seam explicitly via `alerts.tasks` (same pattern as `pipeline`).
Task NAMES live in the import-cycle-free `alerts.constants`.
"""

from alerts.backends import (
    DeliveryBackend,
    DeliveryResult,
    TelegramBotBackend,
    TelegramTarget,
    WebhookBackend,
    WebhookTarget,
)
from alerts.constants import RESWEEP_PENDING_ALERTS_TASK
from alerts.errors import (
    DeliveryError,
    PermanentDeliveryError,
    TransientDeliveryError,
    WebhookValidationError,
)
from alerts.formatting import AlertView, build_webhook_payload, format_alert_message
from alerts.notifier import deliver
from alerts.security import validate_webhook_url

__all__ = [
    "RESWEEP_PENDING_ALERTS_TASK",
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
    "format_alert_message",
    "validate_webhook_url",
]
