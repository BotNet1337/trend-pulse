"""AC1 + AC2 — deterministic viral score v2 + platform-independence.

AC1 (RED anchor): `compute_viral_score(<known inputs>)` equals a by-hand value from
the v2 formula `100·(temporal·0.15 + engagement·0.55 + cross_channel·0.30)` with every
component bounded to [0, 1]. The `temporal` term (carried in the `velocity` slot for
schema/API compatibility — TASK-124) is a convex combination of the positive-part
EWMA acceleration and the cross-channel breadth velocity, reusing the pure science
features from `eval/science_features.py`. AC2: the `scorer/` package imports cleanly
without any `collector.telegram` (or platform SDK) dependency — platform-independent
(ADR-001).

All cases are DB-free (pure compute) so they run under `make ci-fast`.
"""

import ast
import inspect
import math
from types import ModuleType

import pytest

from eval.science_features import TimedEvent, breadth_velocity, ewma_acceleration
from scorer import compute_viral_score
from scorer.score import (
    ACCEL_SCALE,
    ACCEL_WEIGHT,
    BREADTH_SCALE,
    BREADTH_WEIGHT,
    BURST_FLOOR_HOURS,
    CROSS_CHANNEL_WEIGHT,
    ENGAGEMENT_WEIGHT,
    EWMA_HALF_LIFE_SECONDS,
    FORWARD_FACTOR,
    LOG_ENGAGEMENT_SCALE,
    MIN_BREADTH_CHANNELS,
    REACTION_FACTOR,
    SCORE_SCALE,
    VELOCITY_WEIGHT,
    ScoreEvent,
    ScoreInputs,
    _cross_channel,
    _engagement,
    _temporal,
)

_SECONDS_PER_HOUR = 3600.0


def _expected(
    *,
    views: int,
    forwards: int,
    reactions: int,
    delta_channel_count: int,
    delta_hours: float,
    unique_channels_count: int,
    watched_channels_count: int,
) -> float:
    """Hand formula mirror for the EVENTS-EMPTY (breadth-fallback) path (TASK-124)."""
    weighted = views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR
    engagement = min(math.log1p(weighted) / LOG_ENGAGEMENT_SCALE, 1.0)
    # temporal fallback: accel=0; breadth from aggregates / floored window / scale.
    breadth = delta_channel_count / max(delta_hours, BURST_FLOOR_HOURS)
    norm_breadth = min(breadth / BREADTH_SCALE, 1.0)
    temporal = min(max(BREADTH_WEIGHT * norm_breadth, 0.0), 1.0)
    cross = unique_channels_count / watched_channels_count
    return SCORE_SCALE * (
        temporal * VELOCITY_WEIGHT + engagement * ENGAGEMENT_WEIGHT + cross * CROSS_CHANNEL_WEIGHT
    )


def test_compute_viral_score_matches_hand_computed_value() -> None:
    # Known inputs (NO per-post events) → a precomputed expected number using the
    # temporal breadth-fallback (accel=0); v2 formula, bounded components x100.
    inputs = ScoreInputs(
        views=1000,
        forwards=50,
        reactions=200,
        channel_avg=500.0,
        delta_channel_count=47,
        delta_hours=0.5,
        unique_channels_count=8,
        watched_channels_count=10,
    )
    # engagement   = min(log1p(1550)/14, 1) = 7.346655.../14 = 0.524761...
    # temporal     = clamp(0.5·0 + 0.5·min((47/max(0.5,1))/30, 1), 0, 1)
    #              = 0.5·min(47/30, 1) = 0.5·1.0 = 0.5  (breadth saturates)
    # cross        = 8/10 = 0.8
    # viral = 100·(0.5·0.15 + 0.524761·0.55 + 0.8·0.30) = 60.36188...
    expected = 60.361876672946
    assert compute_viral_score(inputs) == pytest.approx(expected)
    assert compute_viral_score(inputs) == pytest.approx(
        _expected(
            views=1000,
            forwards=50,
            reactions=200,
            delta_channel_count=47,
            delta_hours=0.5,
            unique_channels_count=8,
            watched_channels_count=10,
        )
    )
    # v2 invariant: viral_score is bounded to [0, 100].
    assert 0.0 <= compute_viral_score(inputs) <= 100.0


def test_compute_viral_score_is_deterministic() -> None:
    inputs = ScoreInputs(
        views=42,
        forwards=3,
        reactions=7,
        channel_avg=20.0,
        delta_channel_count=5,
        delta_hours=2.0,
        unique_channels_count=3,
        watched_channels_count=4,
    )
    assert compute_viral_score(inputs) == compute_viral_score(inputs)


def test_viral_score_is_bounded_unit_times_scale() -> None:
    # v2 invariant: every component ∈ [0,1], weights sum to 1 → viral_score ∈ [0, SCORE_SCALE].
    # TASK-124: an EVENTS-FULL extreme (mega accel + mega breadth) saturates temporal to
    # 1.0 → engagement & cross also saturate → the whole score reaches SCORE_SCALE.
    # Back-loaded burst: 2 early events then 498 in the final second → huge acceleration;
    # all distinct channels → huge breadth. Both halves of temporal saturate to 1.
    early = [ScoreEvent(epoch=float(i), channel_id=i) for i in range(2)]
    burst = [ScoreEvent(epoch=99.0 + i / 1000.0, channel_id=2 + i) for i in range(498)]
    events = tuple(early + burst)
    extreme = ScoreInputs(
        views=10_000_000,
        forwards=1_000_000,
        reactions=1_000_000,
        channel_avg=1.0,
        delta_channel_count=500,
        delta_hours=0.0,
        unique_channels_count=500,
        watched_channels_count=10,  # unique > watched → cross clamps to 1
        events=events,
    )
    assert compute_viral_score(extreme) == pytest.approx(SCORE_SCALE)
    assert pytest.approx(VELOCITY_WEIGHT + ENGAGEMENT_WEIGHT + CROSS_CHANNEL_WEIGHT) == 1.0


def test_viral_score_fallback_temporal_maxes_at_breadth_half() -> None:
    # TASK-124 (new semantics, justified): with NO event stream the acceleration half is
    # structurally 0, so the fallback temporal term tops out at BREADTH_WEIGHT (0.5) even
    # for a maximal breadth — UNLIKE the old `_velocity` which saturated to 1.0. The score
    # is still bounded [0, 100]; only its temporal ceiling differs from the events-full path.
    extreme = ScoreInputs(
        views=10_000_000,
        forwards=1_000_000,
        reactions=1_000_000,
        channel_avg=1.0,
        delta_channel_count=500,
        delta_hours=0.0,
        unique_channels_count=500,
        watched_channels_count=10,
    )
    components = compute_viral_score(extreme)
    # temporal = BREADTH_WEIGHT (0.5); engagement = 1; cross = 1.
    expected = SCORE_SCALE * (
        BREADTH_WEIGHT * VELOCITY_WEIGHT + 1.0 * ENGAGEMENT_WEIGHT + 1.0 * CROSS_CHANNEL_WEIGHT
    )
    assert components == pytest.approx(expected)
    assert 0.0 <= components <= SCORE_SCALE


# --- temporal = bounded EWMA-accel(+) + breadth velocity (TASK-124). ---------- #
# It is carried in the `velocity` field/column (name unchanged for schema/API
# compatibility), but the SEMANTICS are the new temporal term.


def _events(*pairs: tuple[float, int]) -> tuple[ScoreEvent, ...]:
    """Build a ScoreEvent tuple from (epoch_seconds, channel_id) pairs."""
    return tuple(ScoreEvent(epoch=epoch, channel_id=channel_id) for (epoch, channel_id) in pairs)


def _temporal_internals(events: tuple[ScoreEvent, ...]) -> tuple[float, float]:
    """Mirror the reused science-feature calls (accel, breadth) for a given event set."""
    timed = [TimedEvent(epoch=ev.epoch, source_id=ev.channel_id, weight=1.0) for ev in events]
    accel = ewma_acceleration(timed, half_life_seconds=EWMA_HALF_LIFE_SECONDS)
    breadth = breadth_velocity(timed)
    norm_accel = min(max(accel, 0.0) / ACCEL_SCALE, 1.0)
    norm_breadth = min(breadth / BREADTH_SCALE, 1.0)
    return norm_accel, norm_breadth


def test_temporal_matches_reused_science_features() -> None:
    # A real cross-channel, accelerating window: temporal = convex combo of the
    # positive-part EWMA acceleration and the breadth velocity (REUSED, not reimpl).
    events = _events(
        (0.0, 1),
        (600.0, 2),
        (1200.0, 3),
        (1500.0, 4),
        (1700.0, 5),
        (1750.0, 6),
    )
    norm_accel, norm_breadth = _temporal_internals(events)
    expected = min(max(ACCEL_WEIGHT * norm_accel + BREADTH_WEIGHT * norm_breadth, 0.0), 1.0)
    got = _temporal(
        events=events,
        delta_channel_count=6,
        delta_hours=(1750.0 / _SECONDS_PER_HOUR),
    )
    assert got == pytest.approx(expected)
    assert 0.0 <= got <= 1.0


def test_temporal_bounded_for_any_input() -> None:
    # AC2: bounded ∈ [0,1] under degenerate / extreme inputs (mega breadth & accel).
    # A burst of many distinct channels in a sub-second window.
    events = _events(*[(float(i) / 1000.0, i) for i in range(200)])
    got = _temporal(events=events, delta_channel_count=200, delta_hours=0.0)
    assert 0.0 <= got <= 1.0


def test_temporal_monotonic_in_acceleration() -> None:
    # Holding breadth fixed (same distinct channels), a MORE accelerating window
    # (more mass in the second half) yields a strictly higher temporal term.
    # 4 distinct channels in both; slow = evenly spread, fast = back-loaded.
    slow = _events((0.0, 1), (1800.0, 2), (3600.0, 3), (5400.0, 4))
    fast = _events((0.0, 1), (3000.0, 2), (5000.0, 3), (5400.0, 4))
    t_slow = _temporal(events=slow, delta_channel_count=4, delta_hours=1.5)
    t_fast = _temporal(events=fast, delta_channel_count=4, delta_hours=1.5)
    # sanity: fast really is the more-accelerating window
    a_slow = ewma_acceleration(
        [TimedEvent(epoch=ev.epoch, source_id=ev.channel_id, weight=1.0) for ev in slow],
        half_life_seconds=EWMA_HALF_LIFE_SECONDS,
    )
    a_fast = ewma_acceleration(
        [TimedEvent(epoch=ev.epoch, source_id=ev.channel_id, weight=1.0) for ev in fast],
        half_life_seconds=EWMA_HALF_LIFE_SECONDS,
    )
    assert a_fast > a_slow
    assert t_fast > t_slow


def test_temporal_monotonic_in_breadth() -> None:
    # Holding the time window + accel comparable, MORE distinct channels (broader
    # cross-channel spread) yields a strictly higher temporal term.
    narrow = _events((0.0, 1), (600.0, 1), (1200.0, 2), (1800.0, 2))  # 2 distinct
    broad = _events((0.0, 1), (600.0, 2), (1200.0, 3), (1800.0, 4))  # 4 distinct
    t_narrow = _temporal(events=narrow, delta_channel_count=2, delta_hours=0.5)
    t_broad = _temporal(events=broad, delta_channel_count=4, delta_hours=0.5)
    assert t_broad > t_narrow


def test_temporal_empty_events_falls_back_to_breadth_aggregates() -> None:
    # AC3: with NO per-post events, temporal is computed from the breadth aggregates
    # (delta_channel_count / floored window / scale); accel half is 0.
    got = _temporal(events=(), delta_channel_count=12, delta_hours=2.0)
    breadth = 12 / max(2.0, BURST_FLOOR_HOURS)
    norm_breadth = min(breadth / BREADTH_SCALE, 1.0)
    expected = min(max(BREADTH_WEIGHT * norm_breadth, 0.0), 1.0)
    assert got == pytest.approx(expected)


def test_temporal_fallback_floors_window_at_burst_floor() -> None:
    # AC2: a sub-floor window cannot inflate the fallback breadth (uses BURST_FLOOR_HOURS).
    sub = _temporal(events=(), delta_channel_count=5, delta_hours=0.0)
    floored = _temporal(events=(), delta_channel_count=5, delta_hours=BURST_FLOOR_HOURS)
    assert sub == pytest.approx(floored)


def test_temporal_single_channel_steady_is_not_degenerate_max() -> None:
    # AC1 (the degeneracy is GONE): a SINGLE-channel cluster with a steady (non-
    # accelerating) post stream over a real window NO LONGER scores ≈ the maximum
    # temporal value. distinct == 1 → breadth ≈ 1/span (tiny after /BREADTH_SCALE) and a
    # steady cadence → ~0 acceleration, so temporal ≪ 1 (the old burst saturated to max
    # on a collapsed window — that path is gone).
    steady_single_channel = _events(
        (0.0, 7),
        (900.0, 7),
        (1800.0, 7),
        (2700.0, 7),
        (3600.0, 7),  # 5 posts, ONE channel, evenly spaced over 1h
    )
    temporal = _temporal(events=steady_single_channel, delta_channel_count=1, delta_hours=1.0)
    # Breadth gated to 0 (one channel) + steady cadence → ~0 accel ⇒ temporal ≈ 0.
    assert temporal == pytest.approx(0.0)
    assert temporal < 0.1  # nowhere near the old ≈max degeneration

    # Contrast: a genuinely accelerating, MULTI-channel cluster scores materially higher.
    multi_accel = _events(
        (0.0, 1),
        (3000.0, 2),
        (3300.0, 3),
        (3500.0, 4),
        (3600.0, 5),
    )
    temporal_multi = _temporal(events=multi_accel, delta_channel_count=5, delta_hours=1.0)
    assert temporal_multi > temporal


def test_temporal_single_post_single_channel_is_zero() -> None:
    # DEBUG TASK-124: a SINGLE-POST single-channel cluster (77% of the live corpus) must
    # NOT score temporal ≈ 0.5. Breadth is a CROSS-channel signal — one channel over the
    # sub-minute span floor was saturating BREADTH_SCALE (60 ch/hr → 0.5·1.0). With the
    # cross-channel gate (distinct < MIN_BREADTH_CHANNELS → breadth 0) and accel ≈ 0 on a
    # collapsed window, temporal collapses to ≈ 0.
    single_post = _events((1000.0, 7))
    temporal = _temporal(events=single_post, delta_channel_count=1, delta_hours=0.0)
    assert temporal == pytest.approx(0.0)
    assert temporal < 0.1


def test_temporal_two_posts_same_epoch_single_channel_is_zero() -> None:
    # DEBUG TASK-124: two posts at the SAME epoch from ONE channel → zero-span, single
    # channel. Accel is 0 (zero span) and breadth is gated to 0 (one channel), so the
    # whole temporal term is ≈ 0 (was 0.5 via the span-floor breadth saturation).
    same_epoch = _events((1000.0, 7), (1000.0, 7))
    temporal = _temporal(events=same_epoch, delta_channel_count=1, delta_hours=0.0)
    assert temporal == pytest.approx(0.0)


def test_temporal_fallback_single_channel_is_zero() -> None:
    # The cross-channel gate is applied CONSISTENTLY in the empty-events breadth fallback:
    # delta_channel_count < MIN_BREADTH_CHANNELS → breadth 0 → temporal 0, so single-
    # channel clusters score temporal ≈ 0 in EVERY path (not just the events path).
    temporal = _temporal(events=(), delta_channel_count=1, delta_hours=0.0)
    assert temporal == pytest.approx(0.0)


def test_temporal_negative_acceleration_does_not_penalise() -> None:
    # A DECAYING window (front-loaded) has negative EWMA acceleration; the positive
    # part clamps it to 0 so the term stays ≥ 0 (never penalised below the breadth half).
    decaying = _events((0.0, 1), (200.0, 2), (400.0, 3), (5400.0, 4))
    accel = ewma_acceleration(
        [TimedEvent(epoch=ev.epoch, source_id=ev.channel_id, weight=1.0) for ev in decaying],
        half_life_seconds=EWMA_HALF_LIFE_SECONDS,
    )
    assert accel < 0  # genuinely decaying
    temporal = _temporal(events=decaying, delta_channel_count=4, delta_hours=1.5)
    _, norm_breadth = _temporal_internals(decaying)
    # positive-part accel → accel half is 0 → temporal == breadth half only.
    assert temporal == pytest.approx(min(max(BREADTH_WEIGHT * norm_breadth, 0.0), 1.0))
    assert temporal >= 0.0


def test_temporal_weights_are_convex() -> None:
    # internal temporal weights are a convex combination (sum to 1.0).
    assert pytest.approx(ACCEL_WEIGHT + BREADTH_WEIGHT) == 1.0


def test_breadth_requires_at_least_two_channels() -> None:
    # The cross-channel gate threshold is 2: breadth (cross-channel spread) is undefined
    # for a single channel. A cluster that JUST crosses the threshold (2 distinct
    # channels) DOES contribute breadth, so the gate discriminates exactly at ≥ 2.
    assert MIN_BREADTH_CHANNELS == 2
    one_channel = _temporal(events=(), delta_channel_count=1, delta_hours=0.5)
    two_channels = _temporal(events=(), delta_channel_count=2, delta_hours=0.5)
    assert one_channel == pytest.approx(0.0)
    assert two_channels > 0.0


# --- engagement = bounded log of the weighted sum (v2; no channel_avg). ---


def test_engagement_is_bounded_log_of_weighted_sum() -> None:
    assert _engagement(views=100, forwards=10, reactions=5) == pytest.approx(
        min(math.log1p(100 + 10 * FORWARD_FACTOR + 5 * REACTION_FACTOR) / LOG_ENGAGEMENT_SCALE, 1.0)
    )


def test_engagement_zero_is_zero() -> None:
    # log1p(0) = 0 → no engagement signal, no division anywhere.
    assert _engagement(views=0, forwards=0, reactions=0) == pytest.approx(0.0)


def test_engagement_clamps_to_one() -> None:
    # Astronomically large engagement saturates at 1.0 (bounded — the old form was not).
    assert _engagement(views=10**9, forwards=0, reactions=0) == pytest.approx(1.0)


def test_engagement_monotonic_and_finite() -> None:
    low = _engagement(views=10, forwards=0, reactions=0)
    high = _engagement(views=10_000, forwards=0, reactions=0)
    assert 0.0 <= low < high <= 1.0
    assert math.isfinite(low) and math.isfinite(high)


# --- cross_channel = reach (unchanged formula). ---


def test_cross_channel_ratio() -> None:
    assert _cross_channel(unique_channels_count=8, watched_channels_count=10) == pytest.approx(0.8)


def test_cross_channel_guards_zero_watched() -> None:
    assert _cross_channel(unique_channels_count=3, watched_channels_count=0) == pytest.approx(0.0)


def test_cross_channel_is_clamped_to_unit_interval() -> None:
    assert _cross_channel(unique_channels_count=15, watched_channels_count=10) == pytest.approx(1.0)


# --- AC2: platform-independence (no collector/telegram import in scorer). ---


def _imported_modules(module: ModuleType) -> set[str]:
    """Collect dotted module names referenced by `import`/`from` in a module."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_score_module_does_not_import_collector() -> None:
    from scorer import score, tasks

    # AC2 — neither the pure formula nor the task wiring may touch the collector /
    # any platform SDK (Telegram-specifics stay in collector/telegram).
    for module in (score, tasks):
        for imported in _imported_modules(module):
            assert not imported.startswith("collector"), (
                f"{module.__name__} must not import {imported} (AC2 — platform-independent)"
            )
