"""`GET /ops/business-metrics` — superuser-only business dashboard (TASK-051).

Returns a single JSON snapshot of revenue, subscription state, and funnel
metrics for the product owner. Gated behind `current_superuser` (fastapi-users
`is_superuser` flag, ADR-003). Non-superusers → 403, unauthenticated → 401.

Invariants:
  - Read-only: no DB writes on GET.
  - No per-user identifiers in response (Pydantic `extra="forbid"` + explicit
    aggregate-only model — `email`, `user_id` are structurally excluded).
  - Metric computation delegated to `analytics.money` pure read functions.
  - `funnel_last_30d` sourced from `business_metrics_daily` (TASK-050 contract).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from analytics.money import (
    _DEFAULT_WINDOW_DAYS,
    avg_check,
    funnel_window,
    mrr_and_active_by_plan,
    repeat_payment_rate,
)
from api.auth.backend import current_superuser
from storage.database import SessionLocal
from storage.models.users import User

router = APIRouter(tags=["ops"])


# ---------------------------------------------------------------------------
# Pydantic response model — aggregates only, no per-user fields
# ---------------------------------------------------------------------------


class FunnelDayRow(BaseModel):
    """One UTC calendar day's funnel counters (from business_metrics_daily)."""

    model_config = ConfigDict(extra="forbid")

    day: date
    registrations: int
    packs_attached: int
    first_alerts_delivered: int
    first_feedback: int
    new_paid: int
    churned: int
    active_paid: int


class FunnelSummary(BaseModel):
    """30-day funnel window with daily rows + summary conversion rate."""

    model_config = ConfigDict(extra="forbid")

    daily: list[FunnelDayRow]
    # Σ new_paid / Σ registrations in window; 0.0 when no registrations.
    conversion_free_to_paid: float


class BusinessMetricsResponse(BaseModel):
    """Aggregate business metrics response (no per-user data, extra='forbid').

    All fields are global aggregates; no `email`, `user_id`, or other PII.
    `extra='forbid'` means an accidental per-user field would raise at response
    validation time, making the invariant structurally enforced.
    """

    model_config = ConfigDict(extra="forbid")

    # Monthly Recurring Revenue in USD (Σ PLAN_PRICES_USD[plan] for active subs).
    mrr: Decimal
    # Active subscriptions by plan name (e.g. {"pro": 2, "team": 1}).
    active_subscriptions_by_plan: dict[str, int]
    # Average payment amount over the last 30 days (processed payments only).
    avg_check_30d: Decimal
    # Daily funnel from business_metrics_daily + summary conversion.
    funnel_last_30d: FunnelSummary
    # Fraction of matured users (first payment > 35 days ago) with ≥2 payments.
    # Null when no matured users exist (no data ≠ 0%).
    repeat_payment_rate: float | None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/ops/business-metrics",
    response_model=BusinessMetricsResponse,
    summary="Business metrics snapshot (superuser only)",
)
def get_business_metrics(
    _user: Annotated[User, Depends(current_superuser)],
) -> BusinessMetricsResponse:
    """Return an aggregate business metrics snapshot.

    Auth:
    - 401 if no valid session cookie.
    - 403 if authenticated but not a superuser.
    - 200 with JSON body for a superuser.

    All values are global aggregates; no per-user identifiers are included.
    """
    with SessionLocal() as session:
        mrr, by_plan = mrr_and_active_by_plan(session)
        avg = avg_check(session, days=_DEFAULT_WINDOW_DAYS)
        rate = repeat_payment_rate(session)
        daily_rows = funnel_window(session, days=_DEFAULT_WINDOW_DAYS)

    # Build funnel summary: conversion = Σ new_paid / Σ registrations
    total_new_paid = sum(r["new_paid"] for r in daily_rows)
    total_reg_for_conv = sum(r["registrations"] for r in daily_rows)
    conversion = total_new_paid / total_reg_for_conv if total_reg_for_conv > 0 else 0.0

    funnel = FunnelSummary(
        daily=[FunnelDayRow(**row) for row in daily_rows],
        conversion_free_to_paid=conversion,
    )

    return BusinessMetricsResponse(
        mrr=mrr,
        active_subscriptions_by_plan=by_plan,
        avg_check_30d=avg,
        funnel_last_30d=funnel,
        repeat_payment_rate=rate,
    )
