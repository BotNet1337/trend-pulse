"""Single plan-limit enforcement entry (ADR-003 "plan-gating in one place").

`assert_within_limit(session, user, resource)` is the ONLY place plan thresholds
are checked. It resolves the user's EFFECTIVE plan (their stored `plan`, but Free
if the subscription `expires_at` is in the past — expiry rollback, AC8), looks up
`PLAN_LIMITS[plan][resource]`, and:

- countable resources (channels/topics): compute current usage via storage repos
  and raise `PlanLimitExceeded(402)` when at/over the cap;
- boolean features (api_access/webhook_delivery): raise `PlanLimitExceeded(403)`
  when the feature is off on the plan.

`None` (unlimited) always passes the quantitative check.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billing.plans import FEATURE_RESOURCES, PLAN_LIMITS, Plan, Resource
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import User
from storage.models.watchlists import Watchlist

# HTTP code hints the API boundary maps to: 402 = over quota (upgrade needed),
# 403 = feature not available on the plan. Named constants, not magic literals.
_CODE_UPGRADE_REQUIRED = 402
_CODE_FORBIDDEN = 403


class PlanLimitExceeded(Exception):
    """The caller exceeds their plan's limit for a resource.

    Carries an HTTP `code` hint: 402 (over quota → upgrade) for countable caps,
    403 (feature not on plan) for boolean feature gates.
    """

    def __init__(self, message: str, *, code: int) -> None:
        super().__init__(message)
        self.code = code


def effective_plan(session: Session, user: User) -> Plan:
    """Resolve the user's effective plan, downgrading to Free if expired (AC8).

    The stored `user.plan` is authoritative, but an expired subscription
    (`expires_at` in the past) rolls back to Free so limits apply immediately.
    """
    try:
        stored = Plan(user.plan)
    except ValueError:
        return Plan.FREE
    if stored is Plan.FREE:
        return Plan.FREE

    sub = session.scalars(select(Subscription).where(Subscription.user_id == user.id)).one_or_none()
    if sub is None or sub.expires_at is None or sub.expires_at <= utcnow():
        return Plan.FREE
    return stored


def _channel_usage(session: Session, user_id: int) -> int:
    """Current channel count for the user — manual watchlists ONLY (pack rows excluded).

    Pack rows (pack_slug IS NOT NULL) do NOT count toward the CHANNELS cap (TASK-038,
    AC3): pack channels are a Free-funnel value and tracked via a separate PACKS limit.
    This preserves backward-compatibility: existing rows with pack_slug=NULL are
    unaffected; no behaviour change for users who have never subscribed to a pack.
    """
    stmt = (
        select(func.count())
        .select_from(Watchlist)
        .where(Watchlist.user_id == user_id)
        .where(Watchlist.pack_slug.is_(None))
    )
    return int(session.scalar(stmt) or 0)


def _topic_usage(session: Session, user_id: int) -> int:
    """Current distinct topic count across the user's watchlists."""
    stmt = (
        select(func.count(func.distinct(Watchlist.topic)))
        .select_from(Watchlist)
        .where(Watchlist.user_id == user_id)
    )
    return int(session.scalar(stmt) or 0)


def _packs_usage(session: Session, user_id: int) -> int:
    """Current count of distinct pack subscriptions for the user (TASK-038).

    Counts distinct non-NULL pack_slug values in the user's watchlists. Each unique
    pack_slug represents one subscribed pack. This is the usage counter for Resource.PACKS.
    """
    stmt = (
        select(func.count(func.distinct(Watchlist.pack_slug)))
        .select_from(Watchlist)
        .where(Watchlist.user_id == user_id)
        .where(Watchlist.pack_slug.is_not(None))
    )
    return int(session.scalar(stmt) or 0)


_USAGE_COUNTERS = {
    Resource.CHANNELS: _channel_usage,
    Resource.TOPICS: _topic_usage,
    Resource.PACKS: _packs_usage,
}


def assert_within_limit(session: Session, user: User, resource: Resource) -> None:
    """Raise `PlanLimitExceeded` if adding one `resource` would breach the plan.

    This is the single enforcement entry every gated surface calls before creating
    a resource (ADR-003).
    """
    plan = effective_plan(session, user)
    limit = PLAN_LIMITS[plan][resource]

    if resource in FEATURE_RESOURCES:
        if not bool(limit):
            raise PlanLimitExceeded(
                f"{resource.value} is not available on the {plan.value} plan",
                code=_CODE_FORBIDDEN,
            )
        return

    # Countable resource. `None` (or a non-int) means unlimited → always passes.
    if not isinstance(limit, int):
        return
    counter = _USAGE_COUNTERS.get(resource)
    if counter is None:  # pragma: no cover - no countable usage source yet
        return
    current = counter(session, user.id)
    if current + 1 > limit:
        raise PlanLimitExceeded(
            f"{resource.value} limit reached: the {plan.value} plan allows {limit}",
            code=_CODE_UPGRADE_REQUIRED,
        )
