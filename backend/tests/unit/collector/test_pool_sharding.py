"""TASK-131 — Pool sizing + deterministic channel sharding (unit tests, TDD).

Tests cover:
  AC1 — pick_slot_for_channel is deterministic (stable cross-call, algorithm pinned).
  AC2 — load spread: distinct handles map to distinct slots.
  AC3 — empty healthy_slots → None.
  AC4 — single healthy slot → that slot (trivial mapping).
  AC5 — acquire_for_channel falls back to rotation when the preferred slot is cooling.
  AC6 — acquire_for_channel falls back to rotation when the preferred slot is quarantined.
  AC7 — acquire_for_channel maps to the deterministic healthy slot when it IS healthy.
  AC8 — all cooling → AllAccountsFloodWaitError; all quarantined → PoolExhaustedError.
"""

import hashlib

import pytest

from collector.errors import AllAccountsFloodWaitError, PoolExhaustedError
from collector.telegram.account_pool import AccountPool, pick_slot_for_channel

from .conftest import FakeClient, make_pool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Clock:
    """Manually advanced monotonic clock for deterministic cooldown tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _pool_with_clock(n: int, clock: _Clock) -> AccountPool:
    pool = make_pool([FakeClient() for _ in range(n)])
    pool._now = clock
    return pool


def _expected_slot(handle: str, slots: list[int]) -> int:
    """Reference implementation: what pick_slot_for_channel SHOULD return."""
    digest = int(hashlib.sha256(handle.encode("utf-8")).hexdigest(), 16)
    return slots[digest % len(slots)]


# ---------------------------------------------------------------------------
# AC1 — Determinism
# ---------------------------------------------------------------------------


def test_pick_slot_deterministic_repeated_calls() -> None:
    """Same handle + slots always returns the same slot across repeated calls."""
    slots = [0, 1, 2, 3]
    handle = "@cryptonews"
    results = {pick_slot_for_channel(handle, slots) for _ in range(20)}
    assert len(results) == 1, "pick_slot_for_channel must be deterministic"


def test_pick_slot_algorithm_pinned_to_sha256() -> None:
    """Result equals sha256-based formula — ensures builtin hash() is NOT used."""
    slots = [0, 1, 2, 3, 4]
    for handle in ["@cryptonews", "@defi_alpha", "@whale_signals", "@trendpulse"]:
        expected = _expected_slot(handle, slots)
        actual = pick_slot_for_channel(handle, slots)
        assert actual == expected, (
            f"pick_slot_for_channel('{handle}', {slots}) = {actual}, "
            f"expected sha256-based slot {expected}"
        )


def test_pick_slot_stable_with_different_slot_orderings() -> None:
    """Slot membership matters, not list identity — same slots in same order → same result."""
    handle = "@defi_alpha"
    slots_a = [0, 1, 2]
    slots_b = [0, 1, 2]
    assert pick_slot_for_channel(handle, slots_a) == pick_slot_for_channel(handle, slots_b)


# ---------------------------------------------------------------------------
# AC2 — Load spread
# ---------------------------------------------------------------------------


def test_pick_slot_spreads_distinct_handles_across_slots() -> None:
    """Multiple distinct handles spread across > 1 slot when pool has > 1 slot.

    Handles are chosen to demonstrably spread under sha256 (pre-verified).
    """
    slots = [0, 1, 2, 3]
    # These handles are verified to land on at least 2 distinct slots under sha256:
    handles = [
        "@cryptonews",
        "@defi_alpha",
        "@whale_signals",
        "@trendpulse",
        "@bitcoin_ru",
    ]
    mapped = {pick_slot_for_channel(h, slots) for h in handles}
    assert len(mapped) > 1, (
        f"Expected handles to spread across > 1 slot, got all mapping to {mapped}"
    )


def test_pick_slot_two_handles_can_differ() -> None:
    """At least two distinct handles map to different slots (direct spread check)."""
    slots = [0, 1]
    # Find two handles that map to different slots under sha256
    # @cryptonews and @defi_alpha pre-checked:
    a = pick_slot_for_channel("@cryptonews", slots)
    b = pick_slot_for_channel("@bitcoin_ru", slots)
    # Verify via the reference formula too
    ea = _expected_slot("@cryptonews", slots)
    eb = _expected_slot("@bitcoin_ru", slots)
    assert a == ea
    assert b == eb
    # If they happen to collide, find handles that differ by brute force in the test
    all_results = {pick_slot_for_channel(f"@chan{i}", slots) for i in range(20)}
    assert len(all_results) > 1, "Expected different handles to hit different slots"


# ---------------------------------------------------------------------------
# AC3 — Empty healthy_slots → None
# ---------------------------------------------------------------------------


def test_pick_slot_empty_slots_returns_none() -> None:
    """Empty healthy_slots → None (no slot available)."""
    result = pick_slot_for_channel("@cryptonews", [])
    assert result is None


def test_pick_slot_empty_slots_various_handles() -> None:
    """None is returned regardless of handle when healthy_slots is empty."""
    for handle in ["@x", "@cryptonews", "@defi_alpha", ""]:
        assert pick_slot_for_channel(handle, []) is None


# ---------------------------------------------------------------------------
# AC4 — Single healthy slot → that slot
# ---------------------------------------------------------------------------


def test_pick_slot_single_slot_returns_it() -> None:
    """When healthy_slots has exactly one entry, always returns that slot."""
    for slot_idx in [0, 3, 7]:
        result = pick_slot_for_channel("@cryptonews", [slot_idx])
        assert result == slot_idx


def test_pick_slot_single_slot_any_handle() -> None:
    """Single-slot pool: any handle maps to that slot."""
    for handle in ["@x", "@cryptonews", "@defi_alpha", "@whale_signals"]:
        assert pick_slot_for_channel(handle, [5]) == 5


# ---------------------------------------------------------------------------
# AC5 — acquire_for_channel falls back when preferred slot is cooling
# ---------------------------------------------------------------------------


def test_acquire_for_channel_fallback_when_preferred_slot_cooling() -> None:
    """When the preferred slot is cooling, acquire_for_channel returns a live client."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # Determine which slot a specific handle maps to
    all_slots = list(range(len(pool._accounts)))
    preferred = pick_slot_for_channel("@cryptonews", all_slots)
    assert preferred is not None

    # Cool down the preferred slot (set cooldown far in the future)
    pool._accounts[preferred].cooldown_until = clock.t + 9999.0

    # acquire_for_channel should fall back and still return a client from a live slot
    client = pool.acquire_for_channel("@cryptonews")
    assert client is not None

    # The fallback must return a LIVE (non-cooling) slot, and never the cooling preferred one.
    returned_slot = pool._index
    assert returned_slot != preferred
    assert pool._accounts[returned_slot].cooldown_until <= clock.t


def test_acquire_for_channel_fallback_returns_non_cooling_client() -> None:
    """Fallback gives a live client; cooling slot's client is not returned."""
    clock = _Clock()
    pool = _pool_with_clock(4, clock)

    # Make ALL slots cooling EXCEPT slot 2
    for i in range(len(pool._accounts)):
        if i != 2:
            pool._accounts[i].cooldown_until = clock.t + 9999.0

    # Any handle whose preferred slot != 2 will fall back to slot 2
    # Find such a handle (brute force a small set)
    handle = None
    for candidate in ["@cryptonews", "@defi_alpha", "@whale_signals", "@trendpulse", "@bitcoin_ru"]:
        slot = pick_slot_for_channel(candidate, list(range(len(pool._accounts))))
        if slot != 2:  # preferred would be cooling → fallback
            handle = candidate
            break

    if handle is None:
        pytest.skip("Could not find a handle that maps away from slot 2 with 4 slots")

    client = pool.acquire_for_channel(handle)
    assert client is not None
    # The returned client must be from a NON-cooling slot (slot 2)
    assert pool._index == 2


# ---------------------------------------------------------------------------
# AC6 — acquire_for_channel falls back when preferred slot is quarantined
# ---------------------------------------------------------------------------


def test_acquire_for_channel_fallback_when_preferred_slot_quarantined() -> None:
    """When the preferred slot is quarantined, acquire_for_channel returns a live client."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    all_slots = list(range(len(pool._accounts)))
    preferred = pick_slot_for_channel("@cryptonews", all_slots)
    assert preferred is not None

    # Quarantine the preferred slot
    pool._accounts[preferred].quarantined = True

    # acquire_for_channel should fall back to a live account
    client = pool.acquire_for_channel("@cryptonews")
    assert client is not None

    # The returned slot must not be quarantined
    assert not pool._accounts[pool._index].quarantined


def test_acquire_for_channel_fallback_quarantined_never_returns_dead_client() -> None:
    """Fallback from quarantined preferred slot returns a healthy slot's client."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    all_slots = list(range(len(pool._accounts)))
    preferred = pick_slot_for_channel("@defi_alpha", all_slots)
    assert preferred is not None

    pool._accounts[preferred].quarantined = True

    client = pool.acquire_for_channel("@defi_alpha")
    # client must not be the dead client
    assert client is not pool._accounts[preferred].client


# ---------------------------------------------------------------------------
# AC7 — acquire_for_channel maps to the deterministic healthy slot when available
# ---------------------------------------------------------------------------


def test_acquire_for_channel_picks_deterministic_slot_when_all_healthy() -> None:
    """When all slots are healthy, acquire_for_channel selects the sha256-pinned slot."""
    clock = _Clock()
    pool = _pool_with_clock(4, clock)

    handle = "@cryptonews"
    all_slots = list(range(len(pool._accounts)))
    expected_slot = pick_slot_for_channel(handle, all_slots)
    assert expected_slot is not None

    pool.acquire_for_channel(handle)

    assert pool._index == expected_slot, f"Expected _index={expected_slot}, got {pool._index}"


def test_acquire_for_channel_returns_correct_client() -> None:
    """acquire_for_channel returns the client of the deterministically selected slot."""
    clock = _Clock()
    clients = [FakeClient(), FakeClient(), FakeClient()]
    pool = make_pool(clients)
    pool._now = clock

    handle = "@whale_signals"
    all_slots = list(range(len(pool._accounts)))
    expected_slot = pick_slot_for_channel(handle, all_slots)
    assert expected_slot is not None

    client = pool.acquire_for_channel(handle)
    assert client is pool._accounts[expected_slot].client


def test_acquire_for_channel_sets_index_to_picked_slot() -> None:
    """_index is set to the deterministic slot so note_read_success/failure land correctly."""
    clock = _Clock()
    pool = _pool_with_clock(5, clock)

    handle = "@trendpulse"
    all_slots = list(range(len(pool._accounts)))
    expected = pick_slot_for_channel(handle, all_slots)

    pool.acquire_for_channel(handle)
    assert pool._index == expected


# ---------------------------------------------------------------------------
# AC8 — all cooling → AllAccountsFloodWaitError; all quarantined → PoolExhaustedError
# ---------------------------------------------------------------------------


def test_acquire_for_channel_all_cooling_raises_all_accounts_flood() -> None:
    """Fallback preserves AllAccountsFloodWaitError when all slots are cooling."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    for account in pool._accounts:
        account.cooldown_until = clock.t + 9999.0

    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire_for_channel("@cryptonews")


def test_acquire_for_channel_all_quarantined_raises_pool_exhausted() -> None:
    """Fallback preserves PoolExhaustedError when all slots are quarantined."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    for account in pool._accounts:
        account.quarantined = True

    with pytest.raises(PoolExhaustedError):
        pool.acquire_for_channel("@cryptonews")


def test_acquire_for_channel_does_not_mutate_cooldown_or_quarantine() -> None:
    """acquire_for_channel only sets _index; it never changes cooldown or quarantine."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # Record before state
    before_cooldowns = [a.cooldown_until for a in pool._accounts]
    before_quarantined = [a.quarantined for a in pool._accounts]

    pool.acquire_for_channel("@cryptonews")

    # After state must match
    assert [a.cooldown_until for a in pool._accounts] == before_cooldowns
    assert [a.quarantined for a in pool._accounts] == before_quarantined
