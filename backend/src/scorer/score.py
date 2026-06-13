"""Pure, deterministic viral-score formula — v2, engagement-dominant (ADR-001).

`compute_viral_score(ScoreInputs)` is the single source of the score:

    viral_score = SCORE_SCALE · ( velocity·VELOCITY_WEIGHT
                                + engagement·ENGAGEMENT_WEIGHT
                                + cross_channel·CROSS_CHANNEL_WEIGHT )   ∈ [0, 100]

with every component normalized to [0, 1]:

    engagement    = min(log1p(views + forwards·F + reactions·R) / LOG_ENGAGEMENT_SCALE, 1)
    cross_channel = unique_channels_count / watched_channels_count          (reach)
    velocity      = min( log1p(max(Δchannel_count - 1, 0)) / max(Δhours, 1h) / BURST_SCALE, 1 )

v2 rationale (real-data eval, eval_offline/): on a 52k-post crypto-RU corpus the
old velocity-dominant weights (0.4/0.35/0.25) ranked eventual virality at ROC-AUC
≈ 0.86 in a clean early-detection test; leading with ENGAGEMENT (0.55/0.30/0.15)
and bounding every term to [0, 1] reaches 0.91-0.93 and makes the 0-100 score
threshold-able (the old unbounded engagement reached ~13071, so the pack threshold
of 70 was meaningless). Engagement carries the signal (AUC 0.91/0.94; 0.83 even for
single-channel early movers); reach is corroboration; spread is the weakest term.

The function is platform-independent: it consumes already-normalized aggregates,
performs no I/O, queries no DB, and imports nothing from `collector`/Telethon (AC2).
All weights/coefficients are NAMED constants. Guards keep the formula total over
degenerate inputs (Δhours→0, watched==0) instead of raising.
"""

import math
from dataclasses import dataclass

# Formula weights (sum to 1.0). Named, never magic literals.
#
# v2 (TASK-scoring-v2): ENGAGEMENT-DOMINANT, derived from a real-data predictive
# eval (eval_offline/, 52k-post crypto-RU corpus with text). On a clean time-split
# early-detection test (features from a story's first 6h → eventual virality), the
# old velocity-dominant weights (0.4/0.35/0.25) scored ROC-AUC ≈ 0.86 while a blend
# that LEADS WITH ENGAGEMENT scored 0.91-0.93. Engagement is the carrier of the
# signal (AUC 0.91/0.94, and 0.83 even for single-channel early movers); reach is
# corroboration; the spread term (kept from T15) is the weakest, so it gets the
# smallest weight — the inverse of the old allocation.
VELOCITY_WEIGHT = 0.15
ENGAGEMENT_WEIGHT = 0.55
CROSS_CHANNEL_WEIGHT = 0.30

# Engagement coefficients (overview §4): a forward signals stronger virality than
# a view, a reaction stronger than a view but weaker than a forward.
FORWARD_FACTOR = 3
REACTION_FACTOR = 2

# v2: every component is normalized to [0, 1] and the weighted sum is scaled by
# SCORE_SCALE so `viral_score ∈ [0, 100]`. The old score was unbounded (engagement =
# weighted/channel_avg reached 13071 on real data) which made the alert threshold
# meaningless — the pack default of 70 was simultaneously unreachable for most
# clusters and trivially exceeded by a few. A bounded 0-100 score gives the
# threshold a stable, calibratable meaning (see `_DEFAULT_SCORE_THRESHOLD`).
SCORE_SCALE = 100.0

# Engagement is bounded by log1p(weighted_engagement) / LOG_ENGAGEMENT_SCALE, clamped
# to 1. LOG_ENGAGEMENT_SCALE ≈ the 99th pct of log-engagement in the 9-month corpus
# (≈ e^14): the largest real stories saturate engagement_c at 1.0, everything else
# scales smoothly. log1p(raw weighted sum) beat channel-avg-normalized engagement on
# the eval (AUC 0.908 vs 0.856) — absolute reach matters for virality; the tradeoff is
# that large channels are no longer size-normalized (intentional).
LOG_ENGAGEMENT_SCALE = 14.0

# Spread "burst": breadth-per-hour, floored at 1 HOUR (not the old 1-minute clamp that
# let a lone instant post saturate) and divided by BURST_SCALE into [0, 1].
BURST_FLOOR_HOURS = 1.0
BURST_SCALE = 3.0

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
    """Bounded cross-channel BURST: log1p(Δch - 1) / max(Δhours, 1h) / BURST_SCALE ∈ [0, 1].

    "Viral" means a story SPREADING ACROSS channels (overview §4, product principle).
    A single-channel cluster has *no* cross-channel spread, so its burst is 0 —
    `log1p(max(Δch - 1, 0))` makes one channel → 0, two → log1p(1), rising monotonically
    with the breadth of spread (T15 — kept).

    v2 changes vs T15: (1) the window is floored at 1 HOUR, not 1 minute, so a near-zero
    window can no longer inflate the rate; (2) the rate is divided by BURST_SCALE and
    clamped to [0, 1] so this term cannot dominate the weighted sum. On the real-data
    eval the spread term was the WEAKEST predictor (AUC ≈ 0.82 vs engagement's 0.91), so
    it is both down-weighted and bounded — the inverse of the old velocity-dominant design.
    """
    hours = max(delta_hours, BURST_FLOOR_HOURS)
    extra_channels = max(delta_channel_count - 1, 0)
    rate = math.log1p(extra_channels) / hours
    return min(rate / BURST_SCALE, 1.0)


def engagement_numerator(*, views: int, forwards: int, reactions: int) -> float:
    """Weighted engagement numerator: views + forwards·F + reactions·R.

    Extracted as a reusable pure function so the historical baseline query
    (scorer/tasks.py) and the engagement formula use the exact same weighted
    sum — numerator and denominator must be the same nature (Discussion TASK-041).
    """
    return float(views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR)


def _engagement(*, views: int, forwards: int, reactions: int) -> float:
    """Bounded engagement: min(log1p(weighted_engagement) / LOG_ENGAGEMENT_SCALE, 1) ∈ [0, 1].

    v2: the DOMINANT term (weight 0.55). The old version divided the weighted sum by a
    per-channel 7-day historical average (channel_avg), giving an unbounded value that
    reached ~13071 on real data and made the score impossible to threshold. The eval
    showed raw log-engagement separates eventual virality BETTER than the channel-avg
    normalized form (ROC-AUC 0.908 vs 0.856), and even predicts which single-channel
    early movers will spread (AUC 0.830). So v2 uses the bounded raw form; `channel_avg`
    is no longer consumed here (kept on `ScoreInputs` for backwards-compat / the eval
    replay). Always finite, never raises.
    """
    weighted = engagement_numerator(views=views, forwards=forwards, reactions=reactions)
    return min(math.log1p(weighted) / LOG_ENGAGEMENT_SCALE, 1.0)


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
    )
    cross_channel = _cross_channel(
        unique_channels_count=inputs.unique_channels_count,
        watched_channels_count=inputs.watched_channels_count,
    )
    # All three components ∈ [0, 1]; scale the weighted sum to a 0-100 viral_score
    # so the alert threshold is a stable, calibratable number (v2).
    viral_score = SCORE_SCALE * (
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
