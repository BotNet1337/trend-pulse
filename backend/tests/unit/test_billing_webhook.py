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
    *,
    payment_id: str | None = None,
    processed_at: datetime | None = None,
    status: str = "pending",
    period: str = "month",
    amount: Decimal = Decimal("19"),
    payment_url: str | None = None,
) -> BillingPayment:
    payment = BillingPayment(
        user_id=1,
        order_id="order-1",
        payment_id=payment_id,
        plan="pro",
        period=period,
        amount=amount,
        currency="usd",
        status=status,
        payment_url=payment_url,
    )
    payment.processed_at = processed_at
    return payment


def _event(
    status: str = "finished",
    payment_id: str = "pay-1",
    amount: Decimal = Decimal("19"),
    actually_paid: Decimal | None = None,
) -> IpnEvent:
    return IpnEvent(
        payment_id=payment_id,
        order_id="order-1",
        status=status,
        amount=amount,
        currency="usd",
        actually_paid=actually_paid,
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


def test_finished_year_invoice_activates_with_year_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3 (TASK-047): a finished IPN for a period='year' invoice restores
    BillingPeriod.YEAR from the stored row and activates with it."""
    from billing.plans import BillingPeriod

    payment = _payment(period="year", amount=Decimal("278"))
    session = _session(payment)
    called: dict[str, object] = {}

    def _activate(sess: object, *, user: object, plan: Plan, period: object) -> object:
        called["period"] = period
        return MagicMock()

    monkeypatch.setattr("billing.webhook.activate_or_extend", _activate)

    event = IpnEvent(
        payment_id="pay-year-1",
        order_id="order-1",
        status="finished",
        amount=Decimal("278"),
        currency="usd",
    )
    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(event))

    assert result.activated is True
    assert called["period"] is BillingPeriod.YEAR


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


# ─── TASK-048 (AC6/AC7): partially_paid → best-effort underpaid email ─────────


def _partial_event(actually_paid: Decimal | None = Decimal("20")) -> IpnEvent:
    return _event("partially_paid", amount=Decimal("29"), actually_paid=actually_paid)


def test_partially_paid_transition_sends_underpaid_email_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: first partially_paid IPN ($29 invoice, $20 paid) → one email with
    amount_due=$9 and the invoice's own payment_url (never an IPN-supplied URL)."""
    payment = _payment(amount=Decimal("29"), payment_url="https://np.example/pay/1")
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))

    assert result.activated is False
    assert payment.status == "partially_paid"
    notice.assert_called_once()
    kwargs = notice.call_args.kwargs
    assert kwargs["amount_due"] == Decimal("9")
    assert kwargs["pay_url"] == "https://np.example/pay/1"


def test_partially_paid_replay_sends_no_second_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: a re-sent partially_paid IPN sees status already partially_paid → no email."""
    payment = _payment(
        amount=Decimal("29"), status="partially_paid", payment_url="https://np.example/pay/1"
    )
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))

    assert result.activated is False
    notice.assert_not_called()


def test_partially_paid_then_finished_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: partially_paid never sets processed_at — the later finished IPN activates."""
    payment = _payment(amount=Decimal("29"), payment_url="https://np.example/pay/1")
    session = _session(payment)
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", MagicMock())
    activations: list[Plan] = []

    def _activate(sess: object, *, user: object, plan: Plan, period: object) -> object:
        activations.append(plan)
        return MagicMock()

    monkeypatch.setattr("billing.webhook.activate_or_extend", _activate)

    r1 = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))
    assert r1.activated is False
    assert payment.processed_at is None

    r2 = process_ipn(
        session, headers={}, raw_body=b"{}", gateway=_gateway(_event(amount=Decimal("29")))
    )
    assert r2.activated is True
    assert activations == [Plan.PRO]
    assert payment.processed_at is not None


def test_partially_paid_email_failure_still_acks(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC7: an email-hook crash is swallowed — status persisted, no exception."""
    payment = _payment(amount=Decimal("29"), payment_url="https://np.example/pay/1")
    session = _session(payment)
    notice = MagicMock(side_effect=RuntimeError("smtp down"))
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))

    assert result.activated is False
    assert payment.status == "partially_paid"
    notice.assert_called_once()


def test_partially_paid_without_actually_paid_amount_due_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: `actually_paid` absent in the IPN → email goes out without a sum."""
    payment = _payment(amount=Decimal("29"), payment_url="https://np.example/pay/1")
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    process_ipn(
        session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event(actually_paid=None))
    )

    notice.assert_called_once()
    assert notice.call_args.kwargs["amount_due"] is None


def test_partially_paid_overpaid_dust_amount_due_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge: actually_paid >= amount (exchange-rate dust) → no sum in the email."""
    payment = _payment(amount=Decimal("29"), payment_url="https://np.example/pay/1")
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    process_ipn(
        session,
        headers={},
        raw_body=b"{}",
        gateway=_gateway(_partial_event(actually_paid=Decimal("29"))),
    )

    notice.assert_called_once()
    assert notice.call_args.kwargs["amount_due"] is None


def test_partially_paid_without_payment_url_falls_back_to_billing_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: pre-0021 row without payment_url → fallback to frontend /billing."""
    payment = _payment(amount=Decimal("29"), payment_url=None)
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))

    notice.assert_called_once()
    assert notice.call_args.kwargs["pay_url"].endswith("/billing")


# ─── TASK-048: notification props (underpaid email + one-click renewUrl) ──────


def _capture_send(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _send(*, to: str, template: str, subject: str, props: dict[str, object]) -> None:
        captured.update({"to": to, "template": template, "subject": subject, "props": props})

    monkeypatch.setattr("billing.notifications.send_templated_email", _send)
    return captured


def _mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.email = "payer@example.com"
    return user


def test_send_underpaid_notice_formats_amount_with_cents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: the email props carry a JSON-safe '9.00' string, never a raw Decimal
    (Numeric(38,18) rows would otherwise render '9.000000000000000000')."""
    from billing.notifications import send_underpaid_notice

    captured = _capture_send(monkeypatch)
    send_underpaid_notice(
        user=_mock_user(),
        payment=_payment(amount=Decimal("29.000000000000000000")),
        amount_due=Decimal("9.000000000000000000"),
        pay_url="https://np.example/pay/1",
    )

    assert captured["template"] == "billing/underpaid"
    props = captured["props"]
    assert props["amountDue"] == "9.00"  # type: ignore[index]
    assert props["payUrl"] == "https://np.example/pay/1"  # type: ignore[index]
    assert props["planName"] == "pro"  # type: ignore[index]


def test_send_underpaid_notice_without_amount_sends_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: unknown remaining balance → amountDue prop is null (sum omitted)."""
    from billing.notifications import send_underpaid_notice

    captured = _capture_send(monkeypatch)
    send_underpaid_notice(
        user=_mock_user(),
        payment=_payment(amount=Decimal("29")),
        amount_due=None,
        pay_url="https://np.example/pay/1",
    )

    assert captured["props"]["amountDue"] is None  # type: ignore[index]


def test_send_renewal_reminder_uses_one_click_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: an explicit renew_url (pre-created invoice) lands in the renewUrl prop."""
    from billing.notifications import send_renewal_reminder

    captured = _capture_send(monkeypatch)
    sub = MagicMock()
    sub.id = 7
    sub.plan = "pro"
    send_renewal_reminder(
        subscription=sub,
        user=_mock_user(),
        window_days=3,
        renew_url="https://np.example/pay/oneclick",
    )

    assert captured["props"]["renewUrl"] == "https://np.example/pay/oneclick"  # type: ignore[index]


def test_send_renewal_reminder_defaults_to_billing_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3: renew_url=None keeps the legacy frontend /billing fallback."""
    from billing.notifications import send_renewal_reminder

    captured = _capture_send(monkeypatch)
    sub = MagicMock()
    sub.id = 7
    sub.plan = "pro"
    send_renewal_reminder(subscription=sub, user=_mock_user(), window_days=3, renew_url=None)

    renew_url = captured["props"]["renewUrl"]  # type: ignore[index]
    assert isinstance(renew_url, str)
    assert renew_url.endswith("/billing")


def test_partially_paid_after_processed_is_replay_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge: late out-of-order partially_paid AFTER activation → idempotency guard
    short-circuits before the email hook — no email, no status change."""
    from storage.models.base import utcnow

    payment = _payment(
        payment_id="pay-1", processed_at=utcnow(), status="processed", amount=Decimal("29")
    )
    session = _session(payment)
    notice = MagicMock()
    monkeypatch.setattr("billing.webhook.send_underpaid_notice", notice)

    result = process_ipn(session, headers={}, raw_body=b"{}", gateway=_gateway(_partial_event()))

    assert result.idempotent_replay is True
    assert payment.status == "processed"
    notice.assert_not_called()
