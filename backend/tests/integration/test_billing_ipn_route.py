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

from api.main import app
from billing.deps import get_db_session, get_ipn_gateway
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
    resp = client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
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
    first = client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert first.status_code == 200

    db_session_committing.expire_all()
    sub1 = db_session_committing.scalars(
        select(Subscription).where(Subscription.user_id == user.id)
    ).one()
    first_expiry = sub1.expires_at

    second = client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
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
    resp = client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: "deadbeef"})
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
    resp = client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200

    db_session_committing.expire_all()
    refreshed = db_session_committing.get(User, user.id)
    assert refreshed is not None
    assert refreshed.plan == "free"
