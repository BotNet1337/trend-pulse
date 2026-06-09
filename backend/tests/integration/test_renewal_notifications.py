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
from unittest.mock import MagicMock, patch

import pytest

from billing.tasks import _check_expiring_subscriptions
from storage.models.subscriptions import Subscription
from storage.models.users import PLAN_FREE, PLAN_PRO, User


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
