"""Pydantic boundary models for the public signals API (T7).

A `SignalOut` is the JSON shape of a `scorer.signal_payload.SignalPayload` — the
sellable signal: what/how-strong/where/how-early. Aggregate-only (no raw content
beyond the short origin narrative), matching the compliance posture of /trending.
"""

from pydantic import BaseModel, Field

from scorer.categorize import EventCategory
from scorer.noise_filter import SignalKind


class SignalOut(BaseModel):
    """One actionable signal (API boundary model)."""

    headline_score: float = Field(ge=0.0, le=100.0)
    signal_kind: SignalKind
    category: EventCategory
    origin_channel: int
    origin_at: float
    total_channels: int = Field(ge=0)
    independent_channels: float = Field(ge=0.0)
    lead_time_to_confirmation_seconds: float | None
    narrative: str


class SignalsResponse(BaseModel):
    """Envelope for GET /signals (list of signals, newest/strongest first)."""

    signals: list[SignalOut]
