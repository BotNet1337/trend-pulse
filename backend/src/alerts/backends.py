"""Delivery backends behind one `DeliveryBackend` protocol (overview §4).

Two implementations send an `AlertView` to a resolved target:

- `TelegramBotBackend` — POST `<base>/bot<token>/sendMessage` with `chat_id`+`text`
  (the overview §1 message). Default channel, available on every plan.
  TASK-042: when `public_base_url` is set and `alert_id` is supplied, includes
  ``reply_markup`` with 👍/👎 inline URL buttons.
- `WebhookBackend` — validate the URL against SSRF FIRST, then POST the overview §4
  JSON payload with `follow_redirects=False` (a 3xx to an internal host must not
  bypass the guard). Pro/Team channel.

HTTP error mapping is shared: 429/5xx and network errors/timeouts → transient
(retryable); other 4xx → permanent (bad token/config — never retry). The token is
never logged and never echoed into an error message.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from alerts.errors import (
    PermanentDeliveryError,
    TransientDeliveryError,
    WebhookValidationError,
)
from alerts.formatting import (
    AlertView,
    build_reply_markup,
    build_webhook_payload,
    format_alert_message,
)
from alerts.security import build_ssrf_safe_client

logger = logging.getLogger(__name__)

# HTTP status boundaries — named, not magic literals (CONVENTIONS).
_HTTP_ERROR_FLOOR = 400
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_FLOOR = 500


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a single backend send (no secrets in `detail`)."""

    ok: bool
    backend: str
    detail: str


@dataclass(frozen=True)
class TelegramTarget:
    """Resolved Telegram delivery config (bot token + chat id).

    `bot_token` is a secret: `repr=False` keeps it out of the auto `__repr__`
    so it never leaks into logs, tracebacks, or error messages.
    """

    bot_token: str = field(repr=False)
    chat_id: str


@dataclass(frozen=True)
class WebhookTarget:
    """Resolved webhook delivery config (validated URL)."""

    url: str


class DeliveryBackend(Protocol):
    """A channel that can send an alert to a resolved target."""

    def send(
        self, view: AlertView, target: object, *, alert_id: int | None = None
    ) -> DeliveryResult: ...


def _raise_for_http_status(status_code: int, *, backend: str) -> None:
    """Map an HTTP status to a transient/permanent delivery error.

    429 (rate limit) and 5xx → transient (retry with backoff); other 4xx →
    permanent (config error, never retry). The status code is safe to surface;
    the bot token / URL is not included.
    """
    if status_code == _HTTP_TOO_MANY_REQUESTS or status_code >= _HTTP_SERVER_ERROR_FLOOR:
        raise TransientDeliveryError(f"{backend} returned retryable status {status_code}")
    raise PermanentDeliveryError(f"{backend} returned non-retryable status {status_code}")


class TelegramBotBackend:
    """Send an alert via the Telegram Bot API `sendMessage` method.

    TASK-042: when `public_base_url` is non-empty and `alert_id` is passed to
    `send`, includes ``reply_markup`` with inline 👍/👎 URL buttons pointing at
    ``GET {public_base_url}/api/feedback/{token}``. When `public_base_url` is
    empty, ``reply_markup`` is omitted (graceful degradation — delivery does not
    fail, buttons are just absent).
    """

    name = "telegram"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        jwt_secret: str = "",
        public_base_url: str = "",
        feedback_token_ttl_seconds: int = 604800,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._jwt_secret = jwt_secret
        self._public_base_url = public_base_url
        self._feedback_token_ttl_seconds = feedback_token_ttl_seconds

    def send(
        self,
        view: AlertView,
        target: object,
        *,
        alert_id: int | None = None,
    ) -> DeliveryResult:
        """Send an alert message; include reply_markup when alert_id is provided.

        Args:
            view:      The alert view to format.
            target:    Must be a TelegramTarget.
            alert_id:  DB id of the alert row (required for feedback buttons).
                       If None, buttons are not included even when base_url is set.
        """
        if not isinstance(target, TelegramTarget):
            raise PermanentDeliveryError("telegram backend requires a TelegramTarget")
        url = f"{self._base_url}/bot{target.bot_token}/sendMessage"
        body: dict[str, object] = {
            "chat_id": target.chat_id,
            "text": format_alert_message(view),
        }
        # TASK-042: attach reply_markup when public_base_url is configured and
        # alert_id is available. build_reply_markup returns None when base_url
        # is empty, so the key is only added when markup is actually present.
        if alert_id is not None and self._public_base_url:
            markup = build_reply_markup(
                view=view,
                alert_id=alert_id,
                jwt_secret=self._jwt_secret,
                public_base_url=self._public_base_url,
                ttl_seconds=self._feedback_token_ttl_seconds,
            )
            if markup is not None:
                body["reply_markup"] = markup
        try:
            response = httpx.post(url, json=body, timeout=self._timeout_seconds)
        except httpx.HTTPError as exc:
            # Network error / timeout → transient (the URL/token is not logged).
            raise TransientDeliveryError("telegram request failed") from exc
        if response.status_code >= _HTTP_ERROR_FLOOR:
            _raise_for_http_status(response.status_code, backend=self.name)
        return DeliveryResult(ok=True, backend=self.name, detail="sent")


class WebhookBackend:
    """POST the overview §4 JSON payload to a user webhook (SSRF-guarded)."""

    name = "webhook"

    def __init__(self, *, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    def send(
        self,
        view: AlertView,
        target: object,
        *,
        alert_id: int | None = None,
    ) -> DeliveryResult:
        # alert_id is unused by the webhook backend (feedback buttons are TG-only).
        _ = alert_id
        if not isinstance(target, WebhookTarget):
            raise PermanentDeliveryError("webhook backend requires a WebhookTarget")
        # SSRF guard is ATOMIC with the connect: the client uses a transport that
        # resolves the host ONCE, validates EVERY resolved IP against the deny-list,
        # and pins the TCP connection to a validated IP — closing the DNS-rebinding
        # (TOCTOU) window. A WebhookValidationError (permanent) is raised before any
        # bytes leave if the host is internal/loopback/metadata. TLS cert is still
        # verified against the real hostname; redirects are not followed.
        try:
            with build_ssrf_safe_client(timeout_seconds=self._timeout_seconds) as client:
                response = client.post(target.url, json=build_webhook_payload(view))
        except WebhookValidationError:
            # Permanent: re-raise so the dispatcher fails fast (never retries).
            raise
        except httpx.HTTPError as exc:
            raise TransientDeliveryError("webhook request failed") from exc
        if response.status_code >= _HTTP_ERROR_FLOOR:
            _raise_for_http_status(response.status_code, backend=self.name)
        return DeliveryResult(ok=True, backend=self.name, detail="sent")
