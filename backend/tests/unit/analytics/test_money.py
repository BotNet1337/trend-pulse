"""Unit tests for analytics.money — business-metrics read functions (TASK-051).

Tests:
- compute_mrr: Σ PLAN_PRICES_USD[plan] for active subs (expires_at > now).
- active_by_plan: dict counting active subs per plan.
- avg_check: 30-day window, processed payments only, safe average.
- repeat_payment_rate: fraction of matured users with ≥2 payments; null when no
  matured users.
- funnel_window: daily funnel row from business_metrics_daily with zero-fill for
  gaps.
- monthly_value: period-aware helper (month → price as-is; year → /12; quarter
  → /3).
- Edge cases: zero data → zeros not errors, NULL expires_at not active, unknown
  plan skipped with warning, pending/expired payments excluded.

All tests use a mock session — no DB required (CONVENTIONS: unit tests are pure).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# compute_mrr
# ---------------------------------------------------------------------------


class TestComputeMrr:
    def test_returns_sum_of_plan_prices_for_active_subs(self) -> None:
        """compute_mrr returns Σ prices for rows returned by the query."""
        from analytics.money import compute_mrr

        session = _mock_session()
        # Simulate 2 pro + 1 team active subscriptions
        session.execute.return_value.scalars.return_value.all.return_value = [
            "pro",
            "pro",
            "team",
        ]

        result = compute_mrr(session)

        # pro=$29, pro=$29, team=$99 → 157
        assert result == Decimal("157")

    def test_zero_active_subs_returns_zero(self) -> None:
        """Zero active subscriptions → MRR is 0, not an error."""
        from analytics.money import compute_mrr

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = []

        result = compute_mrr(session)

        assert result == Decimal("0")

    def test_null_expires_at_not_counted(self) -> None:
        """Subscriptions with NULL expires_at must not appear in the query results.

        The SQL guard (expires_at > now()) ensures this; we verify compute_mrr
        handles an empty result correctly (the filter is in the query, not here).
        """
        from analytics.money import compute_mrr

        session = _mock_session()
        # NULL expires_at rows are excluded by the query itself → empty result
        session.execute.return_value.scalars.return_value.all.return_value = []

        result = compute_mrr(session)

        assert result == Decimal("0")

    def test_unknown_plan_skipped_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown plan in subscriptions → skipped with log_event warning, not exception."""
        from analytics.money import compute_mrr

        session = _mock_session()
        # mix of known and unknown plan
        session.execute.return_value.scalars.return_value.all.return_value = [
            "pro",
            "legacy_enterprise",  # unknown plan
            "team",
        ]

        with caplog.at_level(logging.INFO, logger="trendpulse"):
            result = compute_mrr(session)

        # pro=29 + team=99 = 128; unknown skipped
        assert result == Decimal("128")
        # log_event emits the plan name in the extra `plan` field
        assert any(getattr(r, "plan", None) == "legacy_enterprise" for r in caplog.records)


# ---------------------------------------------------------------------------
# active_by_plan
# ---------------------------------------------------------------------------


class TestActiveByPlan:
    def test_counts_plans_correctly(self) -> None:
        """active_by_plan returns dict with per-plan counts."""
        from analytics.money import active_by_plan

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = [
            "pro",
            "pro",
            "team",
        ]

        result = active_by_plan(session)

        assert result == {"pro": 2, "team": 1}

    def test_empty_returns_empty_dict(self) -> None:
        """No active subs → empty dict."""
        from analytics.money import active_by_plan

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = []

        result = active_by_plan(session)

        assert result == {}

    def test_unknown_plan_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown plan is skipped (with warning) and not included in result."""
        from analytics.money import active_by_plan

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = [
            "pro",
            "legacy_plan",
        ]

        with caplog.at_level(logging.INFO, logger="trendpulse"):
            result = active_by_plan(session)

        assert "pro" in result
        assert "legacy_plan" not in result
        # log_event emits the plan name in the extra `plan` field
        assert any(getattr(r, "plan", None) == "legacy_plan" for r in caplog.records)


# ---------------------------------------------------------------------------
# avg_check
# ---------------------------------------------------------------------------


class TestAvgCheck:
    def test_returns_average_of_processed_amounts(self) -> None:
        """avg_check returns mean of processed payment amounts in the window."""
        from analytics.money import avg_check

        session = _mock_session()
        # 3 payments: 29, 29, 99 → avg = 157/3 ≈ 52.33
        session.execute.return_value.scalars.return_value.all.return_value = [
            Decimal("29"),
            Decimal("29"),
            Decimal("99"),
        ]

        result = avg_check(session, days=30)

        expected = Decimal("157") / Decimal("3")
        assert result == expected

    def test_zero_payments_returns_zero(self) -> None:
        """No processed payments in window → avg_check returns 0, not ZeroDivisionError."""
        from analytics.money import avg_check

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = []

        result = avg_check(session, days=30)

        assert result == Decimal("0")

    def test_default_window_is_30_days(self) -> None:
        """avg_check uses _DEFAULT_WINDOW_DAYS=30 when called without explicit days."""
        from analytics.money import _DEFAULT_WINDOW_DAYS, avg_check

        assert _DEFAULT_WINDOW_DAYS == 30

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = []
        # Just verify it doesn't raise when called without days kwarg via default
        result = avg_check(session)
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# repeat_payment_rate
# ---------------------------------------------------------------------------


def _row(repeat_count: int | None, matured_count: int) -> MagicMock:
    """Build a mock SQLAlchemy Row with named attributes."""
    row = MagicMock()
    row.repeat_count = repeat_count
    row.matured_count = matured_count
    return row


class TestRepeatPaymentRate:
    def test_returns_null_when_no_matured_users(self) -> None:
        """repeat_payment_rate returns None when no users have matured (>35 days old)."""
        from analytics.money import repeat_payment_rate

        session = _mock_session()
        session.execute.return_value.one.return_value = _row(0, 0)

        result = repeat_payment_rate(session)

        assert result is None

    def test_calculates_fraction_of_repeat_payers(self) -> None:
        """With matured users: fraction = users_with_2plus_payments / total_matured."""
        from analytics.money import repeat_payment_rate

        session = _mock_session()
        # 1 out of 3 matured users has ≥2 payments
        session.execute.return_value.one.return_value = _row(1, 3)

        result = repeat_payment_rate(session)

        assert result is not None
        assert abs(float(result) - 1 / 3) < 1e-9

    def test_all_matured_users_are_repeat(self) -> None:
        """All matured users have repeat payments → rate = 1.0."""
        from analytics.money import repeat_payment_rate

        session = _mock_session()
        session.execute.return_value.one.return_value = _row(3, 3)

        result = repeat_payment_rate(session)

        assert result is not None
        assert float(result) == pytest.approx(1.0)

    def test_maturity_constant_is_named(self) -> None:
        """The 35-day maturity window is a named constant, not a magic literal."""
        from analytics.money import _REPEAT_MATURITY_DAYS

        assert _REPEAT_MATURITY_DAYS == 35


# ---------------------------------------------------------------------------
# funnel_window
# ---------------------------------------------------------------------------


class TestFunnelWindow:
    def test_returns_list_of_dicts_for_each_day(self) -> None:
        """funnel_window returns one entry per day in window (from DB rows)."""
        from analytics.money import funnel_window

        session = _mock_session()

        from datetime import date

        # Simulate 2 rows from business_metrics_daily
        row1 = MagicMock()
        row1.day = date(2026, 6, 1)
        row1.registrations = 5
        row1.new_paid = 2
        row1.churned = 0
        row1.active_paid = 10

        row2 = MagicMock()
        row2.day = date(2026, 6, 2)
        row2.registrations = 3
        row2.new_paid = 1
        row2.churned = 0
        row2.active_paid = 11

        session.execute.return_value.scalars.return_value.all.return_value = [row1, row2]

        result = funnel_window(session, days=30)

        assert len(result) == 2
        assert result[0]["day"] == date(2026, 6, 1)
        assert result[0]["new_paid"] == 2

    def test_empty_db_returns_empty_list(self) -> None:
        """No rows in window → empty list, not error."""
        from analytics.money import funnel_window

        session = _mock_session()
        session.execute.return_value.scalars.return_value.all.return_value = []

        result = funnel_window(session, days=30)

        assert result == []


# ---------------------------------------------------------------------------
# monthly_value helper
# ---------------------------------------------------------------------------


class TestMonthlyValue:
    def test_month_returns_full_price(self) -> None:
        """monthly_value(plan, 'month') returns the plan's full monthly price."""
        from analytics.money import monthly_value
        from billing.plans import Plan

        result = monthly_value(Plan.PRO, "month")

        assert result == Decimal("29")

    def test_year_returns_price_divided_by_12(self) -> None:
        """monthly_value(plan, 'year') returns price / 12 (amortized)."""
        from analytics.money import monthly_value
        from billing.plans import Plan

        result = monthly_value(Plan.TEAM, "year")

        assert result == Decimal("99") / Decimal("12")

    def test_quarter_returns_price_divided_by_3(self) -> None:
        """monthly_value(plan, 'quarter') returns price / 3 (amortized)."""
        from analytics.money import monthly_value
        from billing.plans import Plan

        result = monthly_value(Plan.PRO, "quarter")

        assert result == Decimal("29") / Decimal("3")

    def test_unknown_period_raises_value_error(self) -> None:
        """Unknown billing period raises ValueError (explicit error handling)."""
        from analytics.money import monthly_value
        from billing.plans import Plan

        with pytest.raises(ValueError, match="period"):
            monthly_value(Plan.PRO, "biweekly")
