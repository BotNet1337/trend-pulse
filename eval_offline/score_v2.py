"""Reformulated viral-score v2 — derived from the predictive eval (harness2).

WHY v2: on a clean time-split predictive test the prod formula scored ROC-AUC 0.247
(eventual reach) / 0.403 (eventual engagement) — BELOW random — because `velocity`
= log1p(Δchannel)/Δhours collapses to its clamp floor for 85% of clusters (single
post, Δhours→1min) and DOMINATES at weight 0.4, inverting the ranking. The eval
showed the real, decoupled signal lives in (in order):
    log(engagement)  AUC 0.908/0.937   ← dominant, carries the early-mover signal (0.83)
    reach / burst    AUC 0.821          ← cross-channel corroboration + spread speed
    #posts           AUC 0.819
A logistic blend of these early features hit AUC 0.934/0.941. v2 is a deterministic,
explainable approximation of that blend (no pickled model in the pipeline).

DESIGN: three bounded components in [0, 1], weighted (weights ≈ standardized logistic
coefficients, engagement-dominant). Same inputs as prod `ScoreInputs`, so it is a
drop-in replacement for `compute_viral_score`.

  engagement_c = min(log1p(weighted_engagement) / LOG_ENG_SCALE, 1)
  reach_c      = unique_channels / watched                       (== old cross_channel)
  burst_c      = min( log1p(unique_channels) / max(Δhours, BURST_FLOOR_H) / BURST_SCALE, 1)
                 ← REDESIGNED velocity: cross-channel SPREAD speed (breadth/time),
                   NOT single-channel instant; floored at 1h so an instant post never
                   saturates, numerator is breadth (channels) not the constant Δ=1.

  viral_score  = W_ENG·engagement_c + W_REACH·reach_c + W_BURST·burst_c   ∈ [0, 1]

Because v2 ∈ [0,1], the alert threshold becomes a real probability-like cutoff (the
old default 70 was unreachable — prod scores ranged [0.22, 17.1]).
"""

import math
from dataclasses import dataclass

# Engagement coefficients — unchanged from prod (a forward > a reaction > a view).
FORWARD_FACTOR = 3
REACTION_FACTOR = 2

# Component weights (sum to 1.0) — engagement-dominant, matching the validated blend.
W_ENG = 0.55
W_REACH = 0.30
W_BURST = 0.15

# log1p(weighted_engagement) scale: ~ the 99th pct of log-engagement in the 9-month
# crypto-RU corpus (≈ e^14). Caps engagement_c at 1 for the very largest stories.
LOG_ENG_SCALE = 14.0
# Burst: floor the spread window at 1 HOUR (not 1 minute) so a single instant post
# can't saturate the term, and divide breadth-per-hour by this scale to land in [0,1].
BURST_FLOOR_H = 1.0
BURST_SCALE = 3.0


@dataclass(frozen=True)
class ScoreInputsV2:
    """Same shape as prod ScoreInputs (drop-in)."""

    views: int
    forwards: int
    reactions: int
    delta_hours: float
    unique_channels_count: int
    watched_channels_count: int


@dataclass(frozen=True)
class ScoreComponentsV2:
    engagement: float
    reach: float
    burst: float
    viral_score: float


def _engagement_c(views: int, forwards: int, reactions: int) -> float:
    weighted = float(views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR)
    return min(math.log1p(weighted) / LOG_ENG_SCALE, 1.0)


def _reach_c(unique_channels_count: int, watched_channels_count: int) -> float:
    if watched_channels_count <= 0:
        return 0.0
    return min(max(unique_channels_count / watched_channels_count, 0.0), 1.0)


def _burst_c(unique_channels_count: int, delta_hours: float) -> float:
    hours = max(delta_hours, BURST_FLOOR_H)
    rate = math.log1p(unique_channels_count) / hours  # breadth per hour
    return min(rate / BURST_SCALE, 1.0)


def compute_components_v2(inputs: ScoreInputsV2) -> ScoreComponentsV2:
    eng = _engagement_c(inputs.views, inputs.forwards, inputs.reactions)
    reach = _reach_c(inputs.unique_channels_count, inputs.watched_channels_count)
    burst = _burst_c(inputs.unique_channels_count, inputs.delta_hours)
    viral = W_ENG * eng + W_REACH * reach + W_BURST * burst
    return ScoreComponentsV2(engagement=eng, reach=reach, burst=burst, viral_score=viral)


def compute_viral_score_v2(inputs: ScoreInputsV2) -> float:
    return compute_components_v2(inputs).viral_score
