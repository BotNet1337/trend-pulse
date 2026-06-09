"""Integration tests — reliability: pending-sweep + Celery /ready + alerts-by-status.

Seeds alerts in a live Postgres, exercises `_resweep_pending_alerts`, and asserts:

- AC1: stale `pending` alert (older than grace) is re-enqueued via
  `dispatch_alert.apply_async`; fresh `pending` (<grace) is NOT touched.
- AC2: `delivered`/`failed` alerts are never re-enqueued (idempotency invariant).
- AC4: `emit_alerts_by_status` returns correct counts for seeded statuses.

AC3 (`/ready` Celery check) is covered in `tests/unit/test_ready.py` via
monkeypatching; no live Celery worker is required for integration here.

The whole module is `integration`-marked and requires a live Postgres (via
`db_session` from `conftest.py`).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from storage.models import Alert, Cluster, User
from storage.models.alerts import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
)

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_NOW = datetime.now(UTC)
_GRACE_SECONDS = 300  # mirrors _DEFAULT_PENDING_RESWEEP_GRACE_SECONDS


def _embedding() -> list[float]:
    return [0.1] + [0.0] * (_EMBEDDING_DIM - 1)


def _seed_user(session: Session, email: str) -> User:
    user = User(email=email, hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user


def _seed_cluster(session: Session, *, user_id: int) -> Cluster:
    cluster = Cluster(
        user_id=user_id,
        topic="test_topic",
        embedding=_embedding(),
        first_seen=_NOW,
        updated_at=_NOW,
    )
    session.add(cluster)
    session.flush()
    return cluster


def _seed_alert(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    status: str,
    age_seconds: int,
) -> Alert:
    """Seed an alert with `first_seen` set to `age_seconds` ago."""
    alert = Alert(
        user_id=user_id,
        cluster_id=cluster_id,
        score=0.9,
        channels_count=1,
        delivery_status=status,
        first_seen=_NOW - timedelta(seconds=age_seconds),
    )
    session.add(alert)
    session.flush()
    return alert


# ---------------------------------------------------------------------------
# AC1 — stale pending is re-enqueued; fresh pending is not
# ---------------------------------------------------------------------------


def test_resweep_redelivers_stale_pending(db_session: Session) -> None:
    """Stale pending (>grace) is re-enqueued; fresh pending (<grace) is skipped."""
    from alerts.tasks import _resweep_pending_alerts

    user = _seed_user(db_session, "stale@example.com")
    cluster_stale = _seed_cluster(db_session, user_id=user.id)
    cluster_fresh = _seed_cluster(db_session, user_id=user.id)

    # Stale: first_seen is older than grace (grace + 60 extra seconds).
    stale_alert = _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_stale.id,
        status=DELIVERY_STATUS_PENDING,
        age_seconds=_GRACE_SECONDS + 60,
    )
    # Fresh: first_seen is within grace (60 seconds ago).
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_fresh.id,
        status=DELIVERY_STATUS_PENDING,
        age_seconds=60,
    )
    db_session.commit()

    with patch("alerts.tasks.dispatch_alert") as mock_dispatch:
        count = _resweep_pending_alerts()

    # Only the stale alert was re-enqueued.
    assert count == 1
    mock_dispatch.apply_async.assert_called_once_with(args=(stale_alert.id,))


# ---------------------------------------------------------------------------
# AC2 — delivered/failed are never re-enqueued
# ---------------------------------------------------------------------------


def test_resweep_skips_delivered_and_failed(db_session: Session) -> None:
    """delivered and failed alerts are never re-enqueued regardless of age."""
    from alerts.tasks import _resweep_pending_alerts

    user = _seed_user(db_session, "terminal@example.com")
    cluster_delivered = _seed_cluster(db_session, user_id=user.id)
    cluster_failed = _seed_cluster(db_session, user_id=user.id)

    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_delivered.id,
        status=DELIVERY_STATUS_DELIVERED,
        age_seconds=_GRACE_SECONDS + 3600,
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_failed.id,
        status=DELIVERY_STATUS_FAILED,
        age_seconds=_GRACE_SECONDS + 3600,
    )
    db_session.commit()

    with patch("alerts.tasks.dispatch_alert") as mock_dispatch:
        count = _resweep_pending_alerts()

    assert count == 0
    mock_dispatch.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# AC4 — emit_alerts_by_status returns correct counts
# ---------------------------------------------------------------------------


def test_alerts_by_status_counts(db_session: Session) -> None:
    """emit_alerts_by_status returns zero-filled counts for all statuses."""
    from observability.alert_status import emit_alerts_by_status

    user = _seed_user(db_session, "counts@example.com")
    c1 = _seed_cluster(db_session, user_id=user.id)
    c2 = _seed_cluster(db_session, user_id=user.id)
    c3 = _seed_cluster(db_session, user_id=user.id)

    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=c1.id,
        status=DELIVERY_STATUS_PENDING,
        age_seconds=10,
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=c2.id,
        status=DELIVERY_STATUS_DELIVERED,
        age_seconds=10,
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=c3.id,
        status=DELIVERY_STATUS_FAILED,
        age_seconds=10,
    )
    db_session.commit()

    counts = emit_alerts_by_status(db_session)

    assert counts[DELIVERY_STATUS_PENDING] == 1
    assert counts[DELIVERY_STATUS_DELIVERED] == 1
    assert counts[DELIVERY_STATUS_FAILED] == 1


def test_alerts_by_status_empty_table_returns_zeros(db_session: Session) -> None:
    """emit_alerts_by_status returns all-zero counts when no alerts exist."""
    from observability.alert_status import emit_alerts_by_status

    counts = emit_alerts_by_status(db_session)

    assert counts[DELIVERY_STATUS_PENDING] == 0
    assert counts[DELIVERY_STATUS_DELIVERED] == 0
    assert counts[DELIVERY_STATUS_FAILED] == 0
