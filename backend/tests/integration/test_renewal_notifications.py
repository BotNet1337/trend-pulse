"""Integration: check_expiring_subscriptions — near-expiry sends once (AC1/AC4).

Ephemeral PG (pgvector/pgvector:pg16) — start before running:
    docker run -d --name tp027_pg -e POSTGRES_PASSWORD=pg -e POSTGRES_USER=pg \\
        -e POSTGRES_DB=trendpulse -p 15448:5432 pgvector/pgvector:pg16

ENV:
    POSTGRES_HOST=localhost POSTGRES_PORT=15448 POSTGRES_USER=pg
    POSTGRES_PASSWORD=pg POSTGRES_DB=trendpulse
    JWT_SECRET=test-jwt-secret OAUTH_STATE_SECRET=test-oauth-state-secret
    GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=y

Marked `@pytest.mark.integration` — not run in `make ci-fast`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from billing.gateway.base import GatewayError, Invoice
from billing.plans import BillingPeriod, Plan
from billing.tasks import _check_expiring_subscriptions
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import PLAN_FREE, PLAN_PRO, User


class _FakeGateway:
    """In-memory PaymentGateway for sweep tests (create_invoice only)."""

    def __init__(
        self,
        payment_url: str = "https://np.example/pay/oneclick-1",
        error: Exception | None = None,
    ) -> None:
        self.create_calls = 0
        self._payment_url = payment_url
        self._error = error

    def create_invoice(
        self, *, plan: Plan, period: BillingPeriod, user: User, order_id: str
    ) -> Invoice:
        self.create_calls += 1
        if self._error is not None:
            raise self._error
        return Invoice(
            order_id=order_id,
            payment_url=self._payment_url,
            redirect_url=self._payment_url,
            amount=Decimal("29"),
            currency="usd",
        )

    def verify_ipn(self, *, headers: dict[str, str], raw_body: bytes) -> object:
        raise NotImplementedError("the sweep never verifies IPNs")


def _make_user(
    session: MagicMock,
    *,
    email: str,
    plan: str = PLAN_PRO,
) -> User:
    """Create and flush a minimal User row."""
    user = User(
        email=email,
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        plan=plan,
    )
    session.add(user)
    session.flush()
    return user


def _make_subscription(
    session: MagicMock,
    *,
    user: User,
    plan: str,
    expires_at: datetime | None,
) -> Subscription:
    """Create and flush a Subscription row."""
    sub = Subscription(
        user_id=user.id,
        plan=plan,
        expires_at=expires_at,
    )
    session.add(sub)
    session.flush()
    return sub


# ---------------------------------------------------------------------------
# AC1 + AC4 — near-expiry: reminder sent once; re-tick no-op
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_near_expiry_sends_once_and_is_idempotent(db_session: object) -> None:
    """Subscription with expires_at = now+3d (window 3).

    - First run: send_renewal_reminder called once, last_reminder_window == 3.
    - Second run: send_renewal_reminder NOT called (idempotent).
    """
    now = datetime.now(UTC)
    user = _make_user(db_session, email="renewal-test@example.com", plan=PLAN_PRO)
    sub = _make_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=now + timedelta(days=3),
    )
    db_session.commit()

    with patch("billing.tasks.send_renewal_reminder") as mock_send:
        count = _check_expiring_subscriptions()

    assert count == 1, f"Expected 1 sent, got {count}"
    mock_send.assert_called_once()

    # Reload sub from DB
    db_session.expire(sub)
    db_session.refresh(sub)
    assert sub.last_reminder_window == 3

    # Re-tick: no-op
    with patch("billing.tasks.send_renewal_reminder") as mock_send2:
        count2 = _check_expiring_subscriptions()

    assert count2 == 0, f"Expected 0 on re-tick, got {count2}"
    mock_send2.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 — expired subscription: do not notify
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_expired_subscription_not_notified(db_session: object) -> None:
    """Subscription with expires_at in the past: renewal not sent."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="expired@example.com", plan=PLAN_PRO)
    _make_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=now - timedelta(days=1),
    )
    db_session.commit()

    with patch("billing.tasks.send_renewal_reminder") as mock_send:
        count = _check_expiring_subscriptions()

    assert count == 0
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 — free subscription: do not notify
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_free_subscription_not_notified(db_session: object) -> None:
    """Free plan subscription: renewal not sent."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="free-user@example.com", plan=PLAN_FREE)
    _make_subscription(
        db_session,
        user=user,
        plan=PLAN_FREE,
        expires_at=now + timedelta(days=3),
    )
    db_session.commit()

    with patch("billing.tasks.send_renewal_reminder") as mock_send:
        count = _check_expiring_subscriptions()

    assert count == 0
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 — expires_at > 7 days: outside window, do not notify
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_far_future_subscription_not_notified(db_session: object) -> None:
    """Subscription with expires_at = now+30d (outside 7-day window): not sent."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="far-future@example.com", plan=PLAN_PRO)
    _make_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=now + timedelta(days=30),
    )
    db_session.commit()

    with patch("billing.tasks.send_renewal_reminder") as mock_send:
        count = _check_expiring_subscriptions()

    assert count == 0
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# AC6 — tenant-scope: each email goes to the subscription's owner
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_tenant_scope_each_user_gets_own_notification(db_session: object) -> None:
    """Two users with near-expiry subscriptions each receive their own reminder."""
    now = datetime.now(UTC)
    user1 = _make_user(db_session, email="tenant1@example.com", plan=PLAN_PRO)
    user2 = _make_user(db_session, email="tenant2@example.com", plan=PLAN_PRO)
    _make_subscription(
        db_session,
        user=user1,
        plan=PLAN_PRO,
        expires_at=now + timedelta(days=1),
    )
    _make_subscription(
        db_session,
        user=user2,
        plan=PLAN_PRO,
        expires_at=now + timedelta(days=3),
    )
    db_session.commit()

    calls: list[tuple[object, ...]] = []

    def _capture(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    with patch("billing.tasks.send_renewal_reminder", side_effect=_capture):
        count = _check_expiring_subscriptions()

    assert count == 2

    captured_users = {
        kw.get("user") or args[1]  # type: ignore[index]
        for args, kw in calls  # type: ignore[misc]
    }
    assert len(captured_users) == 2


# ---------------------------------------------------------------------------
# AC3 — renewal does NOT write to the alerts table
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_renewal_does_not_write_to_alerts_table(db_session: object) -> None:
    """After check_expiring_subscriptions runs, the alerts table remains empty (AC3)."""
    from sqlalchemy import text

    now = datetime.now(UTC)
    user = _make_user(db_session, email="noalert@example.com", plan=PLAN_PRO)
    _make_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=now + timedelta(days=1),
    )
    db_session.commit()

    with patch("billing.tasks.send_renewal_reminder"):
        _check_expiring_subscriptions()

    count_alerts = db_session.execute(text("SELECT COUNT(*) FROM alerts")).scalar()
    assert count_alerts == 0, f"Alerts table should be empty, got {count_alerts} rows"


# ---------------------------------------------------------------------------
# TASK-048 — one-click renewal invoice: pre-create, reuse, fallback
# ---------------------------------------------------------------------------


def _user_payments(session: object, user: User) -> list[BillingPayment]:
    return list(
        session.scalars(  # type: ignore[attr-defined]
            select(BillingPayment).where(BillingPayment.user_id == user.id)
        ).all()
    )


@pytest.mark.integration
def test_sweep_precreates_one_click_invoice(db_session: object) -> None:
    """AC1 (TASK-048): the reminder carries the payment_url of a pre-created
    pending invoice, and the billing_payments row persists that URL."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="oneclick@example.com", plan=PLAN_PRO)
    _make_subscription(db_session, user=user, plan=PLAN_PRO, expires_at=now + timedelta(days=3))
    db_session.commit()

    gateway = _FakeGateway()
    sent_kwargs: list[dict[str, object]] = []

    def _capture(**kwargs: object) -> None:
        sent_kwargs.append(kwargs)

    with (
        patch("billing.tasks.get_gateway", return_value=gateway),
        patch("billing.tasks.send_renewal_reminder", side_effect=_capture),
    ):
        count = _check_expiring_subscriptions()

    assert count == 1
    assert sent_kwargs[0]["renew_url"] == "https://np.example/pay/oneclick-1"

    payments = _user_payments(db_session, user)
    assert len(payments) == 1
    assert payments[0].status == "pending"
    assert payments[0].plan == "pro"
    assert payments[0].period == "month"  # no processed payments → MONTH fallback
    assert payments[0].payment_url == "https://np.example/pay/oneclick-1"


@pytest.mark.integration
def test_sweep_reuses_invoice_across_windows(db_session: object) -> None:
    """AC2 (TASK-048): the invoice pre-created in the 3d window is REUSED in the
    1d window — no second billing_payments row, same renew_url."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="reuse@example.com", plan=PLAN_PRO)
    sub = _make_subscription(
        db_session, user=user, plan=PLAN_PRO, expires_at=now + timedelta(days=3)
    )
    db_session.commit()

    gateway = _FakeGateway()
    sent_kwargs: list[dict[str, object]] = []

    def _capture(**kwargs: object) -> None:
        sent_kwargs.append(kwargs)

    with (
        patch("billing.tasks.get_gateway", return_value=gateway),
        patch("billing.tasks.send_renewal_reminder", side_effect=_capture),
    ):
        assert _check_expiring_subscriptions() == 1  # window 3 → invoice created

        # Time passes: the subscription slides into the 1-day window.
        db_session.expire_all()
        db_session.execute(
            Subscription.__table__.update()
            .where(Subscription.id == sub.id)
            .values(expires_at=datetime.now(UTC) + timedelta(hours=20))
        )
        db_session.commit()

        assert _check_expiring_subscriptions() == 1  # window 1 → reuse

    assert gateway.create_calls == 1, "the 1d window must reuse the 3d-window invoice"
    assert len(sent_kwargs) == 2
    assert sent_kwargs[0]["renew_url"] == sent_kwargs[1]["renew_url"]
    assert len(_user_payments(db_session, user)) == 1


@pytest.mark.integration
def test_sweep_falls_back_when_gateway_not_configured(db_session: object) -> None:
    """AC3 (TASK-048): no NOWPayments credentials → reminder still goes out with
    renew_url=None (the sender renders the frontend /billing fallback)."""
    now = datetime.now(UTC)
    user = _make_user(db_session, email="fallback@example.com", plan=PLAN_PRO)
    _make_subscription(db_session, user=user, plan=PLAN_PRO, expires_at=now + timedelta(days=3))
    db_session.commit()

    sent_kwargs: list[dict[str, object]] = []

    def _capture(**kwargs: object) -> None:
        sent_kwargs.append(kwargs)

    # get_gateway NOT patched: test settings carry no NOWPayments credentials,
    # so the sweep takes the BillingNotConfiguredError → None path for real.
    with patch("billing.tasks.send_renewal_reminder", side_effect=_capture):
        count = _check_expiring_subscriptions()

    assert count == 1
    assert sent_kwargs[0]["renew_url"] is None
    assert _user_payments(db_session, user) == []


@pytest.mark.integration
def test_sweep_continues_when_invoice_creation_fails(db_session: object) -> None:
    """AC3 (TASK-048): a gateway error during pre-creation degrades that user to
    the /billing fallback and the sweep still processes everyone."""
    now = datetime.now(UTC)
    user1 = _make_user(db_session, email="gwfail1@example.com", plan=PLAN_PRO)
    user2 = _make_user(db_session, email="gwfail2@example.com", plan=PLAN_PRO)
    _make_subscription(db_session, user=user1, plan=PLAN_PRO, expires_at=now + timedelta(days=1))
    _make_subscription(db_session, user=user2, plan=PLAN_PRO, expires_at=now + timedelta(days=3))
    db_session.commit()

    gateway = _FakeGateway(error=GatewayError("NOWPayments is down"))
    sent_kwargs: list[dict[str, object]] = []

    def _capture(**kwargs: object) -> None:
        sent_kwargs.append(kwargs)

    with (
        patch("billing.tasks.get_gateway", return_value=gateway),
        patch("billing.tasks.send_renewal_reminder", side_effect=_capture),
    ):
        count = _check_expiring_subscriptions()

    assert count == 2
    assert gateway.create_calls == 2
    assert all(kw["renew_url"] is None for kw in sent_kwargs)
    assert _user_payments(db_session, user1) == []
    assert _user_payments(db_session, user2) == []
