"""AC2 — create invoice (NOWPayments API mocked).

`NowPaymentsGateway.create_invoice` POSTs to NOWPayments and maps the response to
our `Invoice` DTO (payment_url + order_id + price). `service.create_invoice`
persists a pending `billing_payments` row and delegates to the gateway. Both are
exercised with a mocked HTTP layer / mocked session (no network, no DB).
"""

from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from billing import service
from billing.gateway.nowpayments import NowPaymentsGateway
from billing.plans import BillingPeriod, Plan
from storage.models.users import User


def _user(user_id: int = 1) -> User:
    user = User()
    user.id = user_id
    user.plan = "free"
    return user


def _gateway() -> NowPaymentsGateway:
    return NowPaymentsGateway(api_key="key", ipn_secret="secret", base_url="http://np/v1")


def test_create_invoice_year_amount_is_278(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2 (TASK-047): a YEAR invoice posts the yearly price to NOWPayments."""
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "invoice_url": "https://nowpayments.io/payment/?iid=year",
        "order_id": "tp-order-year",
    }
    captured: dict[str, object] = {}

    def _post(url: str, **kwargs: object) -> MagicMock:
        captured["json"] = kwargs.get("json")
        return response

    monkeypatch.setattr("billing.gateway.nowpayments.httpx.post", _post)

    invoice = _gateway().create_invoice(
        plan=Plan.PRO, period=BillingPeriod.YEAR, user=_user(), order_id="tp-order-year"
    )

    assert invoice.amount == Decimal("278")
    assert captured["json"]["price_amount"] == "278"  # type: ignore[index]


def test_create_invoice_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "invoice_url": "https://nowpayments.io/payment/?iid=abc",
        "order_id": "tp-order-1",
    }
    captured: dict[str, object] = {}

    def _post(url: str, **kwargs: object) -> MagicMock:
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return response

    monkeypatch.setattr("billing.gateway.nowpayments.httpx.post", _post)

    invoice = _gateway().create_invoice(
        plan=Plan.PRO, period=BillingPeriod.MONTH, user=_user(), order_id="tp-order-1"
    )

    assert invoice.payment_url == "https://nowpayments.io/payment/?iid=abc"
    assert invoice.order_id == "tp-order-1"
    assert invoice.amount == Decimal("29")
    assert invoice.currency == "usd"
    assert captured["url"] == "http://np/v1/invoice"
    # The API key rides in the x-api-key header (never logged).
    assert captured["headers"]["x-api-key"] == "key"  # type: ignore[index]
    assert captured["json"]["price_amount"] == "29"  # type: ignore[index]


def test_create_invoice_missing_url_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"order_id": "tp-order-1"}  # no invoice_url
    monkeypatch.setattr("billing.gateway.nowpayments.httpx.post", lambda url, **k: response)

    from billing.gateway.base import GatewayError

    with pytest.raises(GatewayError):
        _gateway().create_invoice(
            plan=Plan.PRO, period=BillingPeriod.MONTH, user=_user(), order_id="tp-order-1"
        )


def test_service_create_invoice_persists_pending_and_delegates() -> None:
    session = MagicMock()
    gateway = MagicMock()

    service.create_invoice(
        session, user=_user(), plan=Plan.PRO, period=BillingPeriod.MONTH, gateway=gateway
    )

    # A pending billing_payments row was added + flushed before the gateway call.
    session.add.assert_called_once()
    persisted = session.add.call_args.args[0]
    assert persisted.plan == "pro"
    assert persisted.status == "pending"
    assert persisted.amount == Decimal("29")
    gateway.create_invoice.assert_called_once()
    assert gateway.create_invoice.call_args.kwargs["order_id"] == persisted.order_id


def test_service_pro_price_is_29() -> None:
    """AC1 (TASK-049/047): monthly anchor prices — Pro $29, Trader/Team $99."""
    from billing.plans import price_for

    assert price_for(Plan.PRO, BillingPeriod.MONTH) == Decimal("29")
    assert price_for(Plan.TEAM, BillingPeriod.MONTH) == Decimal("99")


@pytest.mark.parametrize(
    ("plan", "period", "expected"),
    [
        (Plan.PRO, BillingPeriod.MONTH, Decimal("29")),
        (Plan.PRO, BillingPeriod.QUARTER, Decimal("78")),
        (Plan.PRO, BillingPeriod.YEAR, Decimal("278")),
        (Plan.TEAM, BillingPeriod.MONTH, Decimal("99")),
        (Plan.TEAM, BillingPeriod.QUARTER, Decimal("267")),
        (Plan.TEAM, BillingPeriod.YEAR, Decimal("950")),
    ],
)
def test_price_grid_per_period(plan: Plan, period: BillingPeriod, expected: Decimal) -> None:
    """AC1 (TASK-047): explicit price grid — quarter -10%, year -20%, rounded down."""
    from billing.plans import price_for

    assert price_for(plan, period) == expected


def test_price_for_free_plan_raises() -> None:
    """AC1 (TASK-047): the free plan has no price for any period."""
    from billing.plans import price_for

    for period in BillingPeriod:
        with pytest.raises(ValueError, match="no price"):
            price_for(Plan.FREE, period)


def test_price_for_unknown_pair_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1 (TASK-047): a plan/period pair missing from the grid raises ValueError."""
    from billing import plans
    from billing.plans import price_for

    trimmed = {Plan.PRO: {BillingPeriod.MONTH: Decimal("29")}}
    monkeypatch.setattr(plans, "PLAN_PERIOD_PRICES_USD", trimmed)
    with pytest.raises(ValueError):
        price_for(Plan.PRO, BillingPeriod.YEAR)


def test_period_days_durations() -> None:
    """AC1 (TASK-047): explicit durations — month 30, quarter 90, year 365 days."""
    from billing.plans import PERIOD_DAYS

    assert PERIOD_DAYS[BillingPeriod.MONTH] == 30
    assert PERIOD_DAYS[BillingPeriod.QUARTER] == 90
    assert PERIOD_DAYS[BillingPeriod.YEAR] == 365


def test_period_end_quarter_and_year() -> None:
    """AC3 (TASK-047): `_period_end` extends by 90/365 days for quarter/year."""
    from datetime import datetime, timedelta

    start = datetime(2026, 6, 11, tzinfo=UTC)
    assert service._period_end(start, BillingPeriod.QUARTER) == start + timedelta(days=90)
    assert service._period_end(start, BillingPeriod.YEAR) == start + timedelta(days=365)


def test_service_year_invoice_persists_year_period_and_amount() -> None:
    """AC2 (TASK-047): a YEAR invoice persists period='year' with the yearly amount."""
    session = MagicMock()
    gateway = MagicMock()

    service.create_invoice(
        session, user=_user(), plan=Plan.PRO, period=BillingPeriod.YEAR, gateway=gateway
    )

    persisted = session.add.call_args.args[0]
    assert persisted.period == "year"
    assert persisted.amount == Decimal("278")
    assert gateway.create_invoice.call_args.kwargs["period"] is BillingPeriod.YEAR


def test_activate_or_extend_year_adds_365_days() -> None:
    """AC3 (TASK-047): activating a year period sets expiry ~now + 365 days."""
    from datetime import timedelta

    from storage.models.base import utcnow

    session = MagicMock()
    session.scalars.return_value.one_or_none.return_value = None  # no existing sub
    user = _user()

    before = utcnow()
    sub = service.activate_or_extend(session, user=user, plan=Plan.PRO, period=BillingPeriod.YEAR)
    after = utcnow()

    assert sub.expires_at >= before + timedelta(days=365)
    assert sub.expires_at <= after + timedelta(days=365)
    assert user.plan == "pro"


def test_activate_or_extend_year_keeps_month_remainder() -> None:
    """AC3 (TASK-047): paying a year on an active month sub extends from the old
    expiry — the remaining days never burn (ADR-004 §4)."""
    from datetime import timedelta

    from storage.models.base import utcnow
    from storage.models.subscriptions import Subscription

    remaining_expiry = utcnow() + timedelta(days=10)
    existing = Subscription(user_id=1, plan="pro", expires_at=remaining_expiry)
    session = MagicMock()
    session.scalars.return_value.one_or_none.return_value = existing

    sub = service.activate_or_extend(
        session, user=_user(), plan=Plan.PRO, period=BillingPeriod.YEAR
    )

    assert sub.expires_at == remaining_expiry + timedelta(days=365)
