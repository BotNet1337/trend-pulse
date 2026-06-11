"""Pure alert presentation: human message (overview §1) + webhook JSON (§4).

`AlertView` is the immutable, platform-independent projection the formatters
consume. The Alert row (task-002/008) carries only `cluster_id`, `score`,
`channels_count`, `first_seen` — NOT `topic`/`title`/`velocity`. Those are sourced
by the notifier from the linked `Cluster` (topic, and the title derived from it)
and the latest `Score` row (velocity), then packed into an `AlertView`. Keeping
the formatters pure (no DB, no mutation) makes them trivially testable (AC1).

`build_reply_markup` (TASK-042) constructs the Telegram InlineKeyboardMarkup
dict with two URL-buttons 👍/👎 pointing at ``GET /api/v1/feedback/{token}``.
When `public_base_url` is empty it logs a one-time warning and returns None
so the delivery path degrades gracefully (Invariant).
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from alerts.feedback_tokens import sign_feedback_token

logger = logging.getLogger(__name__)

# overview §1 message format. The score in the example is an integer (`Score: 94`)
# and the channel count is a plain integer — render the score as a rounded int so
# `94.0` reads as `94`. Named so the format string has no magic literals.
_WEBHOOK_EVENT = "viral_alert"
_FIRST_SEEN_TIME_FORMAT = "%H:%M"

# Feedback API path — must match nginx /api/ prefix strip (TASK-042 locate).
# nginx proxies /api/* → backend /v1/* (TASK-030: /api/v1 versioning, ADR-007).
# So the full public URL is: {public_base_url}/api/v1/feedback/{token}.
_FEEDBACK_API_PATH = "/api/v1/feedback/"

# Button emoji labels — named, not magic literals.
_BUTTON_UP_LABEL = "👍"
_BUTTON_DOWN_LABEL = "👎"

# Guard flag so the "no public_base_url" warning is emitted only once per process
# (avoid log flooding on every alert). Module-level flag.
_warned_no_base_url: bool = False


@dataclass(frozen=True)
class AlertView:
    """Immutable projection of an alert for delivery formatting (no ORM, no I/O)."""

    topic: str
    title: str
    score: float
    channels_count: int
    first_seen: datetime
    velocity: float


def format_alert_message(view: AlertView) -> str:
    """Render the overview §1 Telegram message for an alert (pure)."""
    return (
        f'🔥 Viral alert [{view.topic}] — "{view.title}"\n'
        f"Score: {round(view.score)} · {view.channels_count} каналов · "
        f"first seen {view.first_seen.strftime(_FIRST_SEEN_TIME_FORMAT)}"
    )


def build_webhook_payload(view: AlertView) -> dict[str, object]:
    """Build the overview §4 webhook JSON payload for an alert (pure).

    The `score` is emitted as an integer to match the overview schema example
    (`"score": 94`); `first_seen` is an ISO-8601 timestamp string.
    """
    return {
        "event": _WEBHOOK_EVENT,
        "topic": view.topic,
        "title": view.title,
        "score": round(view.score),
        "channels_count": view.channels_count,
        "first_seen": view.first_seen.isoformat(),
        "velocity": view.velocity,
    }


def build_reply_markup(
    *,
    view: AlertView,
    alert_id: int,
    jwt_secret: str,
    public_base_url: str,
    ttl_seconds: int,
) -> dict[str, object] | None:
    """Build a Telegram InlineKeyboardMarkup with 👍/👎 URL feedback buttons.

    Returns an ``inline_keyboard`` dict for use in ``sendMessage.reply_markup``,
    or ``None`` when ``public_base_url`` is empty (graceful degradation — alert
    is delivered without buttons; one-time WARNING logged).

    Each button's URL points to ``{public_base_url}/api/v1/feedback/{token}``
    where ``token`` is a short HMAC-SHA256-signed token encoding
    (alert_id, verdict, exp). The nginx edge proxy strips the ``/api/`` prefix
    before forwarding to the backend.

    Args:
        view:            AlertView (reserved — currently unused; kept for future
                         use e.g. including topic in button labels).
        alert_id:        The alert row id — embedded in the token payload.
        jwt_secret:      Application jwt_secret for token signing.
        public_base_url: Publicly reachable domain (e.g. "https://foresignal.biz").
        ttl_seconds:     Token validity in seconds (e.g. 604800 = 7d).

    Returns:
        Telegram InlineKeyboardMarkup dict, or None when base_url is empty.
    """
    global _warned_no_base_url

    if not public_base_url:
        if not _warned_no_base_url:
            logger.warning(
                "build_reply_markup: public_base_url is empty — "
                "alert feedback buttons disabled (set PUBLIC_BASE_URL in deploy.env)"
            )
            _warned_no_base_url = True
        return None

    # ``view`` is reserved in the function signature for future use (e.g. including
    # the topic/title in the button text).  The token encodes only alert_id+verdict+exp;
    # no AlertView fields are used currently.  Accepted but deliberately unused.
    _ = view  # reserved — do not remove from signature

    base = public_base_url.rstrip("/")

    token_up = sign_feedback_token(
        alert_id=alert_id,
        verdict="up",
        jwt_secret=jwt_secret,
        ttl_seconds=ttl_seconds,
    )
    token_down = sign_feedback_token(
        alert_id=alert_id,
        verdict="down",
        jwt_secret=jwt_secret,
        ttl_seconds=ttl_seconds,
    )

    return {
        "inline_keyboard": [
            [
                {"text": _BUTTON_UP_LABEL, "url": f"{base}{_FEEDBACK_API_PATH}{token_up}"},
                {"text": _BUTTON_DOWN_LABEL, "url": f"{base}{_FEEDBACK_API_PATH}{token_down}"},
            ]
        ]
    }
