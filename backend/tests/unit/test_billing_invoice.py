"""AC2 — create invoice (NOWPayments API mocked).

`NowPaymentsGateway.create_invoice` POSTs to NOWPayments and maps the response to
our `Invoice` DTO (payment_url + order_id + price). `service.create_invoice`
persists a pending `billing_payments` row and delegates to the gateway. Both are
exercised with a mocked HTTP layer / mocked session (no network, no DB).
"""

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
    """AC1 (TASK-049): new price grid — Pro $29, Trader/Team $99."""
    from billing.plans import price_for

    assert price_for(Plan.PRO) == Decimal("29")
    assert price_for(Plan.TEAM) == Decimal("99")
