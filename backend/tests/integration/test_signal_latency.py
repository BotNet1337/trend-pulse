"""Integration tests for signal_latency SQL-percentile logic (AC1).

Seeds alerts + posts with controlled timestamps in a live Postgres, runs
`emit_signal_latency`, and asserts:

- AC1a: exact p50/p95 for both e2e and delivery cuts.
- AC1b: window filter — alerts delivered outside the window are excluded.
- AC1c: empty window → count=0, p50/p95=None, no error.
- AC1d: negative delta (source clock skew) → clamped to 0, count_negative set.
- AC1e: cluster without posts → excluded from e2e, counted in delivery.

Requires a live Postgres with the full schema (db_session fixture).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from storage.models import Alert, Channel, Cluster, Post, User
from storage.models.alerts import DELIVERY_STATUS_DELIVERED
from storage.models.channels import SourceKind

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _embedding() -> list[float]:
    return [0.1] + [0.0] * (_EMBEDDING_DIM - 1)


def _make_settings(window_seconds: int = 7200) -> MagicMock:
    s = MagicMock()
    s.latency_window_seconds = window_seconds
    return s


def _seed_user(session: Session) -> User:
    user = User(email="latency@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user


def _seed_channel(session: Session) -> Channel:
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@latency_test")
    session.add(ch)
    session.flush()
    return ch


def _seed_cluster(session: Session, user_id: int) -> Cluster:
    cl = Cluster(
        user_id=user_id,
        topic="test-topic",
        embedding=_embedding(),
        first_seen=_BASE_TIME,
        updated_at=_BASE_TIME,
    )
    session.add(cl)
    session.flush()
    return cl


def _seed_post(
    session: Session,
    *,
    user_id: int,
    channel_id: int,
    cluster_id: int,
    external_id: str,
    posted_at: datetime,
) -> Post:
    post = Post(
        user_id=user_id,
        channel_id=channel_id,
        cluster_id=cluster_id,
        external_id=external_id,
        views=10,
        forwards=0,
        reactions=0,
        posted_at=posted_at,
        fetched_at=posted_at,
    )
    session.add(post)
    session.flush()
    return post


def _seed_alert(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    first_seen: datetime,
    delivered_at: datetime | None,
) -> Alert:
    alert = Alert(
        user_id=user_id,
        cluster_id=cluster_id,
        score=80.0,
        channels_count=1,
        first_seen=first_seen,
        delivered_at=delivered_at,
        delivery_status=DELIVERY_STATUS_DELIVERED if delivered_at else "pending",
    )
    session.add(alert)
    session.flush()
    return alert


# ---------------------------------------------------------------------------
# AC1a — exact percentiles for both cuts
# ---------------------------------------------------------------------------


def test_exact_percentiles_both_cuts(db_session: Session) -> None:
    """Given 3 delivered alerts with known timestamps, p50/p95 are correct."""
    from observability.signal_latency import emit_signal_latency

    user = _seed_user(db_session)
    channel = _seed_channel(db_session)

    # We seed 3 alerts, each with 1 post.
    # Alert 1: posted 60s before first_seen, first_seen 10s before delivered_at
    # Alert 2: posted 120s before first_seen, first_seen 20s before delivered_at
    # Alert 3: posted 300s before first_seen, first_seen 60s before delivered_at
    #
    # e2e deltas (delivered_at - min(posted_at)) = 70s, 140s, 360s
    # delivery deltas (delivered_at - first_seen) = 10s, 20s, 60s
    # p50 of [70, 140, 360] = 140 (median)
    # p95 of [70, 140, 360] ≈ 332 (interpolated)
    # p50 of [10, 20, 60] = 20
    # p95 of [10, 20, 60] ≈ 56

    now = datetime.now(UTC)
    seeds = [
        (60, 10),  # (seconds_post_before_first_seen, seconds_first_seen_before_delivered)
        (120, 20),
        (300, 60),
    ]

    for i, (post_lag, delivery_lag) in enumerate(seeds):
        cluster = _seed_cluster(db_session, user.id)
        first_seen = now - timedelta(seconds=3600 - i * 10)  # all well within window
        delivered_at = first_seen + timedelta(seconds=delivery_lag)
        posted_at = first_seen - timedelta(seconds=post_lag)

        _seed_post(
            db_session,
            user_id=user.id,
            channel_id=channel.id,
            cluster_id=cluster.id,
            external_id=f"p{i}",
            posted_at=posted_at,
        )
        _seed_alert(
            db_session,
            user_id=user.id,
            cluster_id=cluster.id,
            first_seen=first_seen,
            delivered_at=delivered_at,
        )

    db_session.commit()

    settings = _make_settings(window_seconds=7200)
    result = emit_signal_latency(db_session, settings)

    assert result["count"] == 3

    # e2e p50 should be near 140s (post_lag + delivery_lag for middle case)
    assert result["e2e_p50_s"] is not None
    assert isinstance(result["e2e_p50_s"], float)
    assert result["e2e_p50_s"] == pytest.approx(140.0, abs=2.0)

    # delivery p50 should be near 20s
    assert result["delivery_p50_s"] is not None
    assert result["delivery_p50_s"] == pytest.approx(20.0, abs=2.0)

    # exact p95 (linear interpolation): over [70, 140, 360] idx=1.9 -> 140+0.9*220=338;
    # over [10, 20, 60] idx=1.9 -> 20+0.9*40=56
    assert result["e2e_p95_s"] == pytest.approx(338.0, abs=2.0)
    assert result["delivery_p95_s"] == pytest.approx(56.0, abs=2.0)
    assert result["e2e_p95_s"] >= result["e2e_p50_s"]
    assert result["delivery_p95_s"] >= result["delivery_p50_s"]


# ---------------------------------------------------------------------------
# AC1b — window filter
# ---------------------------------------------------------------------------


def test_window_excludes_old_alerts(db_session: Session) -> None:
    """Alerts delivered outside the window are excluded from the metric."""
    from observability.signal_latency import emit_signal_latency

    user = _seed_user(db_session)
    channel = _seed_channel(db_session)

    now = datetime.now(UTC)
    # Alert 1: delivered 30 minutes ago → inside a 1-hour window
    cluster_in = _seed_cluster(db_session, user.id)
    delivered_in = now - timedelta(minutes=30)
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        cluster_id=cluster_in.id,
        external_id="in",
        posted_at=delivered_in - timedelta(seconds=60),
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_in.id,
        first_seen=delivered_in - timedelta(seconds=10),
        delivered_at=delivered_in,
    )

    # Alert 2: delivered 3 hours ago → outside a 1-hour window
    cluster_out = _seed_cluster(db_session, user.id)
    delivered_out = now - timedelta(hours=3)
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        cluster_id=cluster_out.id,
        external_id="out",
        posted_at=delivered_out - timedelta(seconds=60),
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_out.id,
        first_seen=delivered_out - timedelta(seconds=10),
        delivered_at=delivered_out,
    )

    db_session.commit()

    # 1-hour window → only the first alert is counted
    settings = _make_settings(window_seconds=3600)
    result = emit_signal_latency(db_session, settings)

    assert result["count"] == 1


# ---------------------------------------------------------------------------
# AC1c — empty window
# ---------------------------------------------------------------------------


def test_empty_window_returns_zero_count_no_error(db_session: Session) -> None:
    """No delivered alerts in the window → count=0, p50/p95=None, no exception."""
    from observability.signal_latency import emit_signal_latency

    # No alerts seeded — empty table
    db_session.commit()

    settings = _make_settings(window_seconds=3600)
    result = emit_signal_latency(db_session, settings)

    assert result["count"] == 0
    assert result["e2e_p50_s"] is None
    assert result["e2e_p95_s"] is None
    assert result["delivery_p50_s"] is None
    assert result["delivery_p95_s"] is None


# ---------------------------------------------------------------------------
# AC1d — negative delta clamped to 0
# ---------------------------------------------------------------------------


def test_negative_delta_clamped_and_reported(db_session: Session) -> None:
    """Alert where posted_at > delivered_at (clock skew) → delta clamped to 0."""
    from observability.signal_latency import emit_signal_latency

    user = _seed_user(db_session)
    channel = _seed_channel(db_session)

    now = datetime.now(UTC)
    cluster = _seed_cluster(db_session, user.id)
    delivered_at = now - timedelta(minutes=5)
    # Post has a future posted_at (clock skew) → e2e delta would be negative
    posted_at = delivered_at + timedelta(seconds=30)  # after delivered_at

    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        cluster_id=cluster.id,
        external_id="skewed",
        posted_at=posted_at,
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster.id,
        first_seen=delivered_at - timedelta(seconds=5),
        delivered_at=delivered_at,
    )
    db_session.commit()

    settings = _make_settings(window_seconds=7200)
    result = emit_signal_latency(db_session, settings)

    assert result["count"] == 1
    # e2e clamped to 0 (not negative)
    assert result["e2e_p50_s"] is not None
    assert result["e2e_p50_s"] >= 0.0
    # count_negative must be reported
    assert result["count_negative"] >= 1


# ---------------------------------------------------------------------------
# AC1e — cluster without posts excluded from e2e, counted in delivery
# ---------------------------------------------------------------------------


def test_cluster_without_posts_excluded_from_e2e(db_session: Session) -> None:
    """Alert for a cluster with no posts: excluded from e2e, present in delivery."""
    from observability.signal_latency import emit_signal_latency

    user = _seed_user(db_session)
    channel = _seed_channel(db_session)

    now = datetime.now(UTC)

    # Alert 1: has a post → counted in both e2e and delivery
    cluster_with_post = _seed_cluster(db_session, user.id)
    delivered1 = now - timedelta(minutes=10)
    _seed_post(
        db_session,
        user_id=user.id,
        channel_id=channel.id,
        cluster_id=cluster_with_post.id,
        external_id="has_post",
        posted_at=delivered1 - timedelta(seconds=120),
    )
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_with_post.id,
        first_seen=delivered1 - timedelta(seconds=30),
        delivered_at=delivered1,
    )

    # Alert 2: cluster has NO posts → excluded from e2e, still in delivery
    cluster_no_post = _seed_cluster(db_session, user.id)
    delivered2 = now - timedelta(minutes=5)
    _seed_alert(
        db_session,
        user_id=user.id,
        cluster_id=cluster_no_post.id,
        first_seen=delivered2 - timedelta(seconds=15),
        delivered_at=delivered2,
    )

    db_session.commit()

    settings = _make_settings(window_seconds=7200)
    result = emit_signal_latency(db_session, settings)

    # delivery cut counts both alerts
    assert result["count"] == 2
    assert result["delivery_p50_s"] is not None

    # e2e result is not None (1 alert with post contributes)
    assert result["e2e_p50_s"] is not None
