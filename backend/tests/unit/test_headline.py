"""Unit tests for the headline signal score (T3 — folds anti-shill into the score).

Proves the moat in numbers: more INDEPENDENT channels → higher score; a shill ring
scores like one channel; promo/coordinated clusters score 0. DB-free pure compute.
"""

import pytest

from scorer.headline import compute_headline_score
from scorer.noise_filter import SignalKind
from scorer.score import ScoreInputs


def _inputs(**over: object) -> ScoreInputs:
    base: dict[str, object] = {
        "views": 5000,
        "forwards": 100,
        "reactions": 200,
        "channel_avg": 1.0,
        "delta_channel_count": 6,
        "delta_hours": 2.0,
        "unique_channels_count": 6,
        "watched_channels_count": 30,
    }
    base.update(over)
    return ScoreInputs(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_monotonic_in_independent_channels() -> None:
    # Same engagement/time; more INDEPENDENT reach → strictly higher score.
    s1 = compute_headline_score(
        base=_inputs(), effective_independent_channels=1.0, signal_kind=SignalKind.ORGANIC
    )
    s3 = compute_headline_score(
        base=_inputs(), effective_independent_channels=3.0, signal_kind=SignalKind.ORGANIC
    )
    s6 = compute_headline_score(
        base=_inputs(), effective_independent_channels=6.0, signal_kind=SignalKind.ORGANIC
    )
    assert s1 < s3 < s6
    assert all(0.0 <= s <= 100.0 for s in (s1, s3, s6))


@pytest.mark.unit
def test_shill_ring_scores_like_one_channel() -> None:
    # A cluster that spans 10 RAW channels but is a colluding ring (effective
    # independent reach ≈ 1) must score the SAME as a genuine single channel — not
    # like 10 independent corroborations.
    ring = compute_headline_score(
        base=_inputs(unique_channels_count=10, delta_channel_count=10),
        effective_independent_channels=1.0,
        signal_kind=SignalKind.ORGANIC,
    )
    one = compute_headline_score(
        base=_inputs(unique_channels_count=1, delta_channel_count=1),
        effective_independent_channels=1.0,
        signal_kind=SignalKind.ORGANIC,
    )
    assert ring == pytest.approx(one)


@pytest.mark.unit
def test_independent_breadth_beats_shill_ring() -> None:
    # 10 INDEPENDENT channels must outscore a 10-channel shill ring on the same content.
    independent = compute_headline_score(
        base=_inputs(unique_channels_count=10, delta_channel_count=10),
        effective_independent_channels=10.0,
        signal_kind=SignalKind.ORGANIC,
    )
    ring = compute_headline_score(
        base=_inputs(unique_channels_count=10, delta_channel_count=10),
        effective_independent_channels=1.0,
        signal_kind=SignalKind.ORGANIC,
    )
    assert independent > ring


@pytest.mark.unit
@pytest.mark.parametrize("kind", [SignalKind.PROMO, SignalKind.COORDINATED])
def test_noise_clusters_score_zero(kind: SignalKind) -> None:
    s = compute_headline_score(base=_inputs(), effective_independent_channels=8.0, signal_kind=kind)
    assert s == 0.0


@pytest.mark.unit
def test_score_is_bounded_unit_scale() -> None:
    extreme = compute_headline_score(
        base=_inputs(views=10_000_000, forwards=1_000_000, reactions=1_000_000),
        effective_independent_channels=30.0,
        signal_kind=SignalKind.ORGANIC,
    )
    assert 0.0 <= extreme <= 100.0
