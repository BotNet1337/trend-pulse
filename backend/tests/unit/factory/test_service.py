"""TASK-134 — pure factory decision helpers (no I/O, no settings).

Covers the four pure helpers the `factory_tick` orchestrator depends on:
  * `needs_topup`   — pool below the operational target.
  * `can_afford`    — budget hard-cap with the equal-is-affordable BOUNDARY.
  * `is_promotable` — the probation gate (`now >= probation_until`).
  * `assign_proxy`  — first unused proxy from the configured pool (immutable inputs).

Marker: unit (default — runs under `make ci-fast`, `-m 'not integration'`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from factory.service import assign_proxy, can_afford, is_promotable, needs_topup

_NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


# --- needs_topup ------------------------------------------------------------
def test_needs_topup_below_target() -> None:
    assert needs_topup(healthy=0, target=3) is True
    assert needs_topup(healthy=2, target=3) is True


def test_needs_topup_at_target() -> None:
    assert needs_topup(healthy=3, target=3) is False


def test_needs_topup_above_target() -> None:
    assert needs_topup(healthy=5, target=3) is False


# --- can_afford (budget hard-cap, BOUNDARY = equal is affordable) -----------
def test_can_afford_strictly_under_budget() -> None:
    assert can_afford(spent=Decimal("5"), price=Decimal("1"), budget=Decimal("10")) is True


def test_can_afford_exactly_at_budget_is_affordable() -> None:
    # BOUNDARY: spent + price == budget → affordable (hard-cap uses <=).
    assert can_afford(spent=Decimal("9"), price=Decimal("1"), budget=Decimal("10")) is True


def test_can_afford_over_budget_is_not_affordable() -> None:
    assert can_afford(spent=Decimal("9.5"), price=Decimal("1"), budget=Decimal("10")) is False


def test_can_afford_zero_budget_never_affords() -> None:
    # A 0 budget with any positive price → spent+price > 0 → refuse.
    assert can_afford(spent=Decimal("0"), price=Decimal("1"), budget=Decimal("0")) is False


# --- is_promotable (probation gate) -----------------------------------------
def test_is_promotable_none_until_is_false() -> None:
    assert is_promotable(None, _NOW) is False


def test_is_promotable_now_before_until_is_false() -> None:
    future = _NOW + timedelta(days=1)
    assert is_promotable(future, _NOW) is False


def test_is_promotable_now_equals_until_is_true() -> None:
    # BOUNDARY: now == probation_until → gate opens (>=).
    assert is_promotable(_NOW, _NOW) is True


def test_is_promotable_now_after_until_is_true() -> None:
    past = _NOW - timedelta(days=1)
    assert is_promotable(past, _NOW) is True


# --- assign_proxy (first unused; immutable inputs) --------------------------
def test_assign_proxy_returns_first_unused() -> None:
    pool = ("socks5://a", "socks5://b", "socks5://c")
    used = frozenset({"socks5://a"})
    assert assign_proxy(pool, used) == "socks5://b"


def test_assign_proxy_all_used_returns_none() -> None:
    pool = ("socks5://a", "socks5://b")
    used = frozenset({"socks5://a", "socks5://b"})
    assert assign_proxy(pool, used) is None


def test_assign_proxy_empty_pool_returns_none() -> None:
    assert assign_proxy((), frozenset()) is None


def test_assign_proxy_does_not_mutate_inputs() -> None:
    pool = ("socks5://a", "socks5://b")
    used = frozenset({"socks5://a"})
    assign_proxy(pool, used)
    assert pool == ("socks5://a", "socks5://b")
    assert used == frozenset({"socks5://a"})
