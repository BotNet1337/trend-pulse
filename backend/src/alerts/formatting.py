"""Pure alert presentation: human message (overview §1) + webhook JSON (§4).

`AlertView` is the immutable, platform-independent projection the formatters
consume. The Alert row (task-002/008) carries only `cluster_id`, `score`,
`channels_count`, `first_seen` — NOT `topic`/`title`/`velocity`. Those are sourced
by the notifier from the linked `Cluster` (topic, and the title derived from it)
and the latest `Score` row (velocity), then packed into an `AlertView`. Keeping
the formatters pure (no DB, no mutation) makes them trivially testable (AC1).
"""

from dataclasses import dataclass
from datetime import datetime

# overview §1 message format. The score in the example is an integer (`Score: 94`)
# and the channel count is a plain integer — render the score as a rounded int so
# `94.0` reads as `94`. Named so the format string has no magic literals.
_WEBHOOK_EVENT = "viral_alert"
_FIRST_SEEN_TIME_FORMAT = "%H:%M"


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
