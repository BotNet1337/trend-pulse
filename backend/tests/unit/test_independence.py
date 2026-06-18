"""Unit tests for the channel-independence graph (T2 — anti-shill moat).

A colluding ring must count as ~1 independent source; genuinely independent editors
must each count as 1. DB-free pure compute.
"""

import pytest

from scorer.independence import (
    COLLUSION_MIN_SHARED_EVENTS,
    ChannelRelations,
    effective_independent_reach,
    independence_weights,
)


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


@pytest.mark.unit
def test_independent_editors_keep_full_weight() -> None:
    # Three channels, each active, barely ever co-posting → all independent.
    rel = ChannelRelations(
        event_count={1: 50, 2: 50, 3: 50},
        cooccurrence={_pair(1, 2): 1, _pair(1, 3): 1, _pair(2, 3): 1},
        forward_edges=[],
    )
    w = independence_weights(rel)
    assert w == {1: 1.0, 2: 1.0, 3: 1.0}
    assert effective_independent_reach([1, 2, 3], w) == pytest.approx(3.0)


@pytest.mark.unit
def test_collusion_ring_counts_as_one_source() -> None:
    # Channels 1,2,3 co-post near-identically on almost every event → one ring.
    rel = ChannelRelations(
        event_count={1: 10, 2: 10, 3: 10},
        cooccurrence={_pair(1, 2): 9, _pair(1, 3): 9, _pair(2, 3): 9},
        forward_edges=[],
    )
    w = independence_weights(rel)
    assert w[1] == pytest.approx(1 / 3)
    assert w[2] == pytest.approx(1 / 3)
    assert w[3] == pytest.approx(1 / 3)
    # The whole ring appearing in a cluster ≈ a single independent source.
    assert effective_independent_reach([1, 2, 3], w) == pytest.approx(1.0)


@pytest.mark.unit
def test_ring_plus_independents() -> None:
    # A 3-channel ring (1,2,3) + two independents (4,5). Cluster of all five →
    # 1 (ring) + 1 + 1 = 3 effective independent sources, not 5.
    rel = ChannelRelations(
        event_count={1: 10, 2: 10, 3: 10, 4: 40, 5: 40},
        cooccurrence={_pair(1, 2): 9, _pair(1, 3): 9, _pair(2, 3): 9, _pair(4, 5): 1},
        forward_edges=[],
    )
    w = independence_weights(rel)
    assert effective_independent_reach([1, 2, 3, 4, 5], w) == pytest.approx(3.0)
    assert w[4] == pytest.approx(1.0)
    assert w[5] == pytest.approx(1.0)


@pytest.mark.unit
def test_forward_chain_collapses_source() -> None:
    # A forwards B → not an independent source for B's content; same ring.
    rel = ChannelRelations(
        event_count={1: 30, 2: 30},
        cooccurrence={},
        forward_edges=[(1, 2)],
    )
    w = independence_weights(rel)
    assert w[1] == pytest.approx(0.5)
    assert w[2] == pytest.approx(0.5)
    assert effective_independent_reach([1, 2], w) == pytest.approx(1.0)


@pytest.mark.unit
def test_one_coincidental_copost_is_not_collusion() -> None:
    # High fraction but only ONE shared event (below the min) → still independent.
    assert COLLUSION_MIN_SHARED_EVENTS >= 2
    rel = ChannelRelations(
        event_count={1: 1, 2: 1},
        cooccurrence={_pair(1, 2): 1},
        forward_edges=[],
    )
    w = independence_weights(rel)
    assert w == {1: 1.0, 2: 1.0}


@pytest.mark.unit
def test_unknown_channel_counts_as_independent() -> None:
    # A channel never observed (not in weights) defaults to full independence.
    assert effective_independent_reach([7, 8], {}) == pytest.approx(2.0)
