"""Unit tests for renewal-window selection logic and idempotency (task-027).

Pure logic tests — no DB, no Celery, no external services.  Tests are
intentionally structured so they run under `make ci-fast` (no `integration`
marker needed).

Covers:
- `_current_window`: days_left → tightest window or None.
- Idempotency gating: last_reminder_window determines whether to send.
- Window reset on renewal (days_left > max(RENEWAL_REMINDER_DAYS)).
- Tenant-scope invariant: send target is always the subscription's owner.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from billing.constants import RENEWAL_REMINDER_DAYS
from billing.tasks import _current_window

# ---------------------------------------------------------------------------
# _current_window — pure logic
# ---------------------------------------------------------------------------


class TestCurrentWindow:
    """Verify the tightest-window selection function."""

    def test_exactly_at_1_day(self) -> None:
        assert _current_window(1.0) == 1

    def test_under_1_day(self) -> None:
        assert _current_window(0.5) == 1

    def test_at_3_days(self) -> None:
        assert _current_window(3.0) == 3

    def test_between_1_and_3(self) -> None:
        # days_left=2 → satisfies both w=3 and w=7; tightest is w=3
        assert _current_window(2.0) == 3

    def test_at_7_days(self) -> None:
        assert _current_window(7.0) == 7

    def test_between_3_and_7(self) -> None:
        # days_left=5 → satisfies w=7 only; tightest is w=7
        assert _current_window(5.0) == 7

    def test_outside_all_windows(self) -> None:
        # days_left=10 → no window applies → None
        assert _current_window(10.0) is None

    def test_far_future(self) -> None:
        assert _current_window(30.0) is None

    def test_just_over_7(self) -> None:
        # 7.01 days → outside all windows
        assert _current_window(7.01) is None

    def test_just_under_7(self) -> None:
        # 6.99 days → window 7
        assert _current_window(6.99) == 7

    @pytest.mark.parametrize(
        ("days_left", "expected"),
        [
            (7.0, 7),
            (6.0, 7),
            (3.0, 3),
            (2.0, 3),
            (1.0, 1),
            (0.1, 1),
            (8.0, None),
            (100.0, None),
        ],
    )
    def test_parametrize_window_mapping(self, days_left: float, expected: int | None) -> None:
        assert _current_window(days_left) == expected


# ---------------------------------------------------------------------------
# Idempotency logic (via _check_expiring_subscriptions with mocked DB)
# ---------------------------------------------------------------------------


def _make_mock_subscription(
    *,
    days_ahead: float,
    plan: str = "pro",
    last_reminder_window: int | None = None,
    sub_id: int = 1,
    user_id: int = 1,
) -> MagicMock:
    """Build a minimal mock Subscription with the required attributes."""
    now = datetime.now(UTC)
    sub = MagicMock(name=f"Subscription(id={sub_id})")
    sub.id = sub_id
    sub.user_id = user_id
    sub.plan = plan
    sub.expires_at = now + timedelta(days=days_ahead)
    sub.last_reminder_window = last_reminder_window
    return sub


def _make_mock_user(*, user_id: int = 1, email: str = "user@example.com") -> MagicMock:
    user = MagicMock(name=f"User(id={user_id})")
    user.id = user_id
    user.email = email
    return user


class TestIdempotency:
    """Verify the skip-if-already-sent gating logic."""

    def _run_with_rows(
        self,
        rows: list[tuple[MagicMock, MagicMock]],
    ) -> tuple[int, list[MagicMock]]:
        """Run _check_expiring_subscriptions with mocked DB rows.

        Returns (sent_count, list_of_send_calls).
        """
        from billing.tasks import _check_expiring_subscriptions

        mock_session = MagicMock(name="session")
        mock_session.execute.return_value.unique.return_value.all.return_value = rows

        sent_calls: list[MagicMock] = []

        def fake_get_session():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                yield mock_session

            return _ctx()

        with (
            patch("billing.tasks.get_session", fake_get_session),
            patch("billing.tasks.send_renewal_reminder") as mock_send,
        ):
            count = _check_expiring_subscriptions()
            sent_calls = mock_send.call_args_list

        return count, sent_calls

    def test_sends_when_no_previous_reminder(self) -> None:
        """last_reminder_window=None → should send (window=3)."""
        sub = _make_mock_subscription(days_ahead=3.0, last_reminder_window=None)
        user = _make_mock_user()
        count, calls = self._run_with_rows([(sub, user)])
        assert count == 1
        assert len(calls) == 1

    def test_skips_when_already_sent_same_window(self) -> None:
        """last_reminder_window=3 and current_window=3 → skip (already sent)."""
        sub = _make_mock_subscription(days_ahead=3.0, last_reminder_window=3)
        user = _make_mock_user()
        count, calls = self._run_with_rows([(sub, user)])
        assert count == 0
        assert len(calls) == 0

    def test_sends_when_tighter_window_reached(self) -> None:
        """last_reminder_window=7, days_left=3 → current_window=3 < 7 → send."""
        sub = _make_mock_subscription(days_ahead=3.0, last_reminder_window=7)
        user = _make_mock_user()
        count, calls = self._run_with_rows([(sub, user)])
        assert count == 1
        assert len(calls) == 1

    def test_skips_when_days_left_still_at_7_window_already_sent(self) -> None:
        """last_reminder_window=7, days_left=6.5 → current_window=7 == 7 → skip."""
        sub = _make_mock_subscription(days_ahead=6.5, last_reminder_window=7)
        user = _make_mock_user()
        count, _calls = self._run_with_rows([(sub, user)])
        assert count == 0

    def test_sets_window_on_success(self) -> None:
        """After successful send, last_reminder_window is set to current_window."""
        sub = _make_mock_subscription(days_ahead=3.0, last_reminder_window=None)
        user = _make_mock_user()
        self._run_with_rows([(sub, user)])
        assert sub.last_reminder_window == 3

    def test_does_not_set_window_on_failure(self) -> None:
        """If send_renewal_reminder raises, last_reminder_window stays None."""
        from billing.tasks import _check_expiring_subscriptions as _check

        sub = _make_mock_subscription(days_ahead=3.0, last_reminder_window=None)
        user = _make_mock_user()

        mock_session = MagicMock(name="session")
        mock_session.execute.return_value.unique.return_value.all.return_value = [(sub, user)]

        def fake_get_session():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                yield mock_session

            return _ctx()

        with (
            patch("billing.tasks.get_session", fake_get_session),
            patch("billing.tasks.send_renewal_reminder", side_effect=RuntimeError("smtp down")),
        ):
            count = _check()

        assert count == 0
        # Flag must NOT be set — retry on next tick
        assert sub.last_reminder_window is None


# ---------------------------------------------------------------------------
# Tenant-scope invariant
# ---------------------------------------------------------------------------


class TestTenantScope:
    """Each notification must target the subscription's owner."""

    def test_each_user_gets_own_email(self) -> None:
        """Two subs → two sends, each to the correct owner."""
        sub1 = _make_mock_subscription(days_ahead=1.0, sub_id=1, user_id=1)
        user1 = _make_mock_user(user_id=1, email="user1@example.com")
        sub2 = _make_mock_subscription(days_ahead=3.0, sub_id=2, user_id=2)
        user2 = _make_mock_user(user_id=2, email="user2@example.com")

        mock_session = MagicMock(name="session")
        mock_session.execute.return_value.unique.return_value.all.return_value = [
            (sub1, user1),
            (sub2, user2),
        ]

        calls: list[dict[str, object]] = []

        def capture(*args: object, **kwargs: object) -> None:
            calls.append({"user": kwargs.get("user") or args[1]})

        def fake_get_session():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                yield mock_session

            return _ctx()

        from billing.tasks import _check_expiring_subscriptions

        with (
            patch("billing.tasks.get_session", fake_get_session),
            patch("billing.tasks.send_renewal_reminder", side_effect=capture),
        ):
            count = _check_expiring_subscriptions()

        assert count == 2
        assert calls[0]["user"] is user1
        assert calls[1]["user"] is user2


# ---------------------------------------------------------------------------
# Window reset on renewal (days_left > max(windows))
# ---------------------------------------------------------------------------


class TestRenewalReApproach:
    """After a renewal, a widened window re-triggers reminders (no explicit reset).

    Within one paid period windows only narrow (7→3→1); a renewed period re-enters
    at a WIDER window than the last sent (e.g. 7 vs a stale 1), and the `==`-gate
    fires a fresh reminder because 7 != 1 — no explicit reset branch is needed.
    """

    def test_renewed_period_resends_at_wider_window(self) -> None:
        """Stale last_reminder_window=1 (prev period); now near-expiry of a renewed
        period at window 7 → reminder sent again, flag becomes 7."""
        # days_ahead=5 → current_window=7 (5<=7), which differs from the stale last=1.
        sub = _make_mock_subscription(days_ahead=5.0, last_reminder_window=1)
        user = _make_mock_user()

        mock_session = MagicMock(name="session")
        mock_session.execute.return_value.unique.return_value.all.return_value = [(sub, user)]

        def fake_get_session():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                yield mock_session

            return _ctx()

        from billing.tasks import _check_expiring_subscriptions

        with (
            patch("billing.tasks.get_session", fake_get_session),
            patch("billing.tasks.send_renewal_reminder") as mock_send,
        ):
            count = _check_expiring_subscriptions()

        assert count == 1
        mock_send.assert_called_once()
        assert sub.last_reminder_window == 7


# ---------------------------------------------------------------------------
# RENEWAL_REMINDER_DAYS constant — named, ordered
# ---------------------------------------------------------------------------


def test_renewal_reminder_days_constant() -> None:
    """RENEWAL_REMINDER_DAYS must be (7, 3, 1) — named constant, no magic literals."""
    assert RENEWAL_REMINDER_DAYS == (7, 3, 1)
    assert len(RENEWAL_REMINDER_DAYS) == 3
    assert all(isinstance(d, int) for d in RENEWAL_REMINDER_DAYS)
