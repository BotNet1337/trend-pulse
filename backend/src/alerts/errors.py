"""Domain errors for alert delivery — drive the retry policy (transient vs permanent).

`dispatch_alert` (alerts.tasks) retries `TransientDeliveryError` with backoff and
treats `PermanentDeliveryError` / `WebhookValidationError` as immediate `failed`
(no retry). Raising a typed error (never a bare `except`) keeps the policy explicit.
"""


class DeliveryError(Exception):
    """Base for all alert-delivery failures."""


class TransientDeliveryError(DeliveryError):
    """A retryable failure (network error, timeout, HTTP 429/5xx)."""


class PermanentDeliveryError(DeliveryError):
    """A non-retryable failure (bad/revoked token, HTTP 4xx config error)."""


class WebhookValidationError(PermanentDeliveryError):
    """Webhook URL failed the SSRF guard — permanent (never retry, never POST)."""
