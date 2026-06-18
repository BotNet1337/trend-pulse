"""Channel-independence graph — discount colluding channel rings so cross-channel
reach counts INDEPENDENT sources, not a shill network reposting itself.

A story across 10 channels owned by one operator (or one channel forwarded by 9
others) is NOT 10 independent corroborations — it's ~1. This is the product moat
(strategy: channel-independence / anti-shill). This pure module turns observed
channel relationships into a per-channel independence weight in (0, 1]:

  • COLLUSION: two channels that co-post near-identical content on a high FRACTION of
    their events (and on at least a few events, not one coincidence) are treated as
    one source. Channels are unioned into rings; each member's weight = 1 / |ring|.
  • FORWARD-CHAIN: a forward edge A→B means A is not an independent source for B's
    content, so A and B are unioned into the same ring.

`effective_independent_reach(cluster_channels, weights)` sums the weights of a
cluster's channels → the independent-channel count the headline score (T3) should use
instead of a raw distinct-channel count. Pure — no I/O, no DB (ADR-001). All
thresholds are NAMED constants (CONVENTIONS).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# Two channels collude when they co-post near-identical content on at least this
# FRACTION of the rarer channel's events — high overlap means a shared source/operator.
COLLUSION_FRACTION = 0.6
# ...and on at least this many shared events, so a single coincidental co-post (one
# wire story both happened to carry) never collapses two independent editors.
COLLUSION_MIN_SHARED_EVENTS = 3


@dataclass(frozen=True)
class ChannelRelations:
    """Observed channel relationships, aggregated upstream (pure input).

    - `event_count[c]`            : number of events (clusters) channel c posted in.
    - `cooccurrence[(a, b)]`      : events where BOTH a and b posted near-identical
                                    content (a < b; symmetric, stored once).
    - `forward_edges`            : (src, dst) — src republished/forwarded dst.
    """

    event_count: Mapping[int, int]
    cooccurrence: Mapping[tuple[int, int], int]
    forward_edges: Iterable[tuple[int, int]]


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # path compression
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        self._parent[self.find(a)] = self.find(b)


def _colludes(events_a: int, events_b: int, shared: int) -> bool:
    """True iff a and b overlap enough to be one source (named-constant gated)."""
    if shared < COLLUSION_MIN_SHARED_EVENTS:
        return False
    rarer = min(events_a, events_b)
    return rarer > 0 and shared / rarer >= COLLUSION_FRACTION


def independence_weights(relations: ChannelRelations) -> dict[int, float]:
    """Per-channel independence weight in (0, 1]: 1/|ring| for ring members, 1.0 alone.

    Builds rings by unioning collusion pairs (high co-occurrence fraction) and forward
    edges, then assigns each channel 1 / size-of-its-ring so a whole ring contributes
    ~1 independent unit.
    """
    uf = _UnionFind()
    channels = set(relations.event_count)
    for c in channels:
        uf.find(c)  # register every known channel

    for (a, b), shared in relations.cooccurrence.items():
        if _colludes(relations.event_count.get(a, 0), relations.event_count.get(b, 0), shared):
            uf.union(a, b)
    for src, dst in relations.forward_edges:
        uf.union(src, dst)
        channels.update((src, dst))

    ring_size: dict[int, int] = {}
    for c in channels:
        root = uf.find(c)
        ring_size[root] = ring_size.get(root, 0) + 1
    return {c: 1.0 / ring_size[uf.find(c)] for c in channels}


def effective_independent_reach(
    cluster_channels: Iterable[int], weights: Mapping[int, float]
) -> float:
    """Independent-channel count for a cluster = sum of its channels' weights.

    A channel not present in `weights` (never seen colluding) counts as fully
    independent (1.0). A 10-channel shill ring (each weight 0.1) sums to ~1.0.
    """
    return sum(weights.get(c, 1.0) for c in set(cluster_channels))
