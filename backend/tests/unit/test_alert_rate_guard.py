"""Unit tests for scorer alert guards (TASK-043).

AC4: rate-guard — N alerts already in sliding 1h window → skip + log_event("alert_rate_limited").
AC5: group-guard — same (user, topic) in window → skip + log_event("alert_group_limited").

Guards are tested with a mock session (no live DB needed for unit). The guards
gate CREATION of new alerts; idempotency / deliver_after semantics are unaffected.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    alerts_per_hour_limit: int = 6,
    alert_group_window_seconds: int = 1800,
) -> MagicMock:
    s = MagicMock()
    s.alerts_per_hour_limit = alerts_per_hour_limit
    s.alert_group_window_seconds = alert_group_window_seconds
    return s


def _mock_cluster(cluster_id: int = 1, topic: str = "crypto") -> MagicMock:
    cl = MagicMock()
    cl.id = cluster_id
    cl.topic = topic
    return cl


# ---------------------------------------------------------------------------
# AC4 — rate-guard: at limit → skip
# ---------------------------------------------------------------------------


class TestRateGuard:
    """check_rate_guard(session, user_id, settings) → True = skip, False = allow."""

    def test_under_limit_allows(self) -> None:
        """5 alerts in window, limit=6 → allowed (not at limit)."""
        from scorer.tasks import check_rate_guard

        session = MagicMock()
        # scalar() returns the count of recent alerts
        session.scalar.return_value = 5

        settings = _make_settings(alerts_per_hour_limit=6)
        should_skip = check_rate_guard(session, user_id=1, settings=settings)
        assert should_skip is False

    def test_at_limit_skips(self) -> None:
        """6 alerts in window, limit=6 → skip."""
        from scorer.tasks import check_rate_guard

        session = MagicMock()
        session.scalar.return_value = 6

        settings = _make_settings(alerts_per_hour_limit=6)
        with patch("scorer.tasks.log_event") as mock_log:
            should_skip = check_rate_guard(session, user_id=1, settings=settings)

        assert should_skip is True
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        assert call_kwargs[0][0] == "alert_rate_limited"
        assert call_kwargs[1]["user_id"] == 1

    def test_over_limit_skips(self) -> None:
        """10 alerts in window, limit=6 → skip."""
        from scorer.tasks import check_rate_guard

        session = MagicMock()
        session.scalar.return_value = 10

        settings = _make_settings(alerts_per_hour_limit=6)
        with patch("scorer.tasks.log_event") as mock_log:
            should_skip = check_rate_guard(session, user_id=1, settings=settings)

        assert should_skip is True
        mock_log.assert_called_once()

    def test_zero_alerts_allows(self) -> None:
        """No alerts in window → allowed."""
        from scorer.tasks import check_rate_guard

        session = MagicMock()
        session.scalar.return_value = 0

        settings = _make_settings(alerts_per_hour_limit=6)
        should_skip = check_rate_guard(session, user_id=2, settings=settings)
        assert should_skip is False

    def test_rate_guard_logs_count_and_limit(self) -> None:
        """log_event must include count and limit for observability."""
        from scorer.tasks import check_rate_guard

        session = MagicMock()
        session.scalar.return_value = 7

        settings = _make_settings(alerts_per_hour_limit=6)
        with patch("scorer.tasks.log_event") as mock_log:
            check_rate_guard(session, user_id=42, settings=settings)

        call_kwargs = mock_log.call_args
        assert call_kwargs[1]["count"] == 7
        assert call_kwargs[1]["limit"] == 6


# ---------------------------------------------------------------------------
# AC5 — group-guard: same (user, topic) in window → skip
# ---------------------------------------------------------------------------


class TestGroupGuard:
    """check_group_guard(session, user_id, cluster, settings) → True = skip, False = allow."""

    def test_no_recent_alert_same_topic_allows(self) -> None:
        """No recent alert for same topic in group window → allowed."""
        from scorer.tasks import check_group_guard

        session = MagicMock()
        session.scalar.return_value = None  # no existing alert id

        settings = _make_settings(alert_group_window_seconds=1800)
        cluster = _mock_cluster(cluster_id=10, topic="crypto")
        should_skip = check_group_guard(session, user_id=1, cluster=cluster, settings=settings)
        assert should_skip is False

    def test_recent_alert_same_topic_skips(self) -> None:
        """Existing alert for same topic in group window → skip."""
        from scorer.tasks import check_group_guard

        session = MagicMock()
        session.scalar.return_value = 99  # existing alert id

        settings = _make_settings(alert_group_window_seconds=1800)
        cluster = _mock_cluster(cluster_id=20, topic="crypto")
        with patch("scorer.tasks.log_event") as mock_log:
            should_skip = check_group_guard(session, user_id=1, cluster=cluster, settings=settings)

        assert should_skip is True
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        assert call_kwargs[0][0] == "alert_group_limited"
        assert call_kwargs[1]["user_id"] == 1
        assert call_kwargs[1]["cluster_id"] == 20

    def test_group_guard_does_not_include_raw_topic_string(self) -> None:
        """log_event must not include topic string (raw content invariant — TASK-039 learnings).

        Only cluster_id (int) should identify the cluster in logs, not the topic string.
        """
        from scorer.tasks import check_group_guard

        session = MagicMock()
        session.scalar.return_value = 99

        settings = _make_settings(alert_group_window_seconds=1800)
        cluster = _mock_cluster(cluster_id=33, topic="some raw topic text")
        with patch("scorer.tasks.log_event") as mock_log:
            check_group_guard(session, user_id=5, cluster=cluster, settings=settings)

        call_kwargs = mock_log.call_args
        logged_fields = call_kwargs[1]
        # Must not leak topic string to logs.
        assert "topic" not in logged_fields, "topic string must not appear in log_event fields"
        # Must include cluster_id (int).
        assert "cluster_id" in logged_fields

    def test_different_topic_allows(self) -> None:
        """Alert exists but for different topic → not blocked by group-guard."""
        from scorer.tasks import check_group_guard

        session = MagicMock()
        # No alert for THIS cluster's topic (query returns None).
        session.scalar.return_value = None

        settings = _make_settings(alert_group_window_seconds=1800)
        cluster = _mock_cluster(cluster_id=50, topic="sports")
        should_skip = check_group_guard(session, user_id=1, cluster=cluster, settings=settings)
        assert should_skip is False


# ---------------------------------------------------------------------------
# Guard ordering: rate-guard BEFORE group-guard BEFORE _create_alert_idempotent
# ---------------------------------------------------------------------------


class TestGuardOrdering:
    """Guards must fire before _create_alert_idempotent — verified by integration."""

    def test_rate_guard_prevents_creation(self) -> None:
        """rate-guard skip → _score_user returns no new alert for that cluster."""
        # We verify that when check_rate_guard returns True, _create_alert_idempotent
        # is NOT called. This is a contract test for the guard ordering.
        from unittest.mock import patch

        from scorer.tasks import _TopicConfig

        session = MagicMock()
        topic_config = _TopicConfig(threshold=0.0, channel_ids=frozenset([1]))

        with (
            patch("scorer.tasks.check_rate_guard", return_value=True) as mock_rg,
            patch("scorer.tasks._create_alert_idempotent") as mock_create,
        ):
            from scorer.tasks import _score_user

            # Minimal setup to get past early returns. The cluster's channel set
            # (TASK-084: matching is by channel overlap) must intersect the topic's
            # watched channels ({1}) so matching succeeds and we reach the guards.
            with (
                patch("scorer.tasks._topic_configs", return_value={"crypto": topic_config}),
                patch("scorer.tasks._resolve_deliver_after", return_value=None),
                patch(
                    "scorer.tasks._recent_clusters",
                    return_value=[_mock_cluster(cluster_id=1, topic="crypto")],
                ),
                patch(
                    "scorer.tasks._cluster_channel_ids",
                    return_value=frozenset([1]),
                ),
                patch(
                    "scorer.tasks._build_score_inputs",
                    return_value=MagicMock(unique_channels_count=1),
                ),
                patch("scorer.tasks._persist_score", return_value=999.0),
            ):
                from datetime import UTC, datetime

                _score_user(
                    session,
                    user_id=1,
                    window_start=datetime.now(UTC),
                )

            # rate guard was checked
            assert mock_rg.called
            # create was NOT called due to rate guard
            mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: rate-guard + group-guard in live scorer (marked integration)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_rate_guard_integration(db_session: Any) -> None:
    """AC4 integration: N alerts in 1h window → additional cluster does not create alert."""

    from sqlalchemy.orm import Session

    from storage.models import Alert, Cluster, User, Watchlist
    from storage.models.channels import Channel, SourceKind

    session: Session = db_session

    user = User(email="rguard@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@rguard1")
    session.add(ch)
    session.flush()
    # Low threshold → would normally alert on everything
    session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="crypto", threshold=0.0))
    session.flush()

    now = datetime.now(UTC)
    _EMBEDDING_DIM = 384

    # Pre-create 6 alerts within the last hour (saturate the rate limit)
    for _ in range(6):
        cl = Cluster(
            user_id=user.id,
            topic="crypto",
            embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
            first_seen=now,
            updated_at=now,
        )
        session.add(cl)
        session.flush()
        alert = Alert(
            user_id=user.id,
            cluster_id=cl.id,
            score=99.0,
            channels_count=1,
            first_seen=now,
        )
        session.add(alert)

    # One MORE cluster — should be blocked by rate-guard.
    new_cluster = Cluster(
        user_id=user.id,
        topic="crypto",
        embedding=[0.2] + [0.0] * (_EMBEDDING_DIM - 1),
        first_seen=now,
        updated_at=now,
    )
    session.add(new_cluster)
    session.flush()

    # Seed a post so scorer can compute a score
    from storage.models.posts import Post

    session.add(
        Post(
            user_id=user.id,
            channel_id=ch.id,
            external_id="rg_post1",
            views=50000,
            forwards=2000,
            reactions=5000,
            posted_at=now,
            cluster_id=new_cluster.id,
        )
    )
    session.commit()

    from scorer.tasks import score_recent_clusters

    # Run scorer — the new cluster should NOT produce an alert (rate limited).
    score_recent_clusters()

    session.expire_all()
    from sqlalchemy import select

    new_alert = session.scalar(
        select(Alert).where(
            Alert.user_id == user.id,
            Alert.cluster_id == new_cluster.id,
        )
    )
    assert new_alert is None, "Rate guard should have blocked alert creation"


@pytest.mark.integration
def test_group_guard_integration(db_session: Any) -> None:
    """AC5 integration: two clusters same topic in group window → only first alert created."""

    from sqlalchemy.orm import Session

    from storage.models import Alert, Cluster, User, Watchlist
    from storage.models.channels import Channel, SourceKind
    from storage.models.posts import Post

    session: Session = db_session

    user = User(email="gguard@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@gguard1")
    session.add(ch)
    session.flush()
    # Low threshold, high rate limit (won't be hit with 2 alerts)
    session.add(Watchlist(user_id=user.id, channel_id=ch.id, topic="sports", threshold=0.0))
    session.flush()

    now = datetime.now(UTC)
    _EMBEDDING_DIM = 384

    # Two clusters, same topic "sports", both fresh
    cluster1 = Cluster(
        user_id=user.id,
        topic="sports",
        embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
        first_seen=now,
        updated_at=now,
    )
    cluster2 = Cluster(
        user_id=user.id,
        topic="sports",
        embedding=[0.15] + [0.0] * (_EMBEDDING_DIM - 1),
        first_seen=now,
        updated_at=now,
    )
    session.add(cluster1)
    session.add(cluster2)
    session.flush()

    # Seed posts for both clusters (high engagement to clear threshold)
    for cl in [cluster1, cluster2]:
        session.add(
            Post(
                user_id=user.id,
                channel_id=ch.id,
                external_id=f"gg_post_{cl.id}",
                views=50000,
                forwards=2000,
                reactions=5000,
                posted_at=now,
                cluster_id=cl.id,
            )
        )

    session.commit()

    from scorer.tasks import score_recent_clusters

    score_recent_clusters()

    session.expire_all()
    from sqlalchemy import select

    alerts = session.scalars(select(Alert).where(Alert.user_id == user.id)).all()
    # Only 1 alert should exist (group-guard blocked the second)
    assert len(alerts) == 1, (
        f"Group guard should have blocked second same-topic alert; got {len(alerts)} alerts"
    )
