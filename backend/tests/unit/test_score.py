"""AC1 + AC2 — deterministic viral score + platform-independence.

AC1 (RED anchor): `compute_viral_score(<known inputs>)` equals a by-hand value
from overview §4's formula (`velocity·0.4 + engagement·0.35 + cross_channel·0.25`).
AC2: the `scorer/` package imports cleanly without any `collector.telegram` (or
platform SDK) dependency — the scorer is platform-independent (ADR-001).

All cases are DB-free (pure compute) so they run under `make ci-fast`.
"""

import ast
import inspect
import math
from types import ModuleType

import pytest

from scorer import compute_viral_score
from scorer.score import (
    CROSS_CHANNEL_WEIGHT,
    ENGAGEMENT_WEIGHT,
    FORWARD_FACTOR,
    REACTION_FACTOR,
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
    channel_avg: float,
    delta_channel_count: int,
    delta_hours: float,
    unique_channels_count: int,
    watched_channels_count: int,
) -> float:
    velocity = math.log1p(max(delta_channel_count - 1, 0)) / delta_hours
    engagement = (views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR) / channel_avg
    cross = unique_channels_count / watched_channels_count
    return (
        velocity * VELOCITY_WEIGHT + engagement * ENGAGEMENT_WEIGHT + cross * CROSS_CHANNEL_WEIGHT
    )


def test_compute_viral_score_matches_hand_computed_value() -> None:
    # Known inputs → a precomputed expected number (overview §4 formula).
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
    # velocity = log1p(47-1)/0.5 = 3.8501476017100584/0.5 = 7.700295203420117
    #   (T15: log1p(Δch - 1) so one channel = no cross-channel spread → velocity 0)
    # engagement = (1000 + 50*3 + 200*2)/500 = 1550/500 = 3.1
    # cross_channel = 8/10 = 0.8
    # viral = 7.700295203420117*0.4 + 3.1*0.35 + 0.8*0.25
    #       = 3.080118081368047 + 1.0850000000000002 + 0.2 = 4.365118081368047
    expected = 4.365118081368047
    assert compute_viral_score(inputs) == pytest.approx(expected)
    assert compute_viral_score(inputs) == pytest.approx(
        _expected(
            views=1000,
            forwards=50,
            reactions=200,
            channel_avg=500.0,
            delta_channel_count=47,
            delta_hours=0.5,
            unique_channels_count=8,
            watched_channels_count=10,
        )
    )


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


def test_velocity_uses_log1p_of_extra_channels_over_hours() -> None:
    # T15: velocity counts CROSS-CHANNEL spread = log1p(Δch - 1), so a story across
    # N channels contributes log1p(N-1), not log1p(N).
    assert _velocity(delta_channel_count=47, delta_hours=0.5) == pytest.approx(math.log1p(46) / 0.5)


def test_velocity_guards_zero_delta_hours() -> None:
    # Δhours → 0 must not raise; it clamps to MIN_WINDOW_HOURS (no ZeroDivision).
    # Use ≥2 channels so there IS spread to measure (1 channel is 0 regardless of speed).
    value = _velocity(delta_channel_count=10, delta_hours=0.0)
    assert value > 0
    assert math.isfinite(value)


def test_velocity_single_channel_is_zero() -> None:
    # T15 (product principle): a story on ONE channel has NO cross-channel spread →
    # velocity 0, no matter how fast or how small the window. This is the fix that
    # stops isolated single posts from scoring as "viral".
    assert _velocity(delta_channel_count=1, delta_hours=2.0) == pytest.approx(0.0)
    assert _velocity(delta_channel_count=1, delta_hours=0.0) == pytest.approx(0.0)


def test_velocity_zero_channels_is_zero() -> None:
    # Degenerate Δch=0 (no observed channels) → max(0-1,0)=0 → log1p(0)=0 → velocity 0.
    assert _velocity(delta_channel_count=0, delta_hours=1.0) == pytest.approx(0.0)


def test_velocity_two_channels_is_positive() -> None:
    # T15: two channels = real cross-channel spread → strictly positive velocity.
    assert _velocity(delta_channel_count=2, delta_hours=2.0) > 0


def test_velocity_monotonic_in_channels() -> None:
    # T15: more channels spreading (same window) → strictly higher velocity.
    prev = _velocity(delta_channel_count=1, delta_hours=2.0)
    for n in range(2, 12):
        cur = _velocity(delta_channel_count=n, delta_hours=2.0)
        assert cur > prev
        prev = cur


def test_engagement_weights_forwards_and_reactions() -> None:
    assert _engagement(views=100, forwards=10, reactions=5, channel_avg=50.0) == pytest.approx(
        (100 + 10 * FORWARD_FACTOR + 5 * REACTION_FACTOR) / 50.0
    )


def test_engagement_guards_zero_channel_avg() -> None:
    # channel_avg == 0 (no historical base) must not raise.
    value = _engagement(views=100, forwards=0, reactions=0, channel_avg=0.0)
    assert math.isfinite(value)
    assert value >= 0


def test_cross_channel_ratio() -> None:
    assert _cross_channel(unique_channels_count=8, watched_channels_count=10) == pytest.approx(0.8)


def test_cross_channel_guards_zero_watched() -> None:
    # watched_channels_count == 0 → no division-by-zero; cluster scores 0 cross.
    assert _cross_channel(unique_channels_count=3, watched_channels_count=0) == pytest.approx(0.0)


def test_cross_channel_is_clamped_to_unit_interval() -> None:
    # Dirty data (unique > watched) clamps to 1.0 (invariant: cross_channel ∈ [0, 1]).
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
