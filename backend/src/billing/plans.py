"""Plan tiers, per-plan limits, and prices — the single source of truth.

Limits come straight from overview §6 (the tariff table); they live here as named
constants in `PLAN_LIMITS`, never as magic literals at the call sites (CONVENTIONS,
ADR-003 "plan-gating in one place"). `None` means "unlimited" for a countable
resource, and for boolean features (`api_access`, `webhook_delivery`) the value is
a plain `bool`.

Prices (Pro/Team, monthly) are the invoice amounts for `POST /billing/invoice`.
"""

from decimal import Decimal
from enum import StrEnum


class Plan(StrEnum):
    """Subscription tiers (overview §6). String values match `users.plan`."""

    FREE = "free"
    PRO = "pro"
    TEAM = "team"


class BillingPeriod(StrEnum):
    """Billing period for an invoice. Crypto has no native subscriptions, so the
    only supported period is a calendar month; the duration lives in `PERIOD_DAYS`.
    """

    MONTH = "month"


class Resource(StrEnum):
    """Gated resources/features enforced via `assert_within_limit`."""

    CHANNELS = "channels"
    TOPICS = "topics"
    ALERTS_PER_DAY = "alerts_per_day"
    HISTORY = "history"
    API_ACCESS = "api_access"
    WEBHOOK_DELIVERY = "webhook_delivery"
    # Curated channel packs (TASK-038). Counted as distinct pack_slug values subscribed.
    # Free=1, Pro/Team=5 — intentional product decision: packs are Free-funnel value (E1/E5).
    PACKS = "packs"


# Period length in days — named constant, time as an explicit duration (CONVENTIONS).
_MONTH_DAYS = 30
PERIOD_DAYS: dict[BillingPeriod, int] = {
    BillingPeriod.MONTH: _MONTH_DAYS,
}

# --- Per-plan limits (overview §6). `None` = unlimited for countable resources. ---
# Countable caps.
_FREE_CHANNELS = 5
_PRO_CHANNELS = 100
_TEAM_CHANNELS = 500
_FREE_TOPICS = 1
_PRO_TOPICS = 5
_TEAM_TOPICS: int | None = None  # unlimited
_FREE_ALERTS_PER_DAY = 5
_PRO_ALERTS_PER_DAY: int | None = None  # unlimited
_TEAM_ALERTS_PER_DAY: int | None = None  # unlimited
# History retention (days). Free has none (—), Pro 30, Team 90.
_FREE_HISTORY_DAYS = 0
_PRO_HISTORY_DAYS = 30
_TEAM_HISTORY_DAYS = 90

# Boolean feature gates (overview §6: webhook no/yes/yes, API no/no/yes).
_FREE_WEBHOOK = False
_PRO_WEBHOOK = True
_TEAM_WEBHOOK = True
_FREE_API = False
_PRO_API = False
_TEAM_API = True

# Curated channel packs (TASK-038). Named caps — Free=1, Pro=5, Team=5.
# Intentional product rule: packs are the Free-funnel value (E1/E5); Free users
# get 1 pack; paid plans expand to 5. Counted as distinct active pack subscriptions.
_FREE_PACKS = 1
_PRO_PACKS = 5
_TEAM_PACKS = 5

# The limit value type: an int cap, `None` (unlimited), or a bool feature gate.
PlanLimit = int | None | bool

PLAN_LIMITS: dict[Plan, dict[Resource, PlanLimit]] = {
    Plan.FREE: {
        Resource.CHANNELS: _FREE_CHANNELS,
        Resource.TOPICS: _FREE_TOPICS,
        Resource.ALERTS_PER_DAY: _FREE_ALERTS_PER_DAY,
        Resource.HISTORY: _FREE_HISTORY_DAYS,
        Resource.API_ACCESS: _FREE_API,
        Resource.WEBHOOK_DELIVERY: _FREE_WEBHOOK,
        Resource.PACKS: _FREE_PACKS,
    },
    Plan.PRO: {
        Resource.CHANNELS: _PRO_CHANNELS,
        Resource.TOPICS: _PRO_TOPICS,
        Resource.ALERTS_PER_DAY: _PRO_ALERTS_PER_DAY,
        Resource.HISTORY: _PRO_HISTORY_DAYS,
        Resource.API_ACCESS: _PRO_API,
        Resource.WEBHOOK_DELIVERY: _PRO_WEBHOOK,
        Resource.PACKS: _PRO_PACKS,
    },
    Plan.TEAM: {
        Resource.CHANNELS: _TEAM_CHANNELS,
        Resource.TOPICS: _TEAM_TOPICS,
        Resource.ALERTS_PER_DAY: _TEAM_ALERTS_PER_DAY,
        Resource.HISTORY: _TEAM_HISTORY_DAYS,
        Resource.API_ACCESS: _TEAM_API,
        Resource.WEBHOOK_DELIVERY: _TEAM_WEBHOOK,
        Resource.PACKS: _TEAM_PACKS,
    },
}

# --- Prices (overview §6). Monthly amount per paid plan, in USD. ---
_PRO_PRICE_USD = Decimal("19")
_TEAM_PRICE_USD = Decimal("79")
PRICE_CURRENCY = "usd"

PLAN_PRICES_USD: dict[Plan, Decimal] = {
    Plan.PRO: _PRO_PRICE_USD,
    Plan.TEAM: _TEAM_PRICE_USD,
}

# Resources that are boolean feature gates (403 when off) vs countable caps (402).
FEATURE_RESOURCES: frozenset[Resource] = frozenset({Resource.API_ACCESS, Resource.WEBHOOK_DELIVERY})


def price_for(plan: Plan) -> Decimal:
    """Return the monthly USD price for a paid plan. Raises for non-payable plans."""
    try:
        return PLAN_PRICES_USD[plan]
    except KeyError as exc:
        raise ValueError(f"plan {plan!r} is not payable (no price)") from exc
