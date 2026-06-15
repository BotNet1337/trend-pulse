"""C2 — science-grounded early-window virality features (incremental, measure lift).

TASK-113 (Track B→C / C2). Each function turns a cluster's EARLY, time-ordered event
window into one extra leak-free feature, grounded in a named result from the cascade /
self-exciting-process literature. They are pure, immutable, numpy-free and unit-tested
so the lift each adds (measured in the eval_offline harness) is reproducible. The
features extend the B1/B2 base vector; the harness reports the marginal PR-AUC each
contributes so we keep only the ones that pay.

Feature catalogue (the WHY each is expected to carry early-virality signal):

- **EWMA velocity + acceleration** — an exponentially-weighted event rate weights the
  most recent activity more than the burst-floor average, and its change (acceleration)
  distinguishes an accelerating cascade from a decaying one.
- **cross-channel breadth velocity** — distinct-source growth per unit time; cross-
  channel spread is the product's target signal (single-channel is filtered by B0).
- **Hawkes branching ratio** (Mishra et al. CIKM'16 hybrid) — the self-exciting
  branching factor n*: how many follow-on events each event triggers. n* >= 1 is a
  super-critical (virally self-sustaining) cascade; n* < 1 is sub-critical.
- **time-of-day phase (TiDeH)** — circadian phase of the birth time; human attention
  (and thus reshare probability) is periodic over the day (Kobayashi & Lambiotte 2016).
- **effective independent sources = exp(source-entropy)** — the diversity moat: a story
  pushed by N truly-independent sources has higher entropy than one amplified by one
  account across aliases (collusion). exp(H) is the "effective number" of sources.
- **channel authority (TunkRank-style)** — a one-pass influence estimate over the early
  interaction graph: a source that many distinct targets engage with carries weight.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

# Named constants (no magic literals; time in seconds).
_SECONDS_PER_HOUR = 3600.0
_MIN_SPAN_HOURS = 1.0 / 60.0  # 1-minute floor (mirrors the score's burst floor)
_HOURS_PER_DAY = 24.0


class ScienceFeatureError(ValueError):
    """A science-feature input was malformed (bad ordering, empty, negative)."""


@dataclass(frozen=True)
class TimedEvent:
    """One early event: WHEN it happened + WHO produced it (source) + a weight.

    The minimal projection every substrate (TG posts, Higgs interactions) maps into so
    the C2 features are substrate-agnostic. Validated at construction.
    """

    epoch: float
    source_id: int
    weight: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.epoch):
            raise ScienceFeatureError(f"epoch must be finite, got {self.epoch}")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ScienceFeatureError(f"weight must be finite and >= 0, got {self.weight}")


def _sorted_epochs(events: Sequence[TimedEvent]) -> list[float]:
    return sorted(event.epoch for event in events)


def ewma_velocity(events: Sequence[TimedEvent], *, half_life_seconds: float) -> float:
    """Exponentially-weighted event rate (events/hour), recent activity weighted more.

    Each event contributes ``0.5 ** (age / half_life)`` (age relative to the LAST early
    event), summed and divided by the early span in hours. Empty window → 0.0. A
    non-positive half-life is rejected (would divide by zero in the exponent).
    """
    if half_life_seconds <= 0:
        raise ScienceFeatureError(f"half_life_seconds must be > 0, got {half_life_seconds}")
    if not events:
        return 0.0
    epochs = _sorted_epochs(events)
    last = epochs[-1]
    weighted = sum(0.5 ** ((last - t) / half_life_seconds) for t in epochs)
    span_hours = max((last - epochs[0]) / _SECONDS_PER_HOUR, _MIN_SPAN_HOURS)
    return weighted / span_hours


def ewma_acceleration(events: Sequence[TimedEvent], *, half_life_seconds: float) -> float:
    """Event-rate change between the first and second half of the early window (per hour).

    Splits the window at its temporal midpoint and compares the EVENT RATE (count / half-
    span-hours) of each half: positive = the cascade is accelerating (later half busier),
    negative = decaying. Using a count-rate (not the floor-sensitive EWMA velocity) keeps
    the sign meaningful even when one half has a single event. ``half_life_seconds`` is
    accepted for signature symmetry with the EWMA family + validated. Needs >= 2 events
    spanning a non-zero duration; otherwise 0.0 (no trend defined).
    """
    if half_life_seconds <= 0:
        raise ScienceFeatureError(f"half_life_seconds must be > 0, got {half_life_seconds}")
    epochs = _sorted_epochs(events)
    if len(epochs) < 2 or epochs[-1] == epochs[0]:
        return 0.0
    mid = epochs[0] + (epochs[-1] - epochs[0]) / 2.0
    half_hours = max((epochs[-1] - epochs[0]) / 2.0 / _SECONDS_PER_HOUR, _MIN_SPAN_HOURS)
    first_count = sum(1 for t in epochs if t <= mid)
    second_count = sum(1 for t in epochs if t > mid)
    return (second_count - first_count) / half_hours


def breadth_velocity(events: Sequence[TimedEvent]) -> float:
    """Distinct-source growth per hour over the early window (cross-channel spread speed).

    distinct sources / early-span-hours (1-min floor). Empty → 0.0. This is the C2
    analogue of the B1 breadth_velocity but computed from the event stream directly.
    """
    if not events:
        return 0.0
    epochs = _sorted_epochs(events)
    distinct = len({event.source_id for event in events})
    span_hours = max((epochs[-1] - epochs[0]) / _SECONDS_PER_HOUR, _MIN_SPAN_HOURS)
    return distinct / span_hours


def hawkes_branching_ratio(events: Sequence[TimedEvent], *, decay_seconds: float) -> float:
    """A simple moment estimate of the Hawkes branching ratio n* (self-excitation).

    Estimates n* as the mean number of "offspring" each event triggers within one decay
    constant: for each event, count later events within ``decay_seconds`` and average.
    n* >= 1 ≈ super-critical (virally self-sustaining); n* < 1 ≈ sub-critical. This is a
    deliberately cheap, monotone proxy for the Mishra CIKM'16 hybrid feature (not a full
    MLE fit). Needs >= 2 events; fewer → 0.0. Non-positive decay is rejected.
    """
    if decay_seconds <= 0:
        raise ScienceFeatureError(f"decay_seconds must be > 0, got {decay_seconds}")
    epochs = _sorted_epochs(events)
    n = len(epochs)
    if n < 2:
        return 0.0
    total_offspring = 0
    for i, t in enumerate(epochs):
        j = i + 1
        while j < n and epochs[j] - t <= decay_seconds:
            j += 1
        total_offspring += j - (i + 1)
    return total_offspring / n


def time_of_day_phase(birth_epoch: float) -> float:
    """TiDeH circadian phase of the cascade's birth, in [0, 1) (fraction of the UTC day).

    A periodic feature: human attention (reshare probability) is diurnal. Returned as a
    fraction of the day so a tree split on it captures "born in the active evening
    window" vs "born at the dead-of-night trough".
    """
    if not math.isfinite(birth_epoch):
        raise ScienceFeatureError(f"birth_epoch must be finite, got {birth_epoch}")
    seconds_into_day = birth_epoch % (_HOURS_PER_DAY * _SECONDS_PER_HOUR)
    return seconds_into_day / (_HOURS_PER_DAY * _SECONDS_PER_HOUR)


def source_entropy(events: Sequence[TimedEvent]) -> float:
    """Shannon entropy (nats) of the early per-source event distribution.

    High entropy = activity spread evenly across many sources (independent spread);
    low entropy = dominated by one source (self-amplification / collusion). Empty → 0.0.
    """
    if not events:
        return 0.0
    counts = Counter(event.source_id for event in events)
    total = sum(counts.values())
    return -sum((c / total) * math.log(c / total) for c in counts.values())


def effective_independent_sources(events: Sequence[TimedEvent]) -> float:
    """exp(source-entropy) — the "effective number" of independent sources (moat signal).

    A story genuinely spread by N independent sources has effective ≈ N; one amplified by
    a single account across aliases collapses toward 1 even if the raw source count is
    high. This is the independence/collusion feature the product strategy calls a moat.
    Empty window → 0.0.
    """
    if not events:
        return 0.0
    return math.exp(source_entropy(events))


def channel_authority(events: Sequence[TimedEvent]) -> float:
    """TunkRank-style one-pass authority of the cascade's most-engaged early source.

    For each source, authority = the number of DISTINCT other sources that appear in the
    window (a one-pass proxy for "how many independent actors this content reached"),
    scaled by the source's own activity share. Returns the MAX source authority — the
    influence of the cascade's strongest early mover. Empty → 0.0.

    This is a cheap, deterministic stand-in for the iterative TunkRank influence score
    (Tunkelang 2009); the eval harness measures whether it adds lift before any heavier
    graph computation is justified.
    """
    if not events:
        return 0.0
    counts = Counter(event.source_id for event in events)
    total = sum(counts.values())
    distinct_sources = len(counts)
    # authority(s) = activity_share(s) * (reach = distinct sources in the window).
    # The strongest early mover's authority summarises the cascade's influence core.
    return max((count / total) * distinct_sources for count in counts.values())


@dataclass(frozen=True)
class ScienceFeatures:
    """The full C2 feature bundle for one early window (all leak-free, early-only)."""

    ewma_velocity: float
    ewma_acceleration: float
    breadth_velocity: float
    hawkes_branching: float
    time_of_day_phase: float
    effective_independent_sources: float
    channel_authority: float


def compute_science_features(
    events: Sequence[TimedEvent],
    *,
    birth_epoch: float,
    ewma_half_life_seconds: float,
    hawkes_decay_seconds: float,
) -> ScienceFeatures:
    """Compute every C2 feature for one early window in a single pass of helpers."""
    return ScienceFeatures(
        ewma_velocity=ewma_velocity(events, half_life_seconds=ewma_half_life_seconds),
        ewma_acceleration=ewma_acceleration(events, half_life_seconds=ewma_half_life_seconds),
        breadth_velocity=breadth_velocity(events),
        hawkes_branching=hawkes_branching_ratio(events, decay_seconds=hawkes_decay_seconds),
        time_of_day_phase=time_of_day_phase(birth_epoch),
        effective_independent_sources=effective_independent_sources(events),
        channel_authority=channel_authority(events),
    )
