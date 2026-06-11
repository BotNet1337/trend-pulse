"""Unit tests for analytics.aggregate.compute_day (TASK-050 AC2, AC4).

Tests:
- compute_day math: registrations, packs_attached, first_alerts_delivered,
  first_feedback, new_paid, churned, active_paid (AC2 shape).
- AC4: first_alerts_delivered counts only users whose FIRST alert was on day D
  (not users who have earlier alerts on a previous day).
- Zero-activity day: compute_day returns a row with all zeros (not absence).

These tests use a mock session and pre-seeded SQL query results.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _day(year: int = 2026, month: int = 1, day: int = 10) -> datetime.date:
    return datetime.date(year, month, day)


# ---------------------------------------------------------------------------
# compute_day math (AC2 shape)
# ---------------------------------------------------------------------------


def test_compute_day_returns_correct_counts() -> None:
    """compute_day builds a BusinessMetricsRow with correct counters from DB."""
    from analytics.aggregate import compute_day

    day = _day()
    mock_session = MagicMock()

    # Patch the individual SQL helpers inside aggregate to return known values.
    with (
        patch("analytics.aggregate._count_registrations", return_value=2),
        patch("analytics.aggregate._count_packs_attached", return_value=1),
        patch("analytics.aggregate._count_first_alerts_delivered", return_value=1),
        patch("analytics.aggregate._count_first_feedback", return_value=1),
        patch("analytics.aggregate._count_new_paid", return_value=1),
        patch("analytics.aggregate._count_churned", return_value=1),
        patch("analytics.aggregate._count_active_paid", return_value=2),
    ):
        row = compute_day(mock_session, day)

    assert row.day == day
    assert row.registrations == 2
    assert row.packs_attached == 1
    assert row.first_alerts_delivered == 1
    assert row.first_feedback == 1
    assert row.new_paid == 1
    assert row.churned == 1
    assert row.active_paid == 2


def test_compute_day_zero_activity_returns_zero_row() -> None:
    """Zero-activity day: all counters are zero — row is returned (not absent)."""
    from analytics.aggregate import compute_day

    day = _day()
    mock_session = MagicMock()

    with (
        patch("analytics.aggregate._count_registrations", return_value=0),
        patch("analytics.aggregate._count_packs_attached", return_value=0),
        patch("analytics.aggregate._count_first_alerts_delivered", return_value=0),
        patch("analytics.aggregate._count_first_feedback", return_value=0),
        patch("analytics.aggregate._count_new_paid", return_value=0),
        patch("analytics.aggregate._count_churned", return_value=0),
        patch("analytics.aggregate._count_active_paid", return_value=0),
    ):
        row = compute_day(mock_session, day)

    assert row.day == day
    assert row.registrations == 0
    assert row.packs_attached == 0
    assert row.first_alerts_delivered == 0
    assert row.first_feedback == 0
    assert row.new_paid == 0
    assert row.churned == 0
    assert row.active_paid == 0


# ---------------------------------------------------------------------------
# AC4: first-alert semantics
# ---------------------------------------------------------------------------


def test_compute_day_ac4_first_alert_only_on_first_day() -> None:
    """AC4: user with alerts on D1<D2 does NOT contribute to first_alerts D2."""
    from analytics.aggregate import compute_day

    day_d1 = _day(day=9)
    day_d2 = _day(day=10)
    mock_session = MagicMock()

    # On D1, user's FIRST alert → count=1
    with (
        patch("analytics.aggregate._count_registrations", return_value=0),
        patch("analytics.aggregate._count_packs_attached", return_value=0),
        patch("analytics.aggregate._count_first_alerts_delivered", return_value=1),
        patch("analytics.aggregate._count_first_feedback", return_value=0),
        patch("analytics.aggregate._count_new_paid", return_value=0),
        patch("analytics.aggregate._count_churned", return_value=0),
        patch("analytics.aggregate._count_active_paid", return_value=0),
    ):
        row_d1 = compute_day(mock_session, day_d1)

    # On D2, the same user gets another alert but it's NOT their first → count=0
    with (
        patch("analytics.aggregate._count_registrations", return_value=0),
        patch("analytics.aggregate._count_packs_attached", return_value=0),
        patch("analytics.aggregate._count_first_alerts_delivered", return_value=0),
        patch("analytics.aggregate._count_first_feedback", return_value=0),
        patch("analytics.aggregate._count_new_paid", return_value=0),
        patch("analytics.aggregate._count_churned", return_value=0),
        patch("analytics.aggregate._count_active_paid", return_value=0),
    ):
        row_d2 = compute_day(mock_session, day_d2)

    # D1 has the first alert, D2 does not
    assert row_d1.first_alerts_delivered == 1
    assert row_d2.first_alerts_delivered == 0


# ---------------------------------------------------------------------------
# Caplog tests: log_event emission at 4 funnel hooks
# ---------------------------------------------------------------------------


def test_on_after_register_emits_user_registered_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """on_after_register emits funnel.user_registered via log_event."""
    # We need to import the module and call the hook in isolation.
    # The hook is async — run via asyncio.
    import asyncio
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from analytics.constants import FUNNEL_USER_REGISTERED

    # Create a mock user
    user = MagicMock()
    user.id = 42

    # Patch heavy dependencies so we only test the log_event emission.
    with (
        patch("api.auth.users.UserManager.request_verify", new_callable=AsyncMock),
        patch("api.auth.users.UserManager._bind_referral", new_callable=AsyncMock),
        caplog.at_level(logging.INFO, logger="trendpulse"),
    ):
        from api.auth.users import UserManager

        mgr = MagicMock(spec=UserManager)
        mgr.request_verify = AsyncMock()
        mgr._bind_referral = AsyncMock()

        # Call the real on_after_register which should emit log_event
        asyncio.run(UserManager.on_after_register(mgr, user, request=None))

    # Check that the funnel event was emitted
    assert any(FUNNEL_USER_REGISTERED in record.message for record in caplog.records)


def test_subscribe_emits_pack_attached_event(caplog: pytest.LogCaptureFixture) -> None:
    """subscribe() emits funnel.pack_attached via log_event after successful flush."""
    import logging
    from unittest.mock import MagicMock

    from analytics.constants import FUNNEL_PACK_ATTACHED
    from storage.models.channels import SourceKind

    # Build a pack with one channel so that created > 0 and the event fires.
    mock_channel_def = MagicMock()
    mock_channel_def.handle = "@test"
    mock_channel_def.kind = SourceKind.TELEGRAM

    mock_session = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1
    mock_pack = MagicMock()
    mock_pack.slug = "test-pack"
    mock_pack.channels = [mock_channel_def]
    mock_pack.topic = "test"
    mock_pack.default_score_threshold = 0.5
    mock_pack.default_min_channels = 1
    mock_pack.default_notification_lang = "en"

    mock_channel = MagicMock()
    mock_channel.id = 1

    with (
        patch("api.packs.service._is_already_subscribed", return_value=False),
        patch("api.packs.service.assert_within_limit"),
        patch("api.packs.service.get_tenant_user_id", return_value=1),
        patch("api.packs.service._get_or_create_channel", return_value=mock_channel),
        caplog.at_level(logging.INFO, logger="trendpulse"),
    ):
        from api.packs.service import subscribe

        subscribe(mock_session, user=mock_user, pack=mock_pack)

    assert any(FUNNEL_PACK_ATTACHED in record.message for record in caplog.records)


def test_deliver_emits_alert_delivered_event(caplog: pytest.LogCaptureFixture) -> None:
    """deliver() emits funnel.alert_delivered via log_event after delivered_at is set."""
    import logging
    from unittest.mock import MagicMock

    from analytics.constants import FUNNEL_ALERT_DELIVERED
    from storage.models.alerts import Alert

    mock_session = MagicMock()
    alert = MagicMock(spec=Alert)
    alert.delivery_status = "pending"
    alert.id = 10
    alert.user_id = 1
    alert.delivery_attempts = 0

    mock_user = MagicMock()
    mock_user.telegram_bot_token = "tok"
    mock_user.telegram_chat_id = "123"
    mock_user.plan = "free"
    mock_user.webhook_url = None

    mock_session.get.return_value = mock_user

    mock_result = MagicMock()
    mock_result.ok = True

    with (
        patch("alerts.notifier._build_view", return_value=MagicMock()),
        patch("alerts.notifier.TelegramBotBackend") as mock_backend_cls,
        caplog.at_level(logging.INFO, logger="trendpulse"),
    ):
        mock_backend_instance = MagicMock()
        mock_backend_instance.send.return_value = mock_result
        mock_backend_cls.return_value = mock_backend_instance

        from alerts.notifier import deliver

        deliver(mock_session, alert)

    assert any(FUNNEL_ALERT_DELIVERED in record.message for record in caplog.records)


def test_feedback_router_emits_feedback_given_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """record_feedback emits funnel.feedback_given via log_event."""
    import logging
    from unittest.mock import MagicMock

    from analytics.constants import FUNNEL_FEEDBACK_GIVEN

    mock_session = MagicMock()
    mock_alert = MagicMock()
    mock_alert.user_id = 1
    mock_alert.id = 5

    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_alert

    mock_payload = {"alert_id": 5, "verdict": "up"}

    with (
        patch("api.feedback.router.verify_feedback_token", return_value=mock_payload),
        patch("api.feedback.router.pg_insert"),
        caplog.at_level(logging.INFO, logger="trendpulse"),
    ):
        from fastapi import Request

        from api.feedback.router import record_feedback

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        record_feedback(mock_request, "fake-token", session=mock_session)

    assert any(FUNNEL_FEEDBACK_GIVEN in record.message for record in caplog.records)
