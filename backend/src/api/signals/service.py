"""Signals service — map domain SignalPayloads to API models behind a source port.

The data SOURCE (where recent signals come from — a DB query, a cache) is a Protocol so
the router and the MCP server depend on the port, not a concrete store, and unit tests
inject a fake. Pure mapping; no I/O here.
"""

from typing import Protocol

from api.signals.schemas import SignalOut
from scorer.signal_payload import SignalPayload


class SignalSource(Protocol):
    """Port: returns up to `limit` recent signals, strongest/newest first."""

    def recent(self, limit: int) -> list[SignalPayload]: ...


class EmptySignalSource:
    """Default source — returns nothing. Replaced by a DB-backed source on wiring (T6b)."""

    def recent(self, limit: int) -> list[SignalPayload]:
        return []


def to_signal_out(payload: SignalPayload) -> SignalOut:
    """Map a domain `SignalPayload` to its API boundary model."""
    return SignalOut(
        headline_score=payload.headline_score,
        signal_kind=payload.signal_kind,
        category=payload.category,
        origin_channel=payload.origin_channel,
        origin_at=payload.origin_at,
        total_channels=payload.total_channels,
        independent_channels=payload.independent_channels,
        lead_time_to_confirmation_seconds=payload.lead_time_to_confirmation_seconds,
        narrative=payload.narrative,
    )


def recent_signals(source: SignalSource, limit: int) -> list[SignalOut]:
    """Fetch up to `limit` recent signals from `source` and map to API models."""
    return [to_signal_out(p) for p in source.recent(limit)]
