"""Pure, deterministic viral-score formula (overview §4, ADR-001).

`compute_viral_score(ScoreInputs)` is the single source of the score:

    viral_score = velocity·VELOCITY_WEIGHT
                + engagement·ENGAGEMENT_WEIGHT
                + cross_channel·CROSS_CHANNEL_WEIGHT

with (overview §4):

    velocity      = log1p(Δchannel_count) / Δhours
    engagement    = (views + forwards·FORWARD_FACTOR + reactions·REACTION_FACTOR) / channel_avg
    cross_channel = unique_channels_count / watched_channels_count

The function is platform-independent: it consumes already-normalized aggregates
(PostMetrics totals + channel counts + a time delta) passed directly, performs no
I/O, queries no DB, and imports nothing from `collector`/Telethon (AC2). All
weights and coefficients are NAMED constants (no magic literals — CONVENTIONS).
Guards keep the formula total over degenerate inputs (Δhours→0, channel_avg==0,
watched==0) instead of raising (Edge cases in the task doc).
"""

import math
from dataclasses import dataclass

# Formula weights (overview §4 — sum to 1.0). Named, never magic literals.
VELOCITY_WEIGHT = 0.4
ENGAGEMENT_WEIGHT = 0.35
CROSS_CHANNEL_WEIGHT = 0.25

# Engagement coefficients (overview §4): a forward signals stronger virality than
# a view, a reaction stronger than a view but weaker than a forward.
FORWARD_FACTOR = 3
REACTION_FACTOR = 2

# Minimum time window (hours) for `_velocity`: when every channel lights up in the
# same instant (Δhours→0) we clamp to this quantum instead of dividing by zero.
MIN_WINDOW_HOURS = 1.0 / 60.0  # one minute, expressed in hours

# Lower/upper bounds for the cross-channel ratio (unique ≤ watched by definition;
# clamp dirty data into the unit interval — invariant cross_channel ∈ [0, 1]).
_CROSS_CHANNEL_MIN = 0.0
_CROSS_CHANNEL_MAX = 1.0


@dataclass(frozen=True)
class ScoreInputs:
    """Normalized, platform-independent aggregates a cluster's score is computed from.

    These are derived upstream (scorer/tasks.py) from a cluster's recent posts —
    the scorer itself never touches the DB or a platform SDK.
    """

    views: int
    forwards: int
    reactions: int
    channel_avg: float
    delta_channel_count: int
    delta_hours: float
    unique_channels_count: int
    watched_channels_count: int


def _velocity(*, delta_channel_count: int, delta_hours: float) -> float:
    """Log-scaled spread speed: log1p(Δchannel_count) / Δhours.

    `log1p` is safe at 0 (→ 0.0) and dampens very large Δchannel_count (log scale,
    by design). `Δhours` is clamped to `MIN_WINDOW_HOURS` so a zero/near-zero
    window never divides by zero.
    """
    hours = max(delta_hours, MIN_WINDOW_HOURS)
    return math.log1p(delta_channel_count) / hours


def engagement_numerator(*, views: int, forwards: int, reactions: int) -> float:
    """Weighted engagement numerator: views + forwards·F + reactions·R.

    Extracted as a reusable pure function so the historical baseline query
    (scorer/tasks.py) and the engagement formula use the exact same weighted
    sum — numerator and denominator must be the same nature (Discussion TASK-041).
    """
    return float(views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR)


def _engagement(*, views: int, forwards: int, reactions: int, channel_avg: float) -> float:
    """Weighted engagement normalized by the channel's historical average.

    `channel_avg ≤ 0` (no historical base) → 0.0 (no engagement signal) rather
    than a ZeroDivision.
    """
    if channel_avg <= 0:
        return 0.0
    weighted = engagement_numerator(views=views, forwards=forwards, reactions=reactions)
    return weighted / channel_avg


def _cross_channel(*, unique_channels_count: int, watched_channels_count: int) -> float:
    """Fraction of watched channels the cluster spread across, clamped to [0, 1].

    `watched ≤ 0` → 0.0 (cannot be cross-channel with nothing watched).
    """
    if watched_channels_count <= 0:
        return _CROSS_CHANNEL_MIN
    ratio = unique_channels_count / watched_channels_count
    return min(max(ratio, _CROSS_CHANNEL_MIN), _CROSS_CHANNEL_MAX)


@dataclass(frozen=True)
class ScoreComponents:
    """The three normalized components + their weighted `viral_score` (overview §4).

    Returned by `compute_components` so callers (scorer/tasks.py) can persist the
    breakdown to a `Score` row without recomputing — `viral_score` is the value
    `compute_viral_score` returns.
    """

    velocity: float
    engagement: float
    cross_channel: float
    viral_score: float


def compute_components(inputs: ScoreInputs) -> ScoreComponents:
    """Compute the three components and their weighted sum in one deterministic pass."""
    velocity = _velocity(
        delta_channel_count=inputs.delta_channel_count,
        delta_hours=inputs.delta_hours,
    )
    engagement = _engagement(
        views=inputs.views,
        forwards=inputs.forwards,
        reactions=inputs.reactions,
        channel_avg=inputs.channel_avg,
    )
    cross_channel = _cross_channel(
        unique_channels_count=inputs.unique_channels_count,
        watched_channels_count=inputs.watched_channels_count,
    )
    viral_score = (
        velocity * VELOCITY_WEIGHT
        + engagement * ENGAGEMENT_WEIGHT
        + cross_channel * CROSS_CHANNEL_WEIGHT
    )
    return ScoreComponents(
        velocity=velocity,
        engagement=engagement,
        cross_channel=cross_channel,
        viral_score=viral_score,
    )


def compute_viral_score(inputs: ScoreInputs) -> float:
    """Deterministic weighted viral score over normalized aggregates (overview §4)."""
    return compute_components(inputs).viral_score
