"""Billing IPN route integration tests (marker: integration).

Runs against the live pgvector Postgres via `TestClient`. The IPN gateway is bound
to a `NowPaymentsGateway` configured with a TEST IPN secret, and bodies are signed
the way NOWPayments signs them (HMAC-SHA512 over sorted-key compact JSON).

- AC3: valid `finished` IPN → user.plan = pro + subscriptions.expires_at set.
- AC5: replaying the same payment_id → no double-extend, still 200.
- AC4: invalid signature → 401, plan unchanged.
- AC6: partially_paid → 200, no activation.
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from api.deps import current_user
from api.main import app
from billing.deps import get_db_session, get_gateway, get_ipn_gateway
from billing.gateway.nowpayments import NowPaymentsGateway
from storage.models.base import utcnow
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import User

pytestmark = pytest.mark.integration

_IPN_SECRET = "integration-ipn-secret"
_SIG_HEADER = "x-nowpayments-sig"


def _sign(body: dict[str, object]) -> tuple[bytes, str]:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_IPN_SECRET.encode("utf-8"), raw, hashlib.sha512).hexdigest()
    return raw, sig


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with db_engine.begin() as conn:
            from storage.models import Base

            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def user(db_session_committing: Session) -> User:
    u = User(email="payer@example.com", hashed_password="x" * 16)
    db_session_committing.add(u)
    db_session_committing.flush()
    return u


@pytest.fixture
def invoice(db_session_committing: Session, user: User) -> BillingPayment:
    payment = BillingPayment(
        user_id=user.id,
        order_id="order-int-1",
        payment_id=None,
        plan="pro",
        period="month",
        amount=Decimal("19"),
        currency="usd",
        status="pending",
    )
    db_session_committing.add(payment)
    db_session_committing.flush()
    return payment


@pytest.fixture
def client(db_session_committing: Session) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    gateway = NowPaymentsGateway(api_key="", ipn_secret=_IPN_SECRET, base_url="http://np")
    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_ipn_gateway] = lambda: gateway
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ipn_gateway, None)


def _ipn_body(status: str = "finished") -> dict[str, object]:
    return {
        "payment_id": "np-pay-1",
        "order_id": "order-int-1",
        "payment_status": status,
        "price_amount": "19",
        "price_currency": "usd",
    }


def test_finished_ipn_activates_plan(
    client: TestClient, db_session_committing: Session, user: User, invoice: BillingPayment
) -> None:
    """AC3: valid finished IPN → plan pro + expires_at set, 200."""
    raw, sig = _sign(_ipn_body())
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200, resp.text

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "pro"
    sub = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one_or_none()
    assert sub is not None
    assert sub.expires_at is not None
    assert sub.expires_at > utcnow()


def test_replay_same_payment_id_no_double_extend(
    client: TestClient, db_session_committing: Session, user: User, invoice: BillingPayment
) -> None:
    """AC5: replaying the same payment_id does not extend expiry twice; still 200."""
    raw, sig = _sign(_ipn_body())
    first = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert first.status_code == 200

    db_session_committing.expire_all()
    sub1 = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one()
    first_expiry = sub1.expires_at

    second = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert second.status_code == 200

    db_session_committing.expire_all()
    sub2 = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one()
    assert sub2.expires_at == first_expiry  # no double-extend


def test_invalid_signature_rejected_no_change(
    client: TestClient, db_session_committing: Session, user: User, invoice: BillingPayment
) -> None:
    """AC4: a wrong signature → 401 and the plan is unchanged."""
    raw, _ = _sign(_ipn_body())
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: "deadbeef"})
    assert resp.status_code == 401

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "free"


def test_partially_paid_no_activation(
    client: TestClient, db_session_committing: Session, user: User, invoice: BillingPayment
) -> None:
    """AC6: partially_paid → 200 but plan stays free, no subscription activated."""
    raw, sig = _sign(_ipn_body("partially_paid"))
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "free"


def test_partially_paid_persists_status_and_notifies_once(
    client: TestClient,
    db_session_committing: Session,
    user: User,
    invoice: BillingPayment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6 (TASK-048): partially_paid → 200, status saved in the DB, underpaid
    notice sent exactly once with amount_due = invoice - actually_paid; the
    replayed IPN sends no second email."""
    from unittest.mock import MagicMock

    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    body = _ipn_body("partially_paid")
    body["actually_paid"] = "10"
    raw, sig = _sign(body)

    first = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert first.status_code == 200, first.text

    db_session_committing.expire_all()
    stored = db_session_committing.scalars(
        select(BillingPayment).where(BillingPayment.order_id == "order-int-1")
    ).one()
    assert stored.status == "partially_paid"
    notice.assert_called_once()
    assert notice.call_args.kwargs["amount_due"] == Decimal("9")  # 19 - 10

    # Replay: NOWPayments re-sends the same IPN — no second email, still 200.
    second = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert second.status_code == 200
    notice.assert_called_once()


def test_partially_paid_then_finished_activates(
    client: TestClient,
    db_session_committing: Session,
    user: User,
    invoice: BillingPayment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6 (TASK-048): a finished IPN AFTER partially_paid still activates the
    plan (no processed_at in the partial branch)."""
    from unittest.mock import MagicMock

    monkeypatch.setattr("billing.webhook.send_underpaid_notice", MagicMock())

    partial = _ipn_body("partially_paid")
    partial["actually_paid"] = "10"
    raw, sig = _sign(partial)
    assert (
        client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig}).status_code == 200
    )

    raw, sig = _sign(_ipn_body("finished"))
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200, resp.text

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "pro"
    sub = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one()
    assert sub.expires_at is not None
    assert sub.expires_at > utcnow()


def test_create_year_invoice_persists_year_payment(
    client: TestClient,
    db_session_committing: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 (TASK-047): POST /billing/invoice {period:'year'} → amount '278' and a
    pending billing_payments row with period='year' (real gateway pricing path,
    only the outbound HTTP call is stubbed)."""

    def _post(url: str, **kwargs: object) -> object:
        class _Resp:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict[str, object]:
                return {"invoice_url": "https://nowpayments.io/payment/?iid=year"}

        return _Resp()

    monkeypatch.setattr("billing.gateway.nowpayments.httpx.post", _post)
    invoice_gateway = NowPaymentsGateway(api_key="k", ipn_secret=_IPN_SECRET, base_url="http://np")
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_gateway] = lambda: invoice_gateway
    try:
        resp = client.post("/v1/billing/invoice", json={"plan": "pro", "period": "year"})
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_gateway, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == "278"
    assert body["currency"] == "usd"

    db_session_committing.expire_all()
    payment = db_session_committing.scalars(
        select(BillingPayment).where(BillingPayment.order_id == body["order_id"])
    ).one()
    assert payment.period == "year"
    assert payment.amount == Decimal("278")
    assert payment.status == "pending"


def test_finished_year_ipn_extends_365_days(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC3 (TASK-047): a finished IPN on a year invoice sets expires_at ≈ now+365d."""
    from datetime import timedelta

    year_invoice = BillingPayment(
        user_id=user.id,
        order_id="order-year-1",
        payment_id=None,
        plan="pro",
        period="year",
        amount=Decimal("278"),
        currency="usd",
        status="pending",
    )
    db_session_committing.add(year_invoice)
    db_session_committing.flush()

    ipn_body = {
        "payment_id": "np-pay-year-1",
        "order_id": "order-year-1",
        "payment_status": "finished",
        "price_amount": "278",
        "price_currency": "usd",
    }
    before = utcnow()
    raw, sig = _sign(ipn_body)
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200, resp.text

    db_session_committing.expire_all()
    sub = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one()
    assert sub.expires_at is not None
    assert sub.expires_at >= before + timedelta(days=365)
    assert sub.expires_at <= utcnow() + timedelta(days=365)


def test_old_price_invoice_activates_after_price_bump(
    client: TestClient, db_session_committing: Session, user: User
) -> None:
    """AC4 (TASK-049): grandfathering — invoice created at OLD price ($19) activates
    when the matching finished IPN arrives, even after constants changed to $29.

    The IPN handler matches by order_id against the stored billing_payments row;
    activation is based on the INVOICE amount, not the new price constant.
    This test uses the same fixture pattern as `invoice` but constructs a $19 row
    inline to make the grandfathering intent explicit.
    """
    # Create a pending invoice at the old $19 price (pre-TASK-049).
    old_invoice = BillingPayment(
        user_id=user.id,
        order_id="order-grandfa-1",
        payment_id=None,
        plan="pro",
        period="month",
        amount=Decimal("19"),  # old price — constants are now 29
        currency="usd",
        status="pending",
    )
    db_session_committing.add(old_invoice)
    db_session_committing.flush()

    ipn_body = {
        "payment_id": "np-grandfa-1",
        "order_id": "order-grandfa-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw, sig = _sign(ipn_body)
    resp = client.post("/v1/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200, resp.text

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "pro", (
        "Old-price invoice must activate plan (grandfathering): "
        "IPN activation compares against invoice row, not new constant"
    )
    sub = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one_or_none()
    assert sub is not None
    assert sub.expires_at is not None
    assert sub.expires_at > utcnow()
