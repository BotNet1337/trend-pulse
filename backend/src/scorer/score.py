"""Pure, deterministic viral-score formula — v2, engagement-dominant (ADR-001).

`compute_viral_score(ScoreInputs)` is the single source of the score:

    viral_score = SCORE_SCALE · ( temporal·VELOCITY_WEIGHT
                                + engagement·ENGAGEMENT_WEIGHT
                                + cross_channel·CROSS_CHANNEL_WEIGHT )   ∈ [0, 100]

with every component normalized to [0, 1]:

    engagement    = min(log1p(views + forwards·F + reactions·R) / LOG_ENGAGEMENT_SCALE, 1)
    cross_channel = unique_channels_count / watched_channels_count          (reach)
    temporal      = clamp( ACCEL_WEIGHT·norm_accel + BREADTH_WEIGHT·norm_breadth , 0, 1 )

The third (temporal) term is carried in the `velocity` field/column for schema/API
backwards-compatibility (TASK-124) — the NAME `velocity` is unchanged, the SEMANTICS
are now a bounded temporal signal instead of the old degenerate burst.

v2 rationale (real-data eval, eval_offline/): on a 52k-post crypto-RU corpus the
old velocity-dominant weights (0.4/0.35/0.25) ranked eventual virality at ROC-AUC
≈ 0.86 in a clean early-detection test; leading with ENGAGEMENT (0.55/0.30/0.15)
and bounding every term to [0, 1] reaches 0.91-0.93 and makes the 0-100 score
threshold-able (the old unbounded engagement reached ~13071, so the pack threshold
of 70 was meaningless). Engagement carries the signal (AUC 0.91/0.94; 0.83 even for
single-channel early movers); reach is corroboration; the temporal term is the
weakest, so it keeps the smallest weight.

TASK-124 (S3): the old `velocity` sub-term was degenerate (`log1p(max(Δch-1,0)) /
max(Δhours,1h) / BURST_SCALE` → AUC≈0.07 on raw data; ≈0 on the 34/35 single-channel
judged clusters — a dead temporal slot). It is replaced by a bounded `temporal` term
= a convex combination of the positive-part EWMA acceleration (Cheng 2014: temporal
features dominate early virality) and the cross-channel breadth velocity (the spread
moat), REUSING the unit-tested pure features from `eval.science_features` (no
reimplementation — AC4). When a cluster carries no per-post event stream (offline /
eval / fallback consumers), the term degrades gracefully to the breadth half computed
from the aggregates (accel undefined → 0).

The function is platform-independent: it consumes already-normalized aggregates,
performs no I/O, queries no DB, and imports nothing from `collector`/Telethon (AC2).
All weights/coefficients are NAMED constants. Guards keep the formula total over
degenerate inputs (Δhours→0, watched==0, empty events) instead of raising.
"""

import math
from dataclasses import dataclass

from eval.science_features import TimedEvent, breadth_velocity, ewma_acceleration

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

# --- Temporal term (TASK-124, S3): bounded EWMA-accel(+) + breadth velocity. ------
#
# The third score term ("velocity" slot, temporal semantics). It is a convex
# combination of two unit-normalized, REUSED science features (eval.science_features,
# unit-tested under TASK-113) and is clamped to [0, 1] so `temporal·0.15` can never
# dominate the engagement-led v2 formula.
#
# `EWMA_HALF_LIFE_SECONDS` — the EWMA half-life passed to `ewma_acceleration` for
#   signature symmetry with the EWMA family; 1 hour mirrors the burst window so the
#   "recent activity weighted more" horizon matches the score's recency horizon.
# `ACCEL_SCALE` — saturation point (events/hour) of the positive-part acceleration:
#   a window whose second half adds ≥ ACCEL_SCALE more events/hour than its first is
#   maximally "accelerating" → norm_accel = 1.
# `BREADTH_SCALE` — saturation point (distinct channels/hour) of the breadth velocity:
#   a story reaching ≥ BREADTH_SCALE distinct channels/hour is maximally broad. Chosen
#   well above the realistic cross-channel-spread rate so the term stays discriminative
#   (monotone, non-saturating) across the observed range.
# `ACCEL_WEIGHT` / `BREADTH_WEIGHT` — the temporal term's INTERNAL convex weights
#   (sum to 1.0): acceleration ("is it speeding up?", Cheng 2014) and breadth ("is it
#   spreading across channels?", the moat) contribute equally.
EWMA_HALF_LIFE_SECONDS = 3600.0
ACCEL_SCALE = 10.0
BREADTH_SCALE = 30.0
ACCEL_WEIGHT = 0.5
BREADTH_WEIGHT = 0.5

# Reused as the fallback denominator floor (events-empty path): a sub-1h window is
# floored to 1 HOUR so a near-zero window can't manufacture a spurious breadth rate
# (this is the v2 burst floor, kept; the old 1-minute clamp let a lone instant post
# saturate). The unit weight per ScoreEvent maps a post to one science TimedEvent.
BURST_FLOOR_HOURS = 1.0
_EVENT_WEIGHT = 1.0

# Breadth is a CROSS-channel signal: cross-channel spread is undefined for a single
# channel, so the breadth half contributes 0 unless the cluster spans ≥ 2 distinct
# channels (TASK-124 DEBUG fix). Without this gate a single-channel cluster's breadth
# velocity = 1 distinct channel / (sub-minute span floor) → ≈ 60 ch/hr → saturates
# BREADTH_SCALE → 0.5·1.0 temporal, re-introducing the very degeneracy the temporal
# term was meant to remove (77% of live clusters are single-post, ALL single-channel).
# This mirrors the old velocity intent `log1p(max(Δchannels-1, 0))`, which is 0 for
# one channel. The acceleration half is naturally ≈ 0 on such collapsed windows, so the
# whole temporal term correctly collapses to ≈ 0 for single-channel clusters.
MIN_BREADTH_CHANNELS = 2

# Lower/upper bounds for the cross-channel ratio (unique ≤ watched by definition;
# clamp dirty data into the unit interval — invariant cross_channel ∈ [0, 1]).
_CROSS_CHANNEL_MIN = 0.0
_CROSS_CHANNEL_MAX = 1.0


@dataclass(frozen=True)
class ScoreEvent:
    """One per-post event projected into the temporal term: WHEN it ran + WHICH channel.

    Built upstream (scorer/tasks.py) from a cluster's recent posts
    (`epoch = posted_at.timestamp()`, `channel_id`). It is the minimal projection the
    reused science features (`eval.science_features`) need — no raw text, metrics-only
    (compliance). Optional: when absent, the temporal term falls back to the aggregates.
    """

    epoch: float
    channel_id: int


@dataclass(frozen=True)
class ScoreInputs:
    """Normalized, platform-independent aggregates a cluster's score is computed from.

    These are derived upstream (scorer/tasks.py) from a cluster's recent posts —
    the scorer itself never touches the DB or a platform SDK.

    `events` (TASK-124) is the OPTIONAL per-post event stream feeding the temporal
    term. It defaults to `()` so every existing consumer that builds `ScoreInputs` from
    aggregates alone (offline replay, eval gate, the formula-fallback model, scenarios)
    keeps working unchanged — the temporal term then degrades to its breadth half
    computed from the aggregates. New field added LAST → keyword/positional safe.
    """

    views: int
    forwards: int
    reactions: int
    channel_avg: float
    delta_channel_count: int
    delta_hours: float
    unique_channels_count: int
    watched_channels_count: int
    events: tuple[ScoreEvent, ...] = ()


def _temporal(
    *,
    events: tuple[ScoreEvent, ...],
    delta_channel_count: int,
    delta_hours: float,
) -> float:
    """Bounded temporal term ∈ [0, 1] (TASK-124): convex combo of EWMA-accel(+) + breadth.

        temporal = clamp( ACCEL_WEIGHT·norm_accel + BREADTH_WEIGHT·norm_breadth , 0, 1 )

    where each sub-feature is unit-normalized by a named scale and clamped:

    - `norm_accel = min(max(ewma_acceleration(events), 0) / ACCEL_SCALE, 1)` — the
      POSITIVE PART of the early-window acceleration (an accelerating cascade is the
      early-virality signal; a decaying one is not penalised below the breadth half, so
      the term stays ≥ 0). Needs ≥ 2 events spanning a non-zero duration, else 0.
    - `norm_breadth = min(breadth_velocity(events) / BREADTH_SCALE, 1)` — distinct
      channels/hour (cross-channel spread speed, the product's moat signal). GATED to 0
      when the cluster spans < `MIN_BREADTH_CHANNELS` distinct channels: cross-channel
      spread is a cross-CHANNEL signal, so a single channel contributes ZERO breadth
      (else a lone post over the sub-minute span floor saturates the term — TASK-124).

    Both are computed by the REUSED pure functions from `eval.science_features` (mapping
    each `ScoreEvent` to a `TimedEvent(epoch, source_id=channel_id, weight=1)`) — the
    formula is never reimplemented here (AC4).

    Graceful fallback (AC3): when `events` is empty (offline / eval / formula-fallback
    consumers carry only aggregates), the acceleration half is undefined → 0 and the
    breadth half is computed from the aggregates instead:
    `breadth = delta_channel_count / max(delta_hours, BURST_FLOOR_HOURS)`, same
    normalization. This is what the S0 eval-gate exercises on B1 snapshots (the
    accel half is validated by unit tests + measured live on prod scores).

    Replaces the old degenerate `_velocity` (TASK-086/124): a single-channel cluster no
    longer scores ≈ max — its breadth half is GATED to 0 (cross-channel spread needs
    ≥ `MIN_BREADTH_CHANNELS` channels) and its acceleration is ≈ 0 on a collapsed window,
    so temporal collapses to ≈ 0.
    """
    if events:
        timed = [
            TimedEvent(epoch=event.epoch, source_id=event.channel_id, weight=_EVENT_WEIGHT)
            for event in events
        ]
        accel = ewma_acceleration(timed, half_life_seconds=EWMA_HALF_LIFE_SECONDS)
        norm_accel = min(max(accel, 0.0) / ACCEL_SCALE, 1.0)
        # Breadth is cross-channel: a single channel contributes ZERO breadth.
        distinct_channels = len({event.channel_id for event in events})
        if distinct_channels >= MIN_BREADTH_CHANNELS:
            norm_breadth = min(breadth_velocity(timed) / BREADTH_SCALE, 1.0)
        else:
            norm_breadth = 0.0
    else:
        # Fallback: no event stream → acceleration undefined (0); breadth from aggregates.
        norm_accel = 0.0
        # Same cross-channel gate as the events path: < MIN_BREADTH_CHANNELS distinct
        # channels (here the aggregate delta_channel_count) → zero breadth.
        if delta_channel_count >= MIN_BREADTH_CHANNELS:
            breadth_rate = delta_channel_count / max(delta_hours, BURST_FLOOR_HOURS)
            norm_breadth = min(breadth_rate / BREADTH_SCALE, 1.0)
        else:
            norm_breadth = 0.0
    temporal = ACCEL_WEIGHT * norm_accel + BREADTH_WEIGHT * norm_breadth
    return min(max(temporal, 0.0), 1.0)


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

    `velocity` carries the bounded TEMPORAL term (TASK-124) — the field/column name is
    kept for schema/API backwards-compatibility (`scores.velocity`, `live_velocity`),
    but its value is `_temporal`, not the old degenerate burst.
    """

    velocity: float
    engagement: float
    cross_channel: float
    viral_score: float


def compute_components(inputs: ScoreInputs) -> ScoreComponents:
    """Compute the three components and their weighted sum in one deterministic pass."""
    # The bounded temporal term occupies the `velocity` slot (name kept for the
    # `scores.velocity` column / `live_velocity` API contract — TASK-124).
    velocity = _temporal(
        events=inputs.events,
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
