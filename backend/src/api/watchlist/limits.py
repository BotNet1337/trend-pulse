"""Plan-limit seam for watchlists (full per-plan enforcement is task-010).

User decision (overrides the task doc's "5 channels"): the plan limit is the max
number of WATCHLISTS a user may own under the default (Free) plan. Creating one
beyond the cap raises `LimitExceededError`, which the router maps to 402.

This is a basic count check against a single default cap; per-plan counters and
atomic enforcement (race on concurrent POSTs at the boundary) are task-010.
"""

from api.watchlist.exceptions import LimitExceededError

# Free-plan cap: max watchlists per user (overview §6, reinterpreted per the
# one-row-per-watchlist decision). Named constant, not a magic literal.
DEFAULT_PLAN_MAX_WATCHLISTS = 5


def check_watchlist_limits(*, current_count: int, adding: int = 1) -> None:
    """Raise `LimitExceededError` if `current_count + adding` exceeds the plan cap."""
    if current_count + adding > DEFAULT_PLAN_MAX_WATCHLISTS:
        raise LimitExceededError(
            f"watchlist limit reached: the default plan allows "
            f"{DEFAULT_PLAN_MAX_WATCHLISTS} watchlists"
        )
