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
    """Billing period for an invoice. Crypto has no native subscriptions — every
    period is a single prepaid invoice; durations live in `PERIOD_DAYS`.

    TASK-047: `QUARTER` (-10%) and `YEAR` (-20%) extend the grid; prices are
    explicit constants in `PLAN_PERIOD_PRICES_USD`, never runtime discount math.
    """

    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


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


# Period lengths in days — named constants, time as explicit durations (CONVENTIONS).
# TASK-047: fixed durations, no calendar/leap-year magic (month is already a fixed 30).
_MONTH_DAYS = 30
_QUARTER_DAYS = 90
_YEAR_DAYS = 365
PERIOD_DAYS: dict[BillingPeriod, int] = {
    BillingPeriod.MONTH: _MONTH_DAYS,
    BillingPeriod.QUARTER: _QUARTER_DAYS,
    BillingPeriod.YEAR: _YEAR_DAYS,
}

# --- Per-plan limits (overview §6). `None` = unlimited for countable resources. ---
# Countable caps.
# Free = воронка: паки + задержка (TASK-049). Собственные каналы — только Pro/Trader.
_FREE_CHANNELS = 0
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

# --- Prices (overview §6). Invoice amounts per paid plan and period, in USD. ---
# TASK-049: new monthly grid — Pro $29, Trader/Team $99 (start at lower bound; raise after PMF).
# TASK-047: quarter ≈ -10% and year ≈ -20% off the monthly run-rate, rounded DOWN
# to a whole dollar in the user's favor (87→78, 297→267, 348→278, 1188→950).
# Explicit constants — no runtime discount arithmetic, nothing to drift.
_PRO_PRICE_USD = Decimal("29")
_TEAM_PRICE_USD = Decimal("99")
_PRO_QUARTER_PRICE_USD = Decimal("78")
_TEAM_QUARTER_PRICE_USD = Decimal("267")
_PRO_YEAR_PRICE_USD = Decimal("278")
_TEAM_YEAR_PRICE_USD = Decimal("950")
PRICE_CURRENCY = "usd"

# Monthly anchor prices. Kept as the MRR normalization base (analytics/money.py)
# and the per-month display anchor — NOT the invoice amount source (see below).
PLAN_PRICES_USD: dict[Plan, Decimal] = {
    Plan.PRO: _PRO_PRICE_USD,
    Plan.TEAM: _TEAM_PRICE_USD,
}

# The invoice price grid (TASK-047) — the single source for `price_for`.
PLAN_PERIOD_PRICES_USD: dict[Plan, dict[BillingPeriod, Decimal]] = {
    Plan.PRO: {
        BillingPeriod.MONTH: _PRO_PRICE_USD,
        BillingPeriod.QUARTER: _PRO_QUARTER_PRICE_USD,
        BillingPeriod.YEAR: _PRO_YEAR_PRICE_USD,
    },
    Plan.TEAM: {
        BillingPeriod.MONTH: _TEAM_PRICE_USD,
        BillingPeriod.QUARTER: _TEAM_QUARTER_PRICE_USD,
        BillingPeriod.YEAR: _TEAM_YEAR_PRICE_USD,
    },
}

# Resources that are boolean feature gates (403 when off) vs countable caps (402).
FEATURE_RESOURCES: frozenset[Resource] = frozenset({Resource.API_ACCESS, Resource.WEBHOOK_DELIVERY})


def price_for(plan: Plan, period: BillingPeriod) -> Decimal:
    """Return the USD invoice amount for a paid plan and period (TASK-047).

    Quarter ≈ -10% and year ≈ -20% vs the monthly run-rate; amounts are explicit
    constants in `PLAN_PERIOD_PRICES_USD`. Raises `ValueError` for the free plan
    and for any plan/period pair missing from the grid.
    """
    try:
        return PLAN_PERIOD_PRICES_USD[plan][period]
    except KeyError as exc:
        raise ValueError(f"no price for plan {plan!r} with period {period!r}") from exc
