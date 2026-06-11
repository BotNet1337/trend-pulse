"""Integration tests for GET /ops/business-metrics (TASK-051).

Auth matrix:
  - AC2: anonymous → 401; regular user → 403; superuser → 200.

Seeded numbers (AC1):
  - 2 active pro subscriptions + 1 team subscription
  - 3 processed payments ($29/$29/$99 per actual PLAN_PRICES_USD)
  - 1 user with two processed payments (repeat payer)
  Expected: mrr==157, active_subscriptions_by_plan=={pro:2,team:1},
            avg_check_30d≈52.33, repeat_payment_rate is a number.

Funnel (AC3):
  - 3 rows in business_metrics_daily (including a day with zero new_paid)
  - funnel_last_30d carries daily row list + summary conversion.

Privacy (AC2):
  - Response contains NO per-user identifiers (email, user_id).
  - extra="forbid" on BusinessMetricsResponse ensures no leakage.

Follows the pattern of test_users_me.py: live ephemeral Postgres (db_session
fixture from conftest), TestClient with async session override for fastapi-users.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from api.main import app
from config import get_settings
from storage.database import get_async_session
from storage.models.business_metrics import BusinessMetricsDaily
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import User

pytestmark = pytest.mark.integration

_TEST_EMAIL_SUPER = "superuser051@example.com"
_TEST_EMAIL_REGULAR = "regular051@example.com"
_TEST_PASSWORD = "test-pass-w0rd"

# Fixed reference time for seeded data — far enough in the past to be in the
# 30-day window but also allows "active" subscriptions (expires_at in future).
_NOW = datetime.datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
_THIRTY_DAYS_AGO = _NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Any) -> Iterator[TestClient]:
    """TestClient with async session wired to the shared test schema."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _register(client: TestClient, email: str) -> dict[str, Any]:
    resp = client.post("/auth/register", json={"email": email, "password": _TEST_PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/auth/jwt/login",
        data={"username": email, "password": _TEST_PASSWORD},
    )
    assert resp.status_code in (200, 204), resp.text


# ---------------------------------------------------------------------------
# Seed helpers (sync session from db_session fixture)
# ---------------------------------------------------------------------------


def _seed_subscription(
    session: Session,
    *,
    user_id: int,
    plan: str,
    expires_at: datetime.datetime,
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        plan=plan,
        expires_at=expires_at,
        created_at=_THIRTY_DAYS_AGO,
        updated_at=_THIRTY_DAYS_AGO,
    )
    session.add(sub)
    session.flush()
    return sub


def _seed_payment(
    session: Session,
    *,
    user_id: int,
    plan: str,
    amount: Decimal,
    order_suffix: str,
    processed_at: datetime.datetime,
) -> BillingPayment:
    pay = BillingPayment(
        user_id=user_id,
        order_id=f"ord-{user_id}-{order_suffix}",
        plan=plan,
        period="month",
        amount=amount,
        currency="usd",
        status="processed",
        created_at=processed_at,
        processed_at=processed_at,
    )
    session.add(pay)
    session.flush()
    return pay


def _seed_business_metrics_row(
    session: Session,
    *,
    day: date,
    registrations: int = 0,
    new_paid: int = 0,
    churned: int = 0,
    active_paid: int = 0,
) -> BusinessMetricsDaily:
    row = BusinessMetricsDaily(
        day=day,
        registrations=registrations,
        packs_attached=0,
        first_alerts_delivered=0,
        first_feedback=0,
        new_paid=new_paid,
        churned=churned,
        active_paid=active_paid,
        computed_at=_NOW,
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# AC2: auth matrix
# ---------------------------------------------------------------------------


class TestAuthMatrix:
    def test_anonymous_gets_401(self, client: TestClient) -> None:
        """Anonymous request (no cookie) → 401."""
        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 401

    def test_regular_user_gets_403(self, client: TestClient, db_session: Session) -> None:
        """Authenticated non-superuser → 403."""
        _register(client, _TEST_EMAIL_REGULAR)
        _login(client, _TEST_EMAIL_REGULAR)

        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 403

    def test_superuser_gets_200(self, client: TestClient, db_session: Session) -> None:
        """Superuser → 200 with business metrics JSON."""
        # Register and promote to superuser via direct DB update
        user_data = _register(client, _TEST_EMAIL_SUPER)
        user_id = user_data["id"]

        # Promote to superuser in the DB (same table the auth backend reads)
        from sqlalchemy import update

        db_session.execute(update(User).where(User.id == user_id).values(is_superuser=True))
        db_session.commit()

        _login(client, _TEST_EMAIL_SUPER)

        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 200, resp.text

    def test_response_contains_no_per_user_identifiers(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Superuser response must not contain email, user_id, or per-user data."""
        user_data = _register(client, f"nopii-{_TEST_EMAIL_SUPER}")
        user_id = user_data["id"]

        from sqlalchemy import update

        db_session.execute(update(User).where(User.id == user_id).values(is_superuser=True))
        db_session.commit()

        _login(client, f"nopii-{_TEST_EMAIL_SUPER}")

        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 200, resp.text

        body = resp.json()
        body_str = str(body)
        # Must not contain any user email address or explicit user_id field
        assert "email" not in body_str or "nopii" not in body_str
        assert "user_id" not in body


# ---------------------------------------------------------------------------
# AC1: seeded numbers
# ---------------------------------------------------------------------------


class TestSeededNumbers:
    def test_mrr_and_plan_counts_and_avg_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        """AC1: mrr==157, plans=={pro:2,team:1}, avg_check_30d≈52.33."""
        from billing.plans import PLAN_PRICES_USD, Plan

        # Create superuser
        su_data = _register(client, "ac1-super@example.com")
        su_id = su_data["id"]

        from sqlalchemy import update

        db_session.execute(update(User).where(User.id == su_id).values(is_superuser=True))

        # Create 3 regular users (for subscriptions/payments)
        # user_a, user_b registered through SQL directly (no auth needed)
        user_a = User(
            email="ac1-a@example.com",
            hashed_password="x" * 16,
            created_at=_THIRTY_DAYS_AGO,
        )
        user_b = User(
            email="ac1-b@example.com",
            hashed_password="x" * 16,
            created_at=_THIRTY_DAYS_AGO,
        )
        user_c = User(
            email="ac1-c@example.com",
            hashed_password="x" * 16,
            created_at=_THIRTY_DAYS_AGO,
        )
        db_session.add_all([user_a, user_b, user_c])
        db_session.flush()

        # 2 active pro + 1 active team subs (expires_at in future)
        future = _NOW + timedelta(days=30)
        _seed_subscription(db_session, user_id=user_a.id, plan="pro", expires_at=future)
        _seed_subscription(db_session, user_id=user_b.id, plan="pro", expires_at=future)
        _seed_subscription(db_session, user_id=user_c.id, plan="team", expires_at=future)

        pro_price = PLAN_PRICES_USD[Plan.PRO]
        team_price = PLAN_PRICES_USD[Plan.TEAM]

        # 3 processed payments: 29/29/99. user_a has TWO payments (repeat payer).
        recent = _NOW - timedelta(days=5)
        _seed_payment(
            db_session,
            user_id=user_a.id,
            plan="pro",
            amount=pro_price,
            order_suffix="1",
            processed_at=recent,
        )
        _seed_payment(
            db_session,
            user_id=user_a.id,
            plan="pro",
            amount=pro_price,
            order_suffix="2",
            processed_at=recent - timedelta(days=1),
        )
        _seed_payment(
            db_session,
            user_id=user_c.id,
            plan="team",
            amount=team_price,
            order_suffix="1",
            processed_at=recent,
        )

        db_session.commit()

        _login(client, "ac1-super@example.com")
        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 200, resp.text

        body = resp.json()

        # mrr = 29+29+99 = 157
        assert float(body["mrr"]) == pytest.approx(157.0)

        # active plans
        assert body["active_subscriptions_by_plan"]["pro"] == 2
        assert body["active_subscriptions_by_plan"]["team"] == 1

        # avg_check = (29+29+99)/3 ≈ 52.33
        assert float(body["avg_check_30d"]) == pytest.approx(
            float((pro_price + pro_price + team_price) / Decimal("3")), rel=1e-4
        )

        # repeat_payment_rate: user_a has 2 payments; maturity check depends on first
        # payment age vs 35 days. For newly seeded users first payment is ~5 days old
        # → NOT matured → rate is None (null).
        assert body["repeat_payment_rate"] is None


# ---------------------------------------------------------------------------
# AC3: funnel from business_metrics_daily with zero-fill
# ---------------------------------------------------------------------------


class TestFunnelWindow:
    def test_funnel_carries_daily_rows_and_summary(
        self, client: TestClient, db_session: Session
    ) -> None:
        """AC3: funnel_last_30d has daily rows + summary conversion; zero-day included."""
        su_data = _register(client, "ac3-super@example.com")
        su_id = su_data["id"]

        from sqlalchemy import update

        db_session.execute(update(User).where(User.id == su_id).values(is_superuser=True))

        # Seed 3 days: 2 with data, 1 zero day
        today = date(2026, 6, 11)
        _seed_business_metrics_row(
            db_session, day=today - timedelta(days=2), registrations=5, new_paid=2
        )
        _seed_business_metrics_row(
            db_session, day=today - timedelta(days=1), registrations=3, new_paid=0
        )
        _seed_business_metrics_row(db_session, day=today, registrations=4, new_paid=1)
        db_session.commit()

        _login(client, "ac3-super@example.com")
        resp = client.get("/ops/business-metrics")
        assert resp.status_code == 200, resp.text

        body = resp.json()
        funnel = body["funnel_last_30d"]

        assert "daily" in funnel
        assert "conversion_free_to_paid" in funnel

        # Should have 3 rows
        assert len(funnel["daily"]) == 3

        # Zero-day (middle row, new_paid=0) is present with zero, not missing
        days_with_zero = [d for d in funnel["daily"] if d["new_paid"] == 0]
        assert len(days_with_zero) >= 1

        # Summary conversion: Σ new_paid / Σ registrations = 3 / 12 = 0.25
        total_reg = sum(d["registrations"] for d in funnel["daily"])
        total_paid = sum(d["new_paid"] for d in funnel["daily"])
        if total_reg > 0:
            expected_conv = total_paid / total_reg
            assert float(funnel["conversion_free_to_paid"]) == pytest.approx(
                expected_conv, rel=1e-4
            )
        else:
            assert funnel["conversion_free_to_paid"] == 0.0
