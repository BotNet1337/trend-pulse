"""Pure logic for forward feature-snapshot capture (TASK-109, B1).

Decides which early observation windows are DUE for a cluster given its age and the
windows already captured, and aggregates a cluster's posts into a metrics-only
snapshot. DB-free and pure so the opportunistic-capture contract is unit-tested without
a live Postgres; the DB write + idempotency live in `scorer.tasks`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Named early observation windows (seconds since the cluster's first_seen). No magic
# literals (CONVENTIONS: time in seconds, named). Ordered ascending; the label is the
# stored `window_label`. These are the windows the GBDT early-signal curve is read at.
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 60 * _SECONDS_PER_MINUTE
OBSERVATION_WINDOW_SECONDS: dict[str, int] = {
    "15m": 15 * _SECONDS_PER_MINUTE,
    "30m": 30 * _SECONDS_PER_MINUTE,
    "1h": _SECONDS_PER_HOUR,
}

# Floor on the age denominator for breadth velocity — mirrors the score's burst floor
# so a sub-minute / zero age can never divide by zero or manufacture an infinite rate.
_MIN_AGE_HOURS = 1.0 / _SECONDS_PER_MINUTE


def windows_due(*, age_seconds: int, captured: frozenset[str]) -> tuple[str, ...]:
    """Which observation windows are crossed-but-not-yet-captured, ascending.

    A window is due when the cluster's age has reached its nominal seconds and no
    snapshot for that window exists yet. Returns every such window (so a missed earlier
    tick is backfilled the first time a later tick runs), in ascending window order.
    Clock-skew / future first_seen (age <= 0) yields no windows.
    """
    if age_seconds < 0:
        return ()
    return tuple(
        label
        for label, seconds in OBSERVATION_WINDOW_SECONDS.items()
        if age_seconds >= seconds and label not in captured
    )


def breadth_velocity(*, distinct_channels: int, age_seconds: int) -> float:
    """Cross-channel breadth velocity = distinct channels per hour (clamped age).

    The age denominator is floored at `_MIN_AGE_HOURS` so a zero/sub-minute age cannot
    divide by zero. A breadth-velocity FEATURE (not a score term) for the GBDT.
    """
    age_hours = max(age_seconds / _SECONDS_PER_HOUR, _MIN_AGE_HOURS)
    return distinct_channels / age_hours


@dataclass(frozen=True)
class SnapshotMetrics:
    """Cumulative-since-birth, metrics-only snapshot of a cluster at an observation window."""

    post_count: int
    views: int
    forwards: int
    reactions: int
    distinct_channels: int
    breadth_velocity: float


def build_snapshot_metrics(
    *,
    post_views: Sequence[int],
    post_forwards: Sequence[int],
    post_reactions: Sequence[int],
    channel_ids: Sequence[int],
    age_seconds: int,
) -> SnapshotMetrics:
    """Aggregate a cluster's posts (cumulative since first_seen) into `SnapshotMetrics`.

    The four post sequences are parallel (one entry per in-cluster post) and must have
    equal length — validated at the boundary (CONVENTIONS: never trust external data).
    An empty cluster yields all-zero metrics (no posts → nothing accrued yet).
    """
    lengths = {
        len(post_views),
        len(post_forwards),
        len(post_reactions),
        len(channel_ids),
    }
    if len(lengths) != 1:
        raise ValueError(
            "post metric sequences must have equal length: "
            f"views={len(post_views)} forwards={len(post_forwards)} "
            f"reactions={len(post_reactions)} channels={len(channel_ids)}"
        )
    distinct_channels = len(set(channel_ids))
    return SnapshotMetrics(
        post_count=len(post_views),
        views=sum(post_views),
        forwards=sum(post_forwards),
        reactions=sum(post_reactions),
        distinct_channels=distinct_channels,
        breadth_velocity=breadth_velocity(
            distinct_channels=distinct_channels, age_seconds=age_seconds
        ),
    )
