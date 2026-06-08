"""Plan-limit seam for watchlists — now bridged to the single billing enforcement.

Task-004 shipped a standalone count check (a fixed Free cap of 5). Task-010 makes
the real per-plan cap apply by delegating to `billing.assert_within_limit`
(ADR-003: plan-gating in ONE place). The watchlist router keeps its 402 mapping;
`billing.PlanLimitExceeded(code=402)` for an over-quota channel cap is translated to
`LimitExceededError` here so the router's existing handler is unchanged.

Channels cap per plan (overview §6): Free 5 → the 6th create is 402; Pro 100;
Team 500. One watchlist row = one channel (the task-004 single-channel decision).
"""

from sqlalchemy.orm import Session

from api.watchlist.exceptions import LimitExceededError
from billing import PlanLimitExceeded, Resource, assert_within_limit
from storage.models.users import User


def check_watchlist_limits(session: Session, user: User) -> None:
    """Raise `LimitExceededError` if creating one more channel breaches the plan.

    Delegates to the single billing enforcement entry (ADR-003); the billing
    quota error (402) is re-raised as the watchlist domain error the router maps.
    """
    try:
        assert_within_limit(session, user, Resource.CHANNELS)
    except PlanLimitExceeded as exc:
        raise LimitExceededError(str(exc)) from exc
