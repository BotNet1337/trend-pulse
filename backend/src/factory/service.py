"""Pure decision helpers for the account-factory loop (TASK-134, Layer B1+B4+B5).

These functions are the factory's decision *brain*, kept PURE so the orchestration
in `factory.tasks.factory_tick` is trivially testable branch-by-branch: no I/O, no
`Settings`, no logging, immutable inputs. The orchestrator wires them to the real
store / provider / Redis.

Money is `Decimal` everywhere (never float) so the budget hard-cap is exact.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal


def needs_topup(healthy: int, target: int) -> bool:
    """True iff the live pool is BELOW its operational target (so the factory buys).

    `healthy` is the current healthy-account count (from the pool-health snapshot);
    `target` is `pool_min_healthy`. Equal or above target → no top-up needed.
    """
    return healthy < target


def can_afford(spent: Decimal, price: Decimal, budget: Decimal) -> bool:
    """True iff buying one more number stays within the hard USD budget ceiling.

    BOUNDARY: `spent + price == budget` IS affordable (the cap uses `<=`); strictly
    over the budget is NOT. A 0 budget with any positive price refuses every buy.
    """
    return spent + price <= budget


def is_promotable(probation_until: datetime | None, now: datetime) -> bool:
    """True iff a probation row's gate has opened (`now >= probation_until`).

    A `None` `probation_until` (the row never entered probation) is never promotable.
    BOUNDARY: `now == probation_until` opens the gate. The probation gate is NEVER
    bypassed — the caller also requires a health check to pass before promoting.
    """
    return probation_until is not None and now >= probation_until


def assign_proxy(pool: tuple[str, ...], used: frozenset[str]) -> str | None:
    """Return the first proxy in `pool` not already in `used`, else `None`.

    Pure: both inputs are immutable and are never mutated. `None` means the pool is
    empty OR exhausted — the caller skips the buy this tick (a registration must not
    reuse a proxy already bound to a live/in-flight factory account). Order is stable
    (the configured pool order) so assignment is deterministic.
    """
    for proxy in pool:
        if proxy not in used:
            return proxy
    return None
