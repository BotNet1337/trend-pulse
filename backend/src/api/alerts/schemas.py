"""Pydantic boundary models for the alerts read API (TASK-016, CONVENTIONS).

AlertRead — the response shape for one alert (score, topic from Cluster join,
first_seen, channels_count, delivery_status). `topic` is NOT on Alert — it is
carried by the related Cluster and is resolved by the service layer.

AlertListResponse — paginated envelope: items + total/limit/offset + the
`history_unavailable` flag which the UI uses to render the plan-based upsell
(Free plan → history_unavailable=True, items=[]).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AlertRead(BaseModel):
    """Read-only projection of one alert row (with Cluster.topic join)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    score: float
    topic: str
    first_seen: datetime
    channels_count: int
    delivery_status: str


class AlertListResponse(BaseModel):
    """Paginated list response envelope for GET /alerts.

    `history_unavailable` is True when the caller's plan has no history window
    (Free plan, HISTORY == 0). The UI must show the plan-upgrade upsell.
    The plan window is enforced backend-side; the frontend MUST NOT hard-code
    the 30/90 day numbers inline (TASK-016 invariant: backend is source of truth).
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AlertRead]
    total: int
    limit: int
    offset: int
    history_unavailable: bool
