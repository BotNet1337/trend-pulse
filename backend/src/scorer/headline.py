"""Headline signal score — the v2 viral score made NOISE-AWARE and INDEPENDENCE-WEIGHTED.

This is the sellable signal (product strategy: channel-independence / anti-shill is the
moat). It wraps the pure v2 score (`scorer.score`) with two corrections:

  • REACH counts INDEPENDENT sources, not raw channels — a 10-channel shill ring
    (effective independent reach ≈ 1, via `scorer.independence`) scores like ONE
    channel, not ten. Both the cross-channel term AND the spread-burst breadth use the
    independent count.
  • NOISE is excluded — a PROMO or COORDINATED cluster (via `scorer.noise_filter`)
    scores 0; only ORGANIC virality earns a score.

Pure: composes the existing v2 components (same weights, same [0,100] scale) — no new
magic literals, no I/O (ADR-001).
"""

import math

from scorer import score as v2
from scorer.noise_filter import SignalKind
from scorer.score import ScoreInputs


def compute_headline_score(
    *,
    base: ScoreInputs,
    effective_independent_channels: float,
    signal_kind: SignalKind,
) -> float:
    """Noise-aware, independence-weighted viral score in [0, 100].

    `base` carries the raw aggregates (views/forwards/reactions, delta_hours, watched
    count); `effective_independent_channels` is `independence.effective_independent_reach`
    for the cluster (a float — a shill ring collapses toward 1); `signal_kind` is the
    `noise_filter` verdict. Non-organic → 0.0.
    """
    if signal_kind is not SignalKind.ORGANIC:
        return 0.0

    engagement = v2._engagement(
        views=base.views, forwards=base.forwards, reactions=base.reactions
    )

    independent = max(effective_independent_channels, 0.0)
    watched = base.watched_channels_count
    reach = min(independent / watched, 1.0) if watched > 0 else 0.0

    # Spread burst over INDEPENDENT breadth (round to the nearest whole source so a
    # lone independent channel contributes no cross-channel spread, matching v2).
    burst = v2._velocity(
        delta_channel_count=math.floor(independent + 0.5),
        delta_hours=base.delta_hours,
    )

    return v2.SCORE_SCALE * (
        burst * v2.VELOCITY_WEIGHT
        + engagement * v2.ENGAGEMENT_WEIGHT
        + reach * v2.CROSS_CHANNEL_WEIGHT
    )
