"""AC3/AC4/AC5/AC6 — IPN status machine, idempotency, cross-check (DB-free).

`process_ipn` verifies (delegated to a fake gateway), cross-checks the IPN against
the stored invoice, is idempotent by `payment_id`, and only activates on
`finished`/`confirmed`. The session + gateway are mocked so these stay unit tests.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from billing.gateway.base import IpnEvent, IpnVerificationError
from billing.plans import Plan
from billing.webhook import IpnRejected, process_ipn
from storage.models.subscriptions import BillingPayment


def _payment(
    *, payment_id: str | None = None, processed_at: datetime | None = None, status: str = "pending"
) -> BillingPayment:
    payment = BillingPayment(
        user_id=1,
        order_id="order-1",
        payment_id=payment_id,
        plan="pro",
        period="month",
        amount=Decimal("19"),
        currency="usd",
        status=status,
    )
    payment.processed_at = processed_at
    return payment


def _event(status: str = "finished", payment_id: str = "pay-1") -> IpnEvent:
    return IpnEvent(
        payment_id=payment_id,
        order_id="order-1",
        status=status,
        amount=Decimal("19"),
        currency="usd",
    )


def _gateway(event: IpnEvent) -> MagicMock:
    gateway = MagicMock()
    gateway.verify_ipn.return_value = event
    return gateway


def _session(payment: BillingPayment | None, user: object | None = object()) -> MagicMock:
    session = MagicMock()
    scalars_result = MagicMock()
    scalars_result.one_or_none.return_value = payment
    session.scalars.return_value = scalars_result
    session.get.return_value = user
    return session


def test_invalid_signature_propagates_no_apply() -> None:
    """AC4: gateway verification failure surfaces; the body is never applied."""
    gateway = MagicMock()
    gateway.verify_ipn.side_effect = IpnVerificationError("bad sig")
    session = _session(_payment())
    with pytest.raises(IpnVerificationError):
        process_ipn(session, headers={}, raw_body=b"{}", gateway=gateway)
    session.flush.assert_not_called()


def test_finished_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: a finished IPN activates/extends the plan and records processing."""
    payment = _payment()
    session = _session(payment)
    called: dict[str, object] = {}

    def _activate(sess: object, *, user: object, plan: Plan, period: object) -> object:
        called["plan"] = plan
        return MagicMock()

    monkeypatch.setattr("billing.webhook.activate_or_extend", _activate)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event()))

    assert result.activated is True
    assert result.idempotent_replay is False
    assert called["plan"] is Plan.PRO
    assert payment.payment_id == "pay-1"
    assert payment.processed_at is not None


def test_replay_same_payment_id_is_noop() -> None:
    """AC5: a replayed IPN with an already-processed payment_id is a no-op 200."""
    from storage.models.base import utcnow

    payment = _payment(payment_id="pay-1", processed_at=utcnow(), status="processed")
    session = _session(payment)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event()))

    assert result.idempotent_replay is True
    assert result.activated is False
    session.flush.assert_not_called()


def test_confirming_then_finished_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: NOWPayments sends the SAME payment_id across statuses. A non-
    activating intermediate IPN (confirming) must NOT lock out the later finished
    IPN — the plan must still activate (idempotency keys on activated status)."""
    activations: list[Plan] = []

    def _activate(sess: object, *, user: object, plan: Plan, period: object) -> object:
        activations.append(plan)
        return MagicMock()

    monkeypatch.setattr("billing.webhook.activate_or_extend", _activate)

    payment = _payment()  # pending, processed_at=None
    session = _session(payment)

    # 1) confirming → acked, NOT activated, processed_at stays None.
    r1 = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event("confirming")))
    assert r1.activated is False
    assert payment.processed_at is None
    assert activations == []

    # 2) finished (same payment_id) → MUST activate now.
    r2 = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event("finished")))
    assert r2.activated is True
    assert activations == [Plan.PRO]
    assert payment.processed_at is not None


def test_partially_paid_does_not_activate(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: partially_paid is acked without activation."""
    payment = _payment()
    session = _session(payment)
    activate = MagicMock()
    monkeypatch.setattr("billing.webhook.activate_or_extend", activate)

    result = process_ipn(
        session, headers={}, raw_body=b"{}", gateway=_gateway(_event("partially_paid"))
    )

    assert result.activated is False
    activate.assert_not_called()
    assert payment.status == "partially_paid"


def test_expired_status_does_not_activate(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: an expired-invoice IPN is acked without activation."""
    payment = _payment()
    session = _session(payment)
    activate = MagicMock()
    monkeypatch.setattr("billing.webhook.activate_or_extend", activate)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event("expired")))

    assert result.activated is False
    activate.assert_not_called()


def test_amount_mismatch_rejected() -> None:
    """Anti-spoof: IPN amount differing from the invoice is rejected, no activation."""
    payment = _payment()
    session = _session(payment)
    bad = IpnEvent(
        payment_id="pay-1",
        order_id="order-1",
        status="finished",
        amount=Decimal("1"),
        currency="usd",
    )
    with pytest.raises(IpnRejected):
        process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(bad))


def test_unknown_order_rejected() -> None:
    """An IPN for an order we never created is rejected."""
    session = _session(None)
    with pytest.raises(IpnRejected):
        process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_event()))
