"""Source attribution — where a story STARTED and how fast it spread across channels.

Buyers pay for "this broke in channel X at HH:MM and reached N channels in T minutes"
(Telemetr markets viral-origin tracing; lead-time is the core sellable metric — see
product strategy). This pure module reconstructs, from a cluster's posts, the ORIGIN
channel, the per-channel first-seen times, and the spread timeline used for lead-time.

Pure — no I/O, no DB (ADR-001). Ties (identical timestamps) resolve by channel id for
determinism.
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class AttributionPost:
    """Minimal per-post shape attribution needs."""

    channel_id: int
    posted_at: float  # epoch seconds


@dataclass(frozen=True)
class SpreadTimeline:
    """Reconstructed origin + cross-channel spread of a cluster."""

    origin_channel: int
    origin_at: float
    # (channel_id, first_seen_epoch) for each distinct channel, ordered by first-seen
    # (ties broken by channel_id) — index i is the (i+1)-th channel the story reached.
    channel_first_seen: tuple[tuple[int, float], ...]

    @property
    def channels_reached(self) -> int:
        """Total distinct channels the story reached."""
        return len(self.channel_first_seen)

    def lead_time_seconds_to_nth_channel(self, n: int) -> float | None:
        """Seconds from origin to the moment the n-th DISTINCT channel picked it up.

        n is 1-based; n=1 is the origin (0.0). Returns None if fewer than n channels
        ever carried the story (the spread never reached that breadth).
        """
        if n < 1 or n > len(self.channel_first_seen):
            return None
        return self.channel_first_seen[n - 1][1] - self.origin_at

    def channels_reached_by(self, dt_seconds: float) -> int:
        """How many distinct channels had the story within `dt_seconds` of the origin."""
        cutoff = self.origin_at + dt_seconds
        return sum(1 for _, ts in self.channel_first_seen if ts <= cutoff)


def attribute(posts: Iterable[AttributionPost]) -> SpreadTimeline | None:
    """Reconstruct the spread timeline from a cluster's posts, or None if empty."""
    first_seen: dict[int, float] = {}
    for p in posts:
        prev = first_seen.get(p.channel_id)
        if prev is None or p.posted_at < prev:
            first_seen[p.channel_id] = p.posted_at
    if not first_seen:
        return None

    ordered = tuple(sorted(first_seen.items(), key=lambda kv: (kv[1], kv[0])))
    origin_channel, origin_at = ordered[0]
    return SpreadTimeline(
        origin_channel=origin_channel,
        origin_at=origin_at,
        channel_first_seen=ordered,
    )
