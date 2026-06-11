"""Integration tests for business_metrics_daily aggregate (TASK-050 AC2-AC4).

Requires a live Postgres with the full schema (db_session fixture).

Covers:
- AC2: seeded data → expected row values {2,1,1,1,1,1,active_paid=correct}.
- AC3: idempotent re-run — values recomputed, no duplicate rows, no errors.
- AC4: first_alerts_delivered counts only users whose FIRST alert was on day D.
- Beat entry: aggregate-business-metrics present in scheduler.beat_schedule.
"""

from __future__ import annotations

import datetime
from datetime import UTC, date, timedelta

import pytest
from sqlalchemy.orm import Session

from storage.models import Alert, BillingPayment, Subscription, User, Watchlist
from storage.models.alert_feedback import AlertFeedback
from storage.models.alerts import DELIVERY_STATUS_DELIVERED
from storage.models.channels import Channel, SourceKind
from storage.models.clusters import Cluster

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_DAY = date(2026, 1, 15)
_DAY_START = datetime.datetime(_DAY.year, _DAY.month, _DAY.day, 0, 0, 0, tzinfo=UTC)
_DAY_END = _DAY_START + timedelta(days=1)


def _embedding() -> list[float]:
    return [0.1] + [0.0] * (_EMBEDDING_DIM - 1)


def _ts(offset_hours: float = 12.0) -> datetime.datetime:
    """Return a datetime inside _DAY."""
    return _DAY_START + timedelta(hours=offset_hours)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _make_user(session: Session, email: str) -> User:
    u = User(
        email=email,
        hashed_password="x" * 16,
        created_at=_ts(1),
    )
    session.add(u)
    session.flush()
    return u


def _make_channel(session: Session, handle: str = "@test") -> Channel:
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle=handle)
    session.add(ch)
    session.flush()
    return ch


def _make_cluster(session: Session, user_id: int) -> Cluster:
    cl = Cluster(
        user_id=user_id,
        topic="test-topic",
        embedding=_embedding(),
        first_seen=_ts(),
        updated_at=_ts(),
    )
    session.add(cl)
    session.flush()
    return cl


def _make_watchlist(
    session: Session, *, user_id: int, channel_id: int, pack_slug: str = "test-pack"
) -> Watchlist:
    wl = Watchlist(
        user_id=user_id,
        channel_id=channel_id,
        topic="test",
        threshold=0.5,
        pack_slug=pack_slug,
        created_at=_ts(2),
    )
    session.add(wl)
    session.flush()
    return wl


def _make_alert(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    delivered_at: datetime.datetime | None = None,
) -> Alert:
    a = Alert(
        user_id=user_id,
        cluster_id=cluster_id,
        score=80.0,
        channels_count=1,
        first_seen=_ts(3),
        delivered_at=delivered_at,
        delivery_status=DELIVERY_STATUS_DELIVERED if delivered_at else "pending",
    )
    session.add(a)
    session.flush()
    return a


def _make_feedback(session: Session, *, user_id: int, alert_id: int) -> AlertFeedback:
    fb = AlertFeedback(
        user_id=user_id,
        alert_id=alert_id,
        verdict=1,
        created_at=_ts(4),
        updated_at=_ts(4),
    )
    session.add(fb)
    session.flush()
    return fb


def _make_payment(
    session: Session, *, user_id: int, processed_at: datetime.datetime
) -> BillingPayment:
    from decimal import Decimal

    pay = BillingPayment(
        user_id=user_id,
        order_id=f"ord-{user_id}-{int(processed_at.timestamp())}",
        plan="pro",
        period="monthly",
        amount=Decimal("29.99"),
        currency="USDT",
        status="processed",
        created_at=processed_at,
        processed_at=processed_at,
    )
    session.add(pay)
    session.flush()
    return pay


def _make_subscription(
    session: Session,
    *,
    user_id: int,
    plan: str = "pro",
    expires_at: datetime.datetime | None = None,
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        plan=plan,
        expires_at=expires_at,
        created_at=_ts(1),
        updated_at=_ts(1),
    )
    session.add(sub)
    session.flush()
    return sub


# ---------------------------------------------------------------------------
# AC2: seeded data → expected row
# ---------------------------------------------------------------------------


def test_compute_day_ac2_seeded_data(db_session: Session) -> None:
    """AC2: 2 registrations, 1 pack, 1 delivered alert, 1 feedback, 1 new_paid,
    1 churned → row matches {2,1,1,1,1,1} and active_paid is correct."""
    from analytics.aggregate import compute_day

    # 2 users registered on _DAY
    user1 = _make_user(db_session, "u1@test.com")
    user2 = _make_user(db_session, "u2@test.com")

    channel = _make_channel(db_session)

    # 1 pack attached (watchlist with pack_slug, created_at on _DAY)
    _make_watchlist(db_session, user_id=user1.id, channel_id=channel.id)

    # 1 delivered alert (first alert for user1, delivered_at on _DAY)
    cluster = _make_cluster(db_session, user1.id)
    alert = _make_alert(db_session, user_id=user1.id, cluster_id=cluster.id, delivered_at=_ts(5))

    # 1 feedback (created_at on _DAY)
    _make_feedback(db_session, user_id=user1.id, alert_id=alert.id)

    # 1 new_paid: first payment processed on _DAY for user1
    _make_payment(db_session, user_id=user1.id, processed_at=_ts(6))

    # 1 churned: subscription expires within _DAY (expires_at on _DAY), not renewed
    _make_subscription(
        db_session,
        user_id=user2.id,
        plan="pro",
        expires_at=_ts(8),  # expires on _DAY
    )

    # 1 active_paid: user1 has active subscription (expires in future)
    future = _ts(20) + timedelta(days=30)
    _make_subscription(
        db_session,
        user_id=user1.id,
        plan="pro",
        expires_at=future,
    )

    db_session.commit()

    row = compute_day(db_session, _DAY)

    assert row.day == _DAY
    assert row.registrations == 2
    assert row.packs_attached == 1
    assert row.first_alerts_delivered == 1
    assert row.first_feedback == 1
    assert row.new_paid == 1
    assert row.churned == 1
    # active_paid at end of day: user1 has active sub (expires_at > _DAY_END), user2's expired
    assert row.active_paid == 1


# ---------------------------------------------------------------------------
# AC3: idempotent re-run (upsert)
# ---------------------------------------------------------------------------


def test_upsert_row_ac3_idempotent(db_session: Session) -> None:
    """AC3: running upsert_row twice on the same day → values updated, no duplicate."""
    from analytics.aggregate import compute_day, upsert_row
    from storage.models.business_metrics import BusinessMetricsDaily

    # Seed minimal data
    _make_user(db_session, "idem@test.com")
    db_session.commit()

    # First run
    row1 = compute_day(db_session, _DAY)
    upsert_row(db_session, row1)
    db_session.commit()

    # Second run (same day)
    row2 = compute_day(db_session, _DAY)
    upsert_row(db_session, row2)
    db_session.commit()

    # Only one row in the table for _DAY
    from sqlalchemy import select

    rows = db_session.scalars(
        select(BusinessMetricsDaily).where(BusinessMetricsDaily.day == _DAY)
    ).all()
    assert len(rows) == 1
    assert rows[0].registrations == row2.registrations


# ---------------------------------------------------------------------------
# AC4: first_alerts_delivered — user's first alert counts only on its first day
# ---------------------------------------------------------------------------


def test_first_alerts_delivered_ac4_only_first_day(db_session: Session) -> None:
    """AC4: user with alerts on D1<D2 → user NOT in first_alerts_delivered for D2."""
    from analytics.aggregate import compute_day

    day_d1 = date(2026, 1, 14)
    day_d2 = date(2026, 1, 15)
    d1_ts = datetime.datetime(2026, 1, 14, 12, 0, 0, tzinfo=UTC)
    d2_ts = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

    user = _make_user(db_session, "first-alert@test.com")
    cluster1 = _make_cluster(db_session, user.id)
    cluster2 = _make_cluster(db_session, user.id)

    # First alert on D1
    _make_alert(db_session, user_id=user.id, cluster_id=cluster1.id, delivered_at=d1_ts)
    # Second alert on D2 (same user, NOT their first)
    _make_alert(db_session, user_id=user.id, cluster_id=cluster2.id, delivered_at=d2_ts)

    db_session.commit()

    row_d1 = compute_day(db_session, day_d1)
    row_d2 = compute_day(db_session, day_d2)

    # User's first alert was D1 → D1 has 1, D2 has 0
    assert row_d1.first_alerts_delivered == 1
    assert row_d2.first_alerts_delivered == 0


# ---------------------------------------------------------------------------
# Beat entry smoke test
# ---------------------------------------------------------------------------


def test_beat_schedule_has_aggregate_business_metrics_entry() -> None:
    """Beat schedule contains the aggregate-business-metrics entry."""
    from analytics.constants import AGGREGATE_BUSINESS_METRICS_TASK
    from scheduler import beat_schedule

    assert "aggregate-business-metrics" in beat_schedule
    entry = beat_schedule["aggregate-business-metrics"]
    assert entry["task"] == AGGREGATE_BUSINESS_METRICS_TASK
    assert isinstance(entry["schedule"], float)
    assert entry["schedule"] > 0
