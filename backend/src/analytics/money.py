"""Business-metrics read functions (TASK-051).

Pure read-only functions that aggregate data from source-of-truth tables:
  - `subscriptions` (active = expires_at > now())
  - `billing_payments` (processed status only)
  - `business_metrics_daily` (pre-computed daily funnel from TASK-050)

Design invariants:
  - No writes: every function is SELECT-only (invariant from task doc).
  - No magic literals: all windows and constants are named.
  - Bind params only: never f-string SQL (CONVENTIONS).
  - Division-by-zero guards: zero data → 0 / None, never exceptions.
  - Unknown plans: skipped with log_event warning, not raised (edge-case).
  - `monthly_value`: period-aware helper for future amortisation (TASK-047/E4).
"""

from __future__ import annotations

import datetime
from datetime import UTC
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, case, func, select
from sqlalchemy.orm import Session

from billing.plans import PLAN_PRICES_USD, Plan
from observability.logging import log_event
from storage.models.business_metrics import BusinessMetricsDaily
from storage.models.subscriptions import BillingPayment, Subscription

# ---------------------------------------------------------------------------
# Named constants (CONVENTIONS: no magic literals)
# ---------------------------------------------------------------------------

# Rolling window used by avg_check and funnel_window by default.
_DEFAULT_WINDOW_DAYS: int = 30

# Minimum age (days) before a user is "matured" for repeat-payment analysis.
# 35 days > one billing month so we have at least one full cycle to measure.
_REPEAT_MATURITY_DAYS: int = 35

# Billing payment status accepted as revenue (not pending / expired / failed).
_PAYMENT_STATUS_PROCESSED: str = "processed"

# Period multipliers for monthly amortisation.
_PERIOD_MONTHS: dict[str, int] = {
    "month": 1,
    "quarter": 3,
    "year": 12,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _known_plans() -> frozenset[str]:
    """Return the set of plan names that have a USD price defined."""
    return frozenset(p.value for p in PLAN_PRICES_USD)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC)


def _window_start(days: int) -> datetime.datetime:
    return _utcnow() - datetime.timedelta(days=days)


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------


def _fetch_active_plan_rows(session: Session) -> list[str]:
    """Execute the active-subscription query once and return raw plan strings.

    Active = expires_at > now().  NULL expires_at rows are excluded by the WHERE
    clause.  This helper is the single source of the query so callers that need
    both MRR and per-plan counts can share one round-trip.
    """
    stmt = select(Subscription.plan).where(
        Subscription.expires_at > bindparam("now", value=_utcnow()),
    )
    return list(session.execute(stmt).scalars().all())


def compute_mrr(session: Session) -> Decimal:
    """Compute Monthly Recurring Revenue from active subscriptions.

    MRR = Σ PLAN_PRICES_USD[plan] for all subscriptions with expires_at > now().
    Subscriptions with NULL expires_at (never-activated placeholders) are excluded
    by the SQL WHERE clause. Unknown plans are skipped with a warning.

    Returns Decimal("0") when there are no active paid subscriptions.
    """
    plans = _fetch_active_plan_rows(session)

    total = Decimal("0")
    known = _known_plans()
    for plan in plans:
        if plan not in known:
            log_event("analytics.unknown_plan", plan=plan, context="compute_mrr")
            continue
        total += PLAN_PRICES_USD[Plan(plan)]
    return total


def active_by_plan(session: Session) -> dict[str, int]:
    """Count active subscriptions grouped by plan.

    Active = expires_at > now() (same predicate as compute_mrr). Unknown plans
    are skipped with a warning and excluded from the result.

    Returns an empty dict when there are no active subscriptions.
    """
    plans = _fetch_active_plan_rows(session)

    counts: dict[str, int] = {}
    known = _known_plans()
    for plan in plans:
        if plan not in known:
            log_event("analytics.unknown_plan", plan=plan, context="active_by_plan")
            continue
        counts[plan] = counts.get(plan, 0) + 1
    return counts


def mrr_and_active_by_plan(session: Session) -> tuple[Decimal, dict[str, int]]:
    """Return (MRR, active_by_plan) using a single DB round-trip.

    Executes the `SELECT plan WHERE expires_at > now()` query exactly once and
    derives both values from the result.  Use this in the ops route to avoid the
    double round-trip that results from calling compute_mrr and active_by_plan
    separately.

    Unknown plans are skipped with a warning (same behaviour as the individual
    functions).
    """
    plans = _fetch_active_plan_rows(session)

    total = Decimal("0")
    counts: dict[str, int] = {}
    known = _known_plans()
    for plan in plans:
        if plan not in known:
            log_event("analytics.unknown_plan", plan=plan, context="mrr_and_active_by_plan")
            continue
        price = PLAN_PRICES_USD[Plan(plan)]
        total += price
        counts[plan] = counts.get(plan, 0) + 1
    return total, counts


def avg_check(session: Session, days: int = _DEFAULT_WINDOW_DAYS) -> Decimal:
    """Compute the average payment amount over the last *days* days.

    Only `processed` payments are included (excludes pending/expired/failed).
    Returns Decimal("0") when there are no qualifying payments (guard against
    division by zero).
    """
    window_start = _window_start(days)
    stmt = select(BillingPayment.amount).where(
        BillingPayment.status == bindparam("status", value=_PAYMENT_STATUS_PROCESSED),
        BillingPayment.processed_at >= bindparam("window_start", value=window_start),
    )
    amounts: list[Decimal] = list(session.execute(stmt).scalars().all())

    if not amounts:
        return Decimal("0")
    return sum(amounts, Decimal("0")) / Decimal(len(amounts))


def repeat_payment_rate(session: Session) -> float | None:
    """Compute the fraction of 'matured' users who have made ≥2 processed payments.

    A user is 'matured' if their first processed payment is older than
    _REPEAT_MATURITY_DAYS days (one full billing cycle has passed, so a repeat
    payment is meaningful).

    Returns None when there are no matured users (no data ≠ 0% — returning 0.0
    would be misleading on a brand-new deployment).
    """
    maturity_cutoff = _utcnow() - datetime.timedelta(days=_REPEAT_MATURITY_DAYS)

    # CTE: per-user payment stats for processed payments only.
    payment_cte = (
        select(
            BillingPayment.user_id,
            func.count(BillingPayment.id).label("payment_count"),
            func.min(BillingPayment.processed_at).label("first_payment_at"),
        )
        .where(BillingPayment.status == bindparam("status", value=_PAYMENT_STATUS_PROCESSED))
        .where(BillingPayment.processed_at.is_not(None))
        .group_by(BillingPayment.user_id)
        .cte("user_payments")
    )

    # Count: matured users total + matured users with ≥2 payments.
    # Use CASE WHEN ... THEN 1 ELSE 0 END to sum booleans safely (no cast needed).
    stmt = select(
        func.sum(
            case(
                (payment_cte.c.payment_count >= 2, 1),
                else_=0,
            )
        ).label("repeat_count"),
        func.count().label("matured_count"),
    ).where(payment_cte.c.first_payment_at < bindparam("maturity_cutoff", value=maturity_cutoff))

    row = session.execute(stmt).one()
    matured_count: int = row.matured_count or 0
    repeat_count_raw = row.repeat_count

    if matured_count == 0:
        return None

    repeat_count: int = int(repeat_count_raw) if repeat_count_raw is not None else 0
    return repeat_count / matured_count


def funnel_window(session: Session, days: int = _DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """Return daily funnel rows from business_metrics_daily for the last *days* days.

    Rows are ordered by day ascending. Days without a row in the table are NOT
    synthetic-zero-filled here (the task contract for TASK-050 guarantees rows exist
    because the beat task writes zeros for empty days). The API layer can choose to
    zero-fill gaps if needed; this function returns raw DB rows.

    Returns an empty list when the table has no rows in the window.
    """
    window_start = (_utcnow() - datetime.timedelta(days=days)).date()
    stmt = (
        select(BusinessMetricsDaily)
        .where(BusinessMetricsDaily.day >= bindparam("window_start", value=window_start))
        .order_by(BusinessMetricsDaily.day.asc())
    )
    rows = list(session.execute(stmt).scalars().all())
    return [
        {
            "day": row.day,
            "registrations": row.registrations,
            "packs_attached": row.packs_attached,
            "first_alerts_delivered": row.first_alerts_delivered,
            "first_feedback": row.first_feedback,
            "new_paid": row.new_paid,
            "churned": row.churned,
            "active_paid": row.active_paid,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# monthly_value helper (for TASK-047/E4 amortisation of annual/quarterly plans)
# ---------------------------------------------------------------------------


def monthly_value(plan: Plan, period: str) -> Decimal:
    """Return the per-month USD value for a plan+period combination.

    - 'month'   → full monthly price (no amortisation needed).
    - 'quarter' → price / 3 (3-month plan amortised monthly).
    - 'year'    → price / 12 (annual plan amortised monthly).

    Raises ValueError for unrecognised periods (explicit error handling, CONVENTIONS).
    This helper is designed to be used by TASK-047 without rewriting this module.
    """
    if period not in _PERIOD_MONTHS:
        raise ValueError(
            f"Unknown billing period {period!r}. Expected one of: {sorted(_PERIOD_MONTHS)}"
        )
    base_price = PLAN_PRICES_USD[plan]
    months = _PERIOD_MONTHS[period]
    return base_price / Decimal(months)
