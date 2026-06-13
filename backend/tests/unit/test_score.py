"""AC1 + AC2 — deterministic viral score v2 + platform-independence.

AC1 (RED anchor): `compute_viral_score(<known inputs>)` equals a by-hand value from
the v2 formula `100·(velocity·0.15 + engagement·0.55 + cross_channel·0.30)` with every
component bounded to [0, 1]. AC2: the `scorer/` package imports cleanly without any
`collector.telegram` (or platform SDK) dependency — platform-independent (ADR-001).

All cases are DB-free (pure compute) so they run under `make ci-fast`.
"""

import ast
import inspect
import math
from types import ModuleType

import pytest

from scorer import compute_viral_score
from scorer.score import (
    BURST_SCALE,
    CROSS_CHANNEL_WEIGHT,
    ENGAGEMENT_WEIGHT,
    FORWARD_FACTOR,
    LOG_ENGAGEMENT_SCALE,
    REACTION_FACTOR,
    SCORE_SCALE,
    VELOCITY_WEIGHT,
    ScoreInputs,
    _cross_channel,
    _engagement,
    _velocity,
)


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
    weighted = views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR
    engagement = min(math.log1p(weighted) / LOG_ENGAGEMENT_SCALE, 1.0)
    burst_rate = math.log1p(max(delta_channel_count - 1, 0)) / max(delta_hours, 1.0)
    velocity = min(burst_rate / BURST_SCALE, 1.0)
    cross = unique_channels_count / watched_channels_count
    return SCORE_SCALE * (
        velocity * VELOCITY_WEIGHT + engagement * ENGAGEMENT_WEIGHT + cross * CROSS_CHANNEL_WEIGHT
    )


def test_compute_viral_score_matches_hand_computed_value() -> None:
    # Known inputs → a precomputed expected number (v2 formula, bounded components x100).
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
    # engagement = min(log1p(1550)/14, 1) = 7.346655.../14 = 0.524761...
    # velocity   = min( log1p(46)/max(0.5,1)/3, 1 ) = min(3.850148/3, 1) = 1.0  (saturated)
    # cross      = 8/10 = 0.8
    # viral = 100*(1.0*0.15 + 0.524761*0.55 + 0.8*0.30) = 67.8618...
    expected = 67.86184304172
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
    extreme = ScoreInputs(
        views=10_000_000,
        forwards=1_000_000,
        reactions=1_000_000,
        channel_avg=1.0,
        delta_channel_count=500,
        delta_hours=0.0,
        unique_channels_count=500,
        watched_channels_count=10,  # unique > watched → cross clamps to 1
    )
    assert compute_viral_score(extreme) == pytest.approx(SCORE_SCALE)
    assert pytest.approx(VELOCITY_WEIGHT + ENGAGEMENT_WEIGHT + CROSS_CHANNEL_WEIGHT) == 1.0


# --- velocity = bounded cross-channel burst (T15 spread semantics, v2 bounding). ---


def test_velocity_is_bounded_log1p_burst() -> None:
    # min( log1p(Δch-1) / max(Δhours, 1h) / BURST_SCALE, 1 ).
    assert _velocity(delta_channel_count=47, delta_hours=0.5) == pytest.approx(
        min(math.log1p(46) / max(0.5, 1.0) / BURST_SCALE, 1.0)
    )


def test_velocity_clamps_to_one() -> None:
    # A very wide, very fast spread saturates at 1.0 (cannot dominate the weighted sum).
    assert _velocity(delta_channel_count=1000, delta_hours=0.001) == pytest.approx(1.0)


def test_velocity_floors_window_at_one_hour() -> None:
    # Δhours below the 1h floor is treated as 1h — a near-zero window can't inflate burst.
    assert _velocity(delta_channel_count=10, delta_hours=0.0) == pytest.approx(
        _velocity(delta_channel_count=10, delta_hours=1.0)
    )


def test_velocity_single_channel_is_zero() -> None:
    # T15 (kept): a story on ONE channel has NO cross-channel spread → 0, any window.
    assert _velocity(delta_channel_count=1, delta_hours=2.0) == pytest.approx(0.0)
    assert _velocity(delta_channel_count=1, delta_hours=0.0) == pytest.approx(0.0)


def test_velocity_zero_channels_is_zero() -> None:
    assert _velocity(delta_channel_count=0, delta_hours=1.0) == pytest.approx(0.0)


def test_velocity_two_channels_is_positive() -> None:
    assert _velocity(delta_channel_count=2, delta_hours=2.0) > 0


def test_velocity_monotonic_in_channels() -> None:
    # More channels spreading (same window, below clamp) → strictly higher burst.
    prev = _velocity(delta_channel_count=1, delta_hours=4.0)
    for n in range(2, 12):
        cur = _velocity(delta_channel_count=n, delta_hours=4.0)
        assert cur > prev
        prev = cur


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
