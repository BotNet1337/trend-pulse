"""Pydantic boundary models for the alerts read API (TASK-016/020, CONVENTIONS).

AlertRead — the response shape for one alert (score, topic from Cluster join,
first_seen, channels_count, delivery_status). `topic` is NOT on Alert — it is
carried by the related Cluster and is resolved by the service layer.

AlertListResponse — cursor pagination envelope: items + next_cursor (opaque
base64url string, None on last page) + the `history_unavailable` flag which
the UI uses to render the plan-based upsell (Free plan → history_unavailable=True,
items=[], next_cursor=None).

TASK-020: replaces offset/total fields with next_cursor (keyset pagination).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AlertRead(BaseModel):
    """Read-only projection of one alert row (with Cluster.topic join).

    Feedback fields (`feedback`, `feedback_token_up`, `feedback_token_down`) are
    populated ONLY in the detail endpoint (`get_alert`). The list endpoint
    (`list_alerts`) leaves them at their `None` default — per-item feedback tokens
    are not minted for a 20-row page (TASK-064 AC4). `feedback` is the caller's
    current verdict ("up" | "down" | null) read from `alert_feedback`; the two
    token fields are freshly-minted feedback tokens (reusable until TTL expiry —
    the write-path UPSERT is idempotent) for the web 👍/👎 buttons. They are None
    when token minting is unavailable (empty jwt_secret / mint failure — graceful
    degradation, the buttons are then hidden client-side).
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    score: float
    topic: str
    first_seen: datetime
    channels_count: int
    delivery_status: str
    feedback: str | None = None
    feedback_token_up: str | None = None
    feedback_token_down: str | None = None


class AlertListResponse(BaseModel):
    """Cursor-paginated list response envelope for GET /alerts (TASK-020).

    `next_cursor` is an opaque base64url token encoding (first_seen, id) for the
    keyset position. None means no more pages. Clients MUST treat it as opaque
    and pass it back verbatim via the `cursor` query parameter.

    `history_unavailable` is True when the caller's plan has no history window
    (Free plan, HISTORY == 0). The UI must show the plan-upgrade upsell.
    The plan window is enforced backend-side; the frontend MUST NOT hard-code
    the 30/90 day numbers inline (TASK-016 invariant: backend is source of truth).
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AlertRead]
    next_cursor: str | None
    history_unavailable: bool
