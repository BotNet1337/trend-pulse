"""TASK-040 — Free-plan alert delay: failing tests (RED anchor).

Tests cover AC1-AC4 purely in-process; no Postgres required (mock-time, mocked
session, mocked apply_async).

AC1 — Free user → deliver_after ≈ now+delay, apply_async countdown≈delay;
       Pro/Team → deliver_after NULL, no countdown.
AC2 — dispatch called with deliver_after in future → no delivery, task
       rescheduled with countdown=remaining, status stays pending, attempts NOT
       incremented.
AC3 — resweep skips pending alerts with future deliver_after; re-enqueues once
       deliver_after has passed.
AC4 — expired Pro subscription (effective_plan→FREE) → delayed like Free.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DELAY = 1800  # seconds — mirrors default free_alert_delay_seconds


def _utc(ts: datetime) -> datetime:
    """Ensure tz-aware (UTC)."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def _make_settings(delay: int = _DELAY) -> MagicMock:
    s = MagicMock(name="settings")
    s.free_alert_delay_seconds = delay
    s.pending_resweep_grace_seconds = 300
    s.pending_resweep_max_batch = 500
    s.scorer_recent_window_seconds = 3600
    # ML serving OFF (TASK-125) so `_load_viral_model` returns None without attempting a
    # load — these delivery tests exercise the formula-only scorer path.
    s.scorer_model_enabled = False
    s.scorer_model_path = ""
    return s


def _make_session(rows: list[int]) -> MagicMock:
    """Session whose execute().scalars().all() returns rows (for resweep)."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    session = MagicMock()
    session.execute.return_value = result
    return session


def _get_session_cm(session: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# AC1 — scorer trigger sets deliver_after for Free, NULL for Pro/Team
# ---------------------------------------------------------------------------


class TestAC1ScorerDeliver:
    """AC1: Free → deliver_after set + countdown; Pro/Team → NULL, immediate."""

    def test_free_alert_created_with_deliver_after_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_create_alert_idempotent called with deliver_after≈now+delay for Free user."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        monkeypatch.setattr(scorer_tasks, "get_settings", lambda: _make_settings(_DELAY))
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.FREE))

        capture: dict[str, object] = {}

        def _fake_create(
            session: object,
            *,
            user_id: int,
            cluster: object,
            score: float,
            channels_count: int,
            deliver_after: datetime | None = None,
        ) -> int:
            capture["deliver_after"] = deliver_after
            return 99

        monkeypatch.setattr(scorer_tasks, "_create_alert_idempotent", _fake_create)

        apply_calls: list[dict] = []

        def _fake_enqueue(alert_id: int, *, countdown: int | None = None) -> None:
            apply_calls.append({"alert_id": alert_id, "countdown": countdown})

        monkeypatch.setattr(scorer_tasks, "_enqueue_delivery", _fake_enqueue)

        # _fake_score_user returns tuples (alert_id, countdown) matching new signature.
        def _fake_score_user(
            sess: object,
            *,
            user_id: int,
            window_start: datetime,
            gbdt: object | None = None,
        ) -> list[tuple[int, int | None]]:
            da = now_fixed + timedelta(seconds=_DELAY)
            _fake_create(
                sess,
                user_id=user_id,
                cluster=MagicMock(id=7, topic="x", first_seen=now_fixed),
                score=0.9,
                channels_count=2,
                deliver_after=da,
            )
            return [(99, _DELAY)]

        monkeypatch.setattr(scorer_tasks, "_score_user", _fake_score_user)
        monkeypatch.setattr(scorer_tasks, "list_active_user_ids", lambda s: [1])

        with patch("scorer.tasks.get_session") as mock_gs:
            mock_gs.return_value = _get_session_cm(MagicMock())
            scorer_tasks.score_recent_clusters()

        expected = now_fixed + timedelta(seconds=_DELAY)
        assert capture["deliver_after"] == expected
        # apply_async must have been called with countdown.
        assert len(apply_calls) == 1
        assert apply_calls[0]["countdown"] == pytest.approx(_DELAY, abs=5)

    def test_pro_user_no_deliver_after_no_countdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pro user: deliver_after=None (NULL), no countdown on apply_async."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        monkeypatch.setattr(scorer_tasks, "get_settings", lambda: _make_settings(_DELAY))
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.PRO))

        capture: dict[str, object] = {}

        def _fake_create(
            session: object,
            *,
            user_id: int,
            cluster: object,
            score: float,
            channels_count: int,
            deliver_after: datetime | None = None,
        ) -> int:
            capture["deliver_after"] = deliver_after
            return 55

        monkeypatch.setattr(scorer_tasks, "_create_alert_idempotent", _fake_create)

        apply_calls: list[dict] = []

        def _fake_enqueue(alert_id: int, *, countdown: int | None = None) -> None:
            apply_calls.append({"countdown": countdown})

        monkeypatch.setattr(scorer_tasks, "_enqueue_delivery", _fake_enqueue)

        def _fake_score_user(
            sess: object,
            *,
            user_id: int,
            window_start: datetime,
            gbdt: object | None = None,
        ) -> list[tuple[int, int | None]]:
            _fake_create(
                sess,
                user_id=user_id,
                cluster=MagicMock(id=8, topic="y", first_seen=now_fixed),
                score=0.9,
                channels_count=2,
                deliver_after=None,
            )
            return [(55, None)]  # Pro → no countdown

        monkeypatch.setattr(scorer_tasks, "_score_user", _fake_score_user)
        monkeypatch.setattr(scorer_tasks, "list_active_user_ids", lambda s: [2])

        with patch("scorer.tasks.get_session") as mock_gs:
            mock_gs.return_value = _get_session_cm(MagicMock())
            scorer_tasks.score_recent_clusters()

        # deliver_after must be NULL for Pro.
        assert capture.get("deliver_after") is None
        # countdown must be None (immediate dispatch).
        assert len(apply_calls) == 1
        assert apply_calls[0]["countdown"] is None

    def test_resolve_deliver_after_returns_future_for_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve_deliver_after returns now+delay for FREE users."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        monkeypatch.setattr(scorer_tasks, "get_settings", lambda: _make_settings(_DELAY))
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.FREE))

        mock_user = MagicMock(id=1, plan="free")
        session = MagicMock()
        session.get.return_value = mock_user

        result = scorer_tasks._resolve_deliver_after(
            session, user_id=1, settings=_make_settings(_DELAY)
        )

        expected = now_fixed + timedelta(seconds=_DELAY)
        assert result == expected

    def test_resolve_deliver_after_returns_none_for_pro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve_deliver_after returns None for PRO users."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.PRO))

        mock_user = MagicMock(id=2, plan="pro")
        session = MagicMock()
        session.get.return_value = mock_user

        result = scorer_tasks._resolve_deliver_after(
            session, user_id=2, settings=_make_settings(_DELAY)
        )

        assert result is None


# ---------------------------------------------------------------------------
# AC1 (direct) — _enqueue_delivery passes countdown for Free, not for Pro
# ---------------------------------------------------------------------------


class TestAC1EnqueueDelivery:
    """_enqueue_delivery accepts a countdown kwarg; assert it's forwarded."""

    def test_enqueue_delivery_with_countdown(self) -> None:
        """_enqueue_delivery(alert_id, countdown=N) calls apply_async with countdown=N."""
        from scorer import tasks as scorer_tasks

        captured: dict[str, object] = {}

        class _FakeDispatch:
            @staticmethod
            def apply_async(args: tuple[int], countdown: int | None = None, **kw: object) -> None:
                captured["args"] = args
                captured["countdown"] = countdown

        # Patch the lazy import inside _enqueue_delivery.
        orig = sys.modules.get("alerts.tasks")
        mock_alerts = MagicMock()
        mock_alerts.dispatch_alert = _FakeDispatch
        sys.modules["alerts.tasks"] = mock_alerts
        try:
            scorer_tasks._enqueue_delivery(42, countdown=_DELAY)
        finally:
            if orig is not None:
                sys.modules["alerts.tasks"] = orig
            else:
                sys.modules.pop("alerts.tasks", None)

        assert captured["args"] == (42,)
        assert captured["countdown"] == pytest.approx(_DELAY, abs=1)

    def test_enqueue_delivery_no_countdown_for_immediate(self) -> None:
        """_enqueue_delivery(alert_id) → apply_async without countdown (immediate)."""
        from scorer import tasks as scorer_tasks

        captured: dict[str, object] = {}

        class _FakeDispatchImmediate:
            @staticmethod
            def apply_async(args: tuple[int], countdown: int | None = None, **kw: object) -> None:
                captured["countdown"] = countdown

        orig = sys.modules.get("alerts.tasks")
        mock_alerts = MagicMock()
        mock_alerts.dispatch_alert = _FakeDispatchImmediate
        sys.modules["alerts.tasks"] = mock_alerts
        try:
            scorer_tasks._enqueue_delivery(10)
        finally:
            if orig is not None:
                sys.modules["alerts.tasks"] = orig
            else:
                sys.modules.pop("alerts.tasks", None)

        # No countdown kwarg → apply_async called without countdown (None).
        assert captured.get("countdown") is None


# ---------------------------------------------------------------------------
# AC2 — _dispatch: early call → reschedule, no delivery, attempts not incremented
# ---------------------------------------------------------------------------


class TestAC2DispatchEarly:
    """AC2: if deliver_after is in the future, dispatch reschedules, doesn't deliver."""

    def _make_alert_with_future_deliver_after(self, now_fixed: datetime) -> MagicMock:
        alert = MagicMock(name="alert")
        alert.id = 77
        alert.delivery_status = "pending"
        alert.delivery_attempts = 0
        alert.deliver_after = now_fixed + timedelta(seconds=600)
        return alert

    def _make_task(self, retries: int = 0) -> MagicMock:
        task = MagicMock(name="celery_task")
        task.request.retries = retries
        return task

    def test_early_dispatch_reschedules_not_delivers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If deliver_after > now, dispatch re-enqueues with countdown=remaining."""
        from alerts import tasks as alert_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(alert_tasks, "utcnow", lambda: now_fixed)

        alert = self._make_alert_with_future_deliver_after(now_fixed)

        session = MagicMock()
        session.get.return_value = alert
        monkeypatch.setattr(alert_tasks, "get_session", lambda: _get_session_cm(session))

        enqueue_calls: list[dict] = []
        deliver_calls: list[int] = []

        monkeypatch.setattr(
            alert_tasks, "deliver", lambda s, a: deliver_calls.append(a.id) or "delivered"
        )

        class _FakeDispatch:
            @staticmethod
            def apply_async(args: tuple, countdown: int = 0, **kw: object) -> None:
                enqueue_calls.append({"args": args, "countdown": countdown})

        monkeypatch.setattr(alert_tasks, "dispatch_alert", _FakeDispatch)

        task = self._make_task()
        alert_tasks._dispatch(task, 77)

        # Must NOT have delivered.
        assert deliver_calls == []
        # Must have rescheduled.
        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]["args"] == (77,)
        # Countdown ≈ remaining time in seconds.
        expected_remaining = int((alert.deliver_after - now_fixed).total_seconds())
        assert enqueue_calls[0]["countdown"] == pytest.approx(expected_remaining, abs=2)
        # Status must stay pending — attempts must NOT be incremented.
        assert alert.delivery_attempts == 0
        assert alert.delivery_status == "pending"

    def test_early_dispatch_does_not_increment_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Attempts counter is untouched on early reschedule."""
        from alerts import tasks as alert_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(alert_tasks, "utcnow", lambda: now_fixed)

        alert = self._make_alert_with_future_deliver_after(now_fixed)
        alert.delivery_attempts = 3

        session = MagicMock()
        session.get.return_value = alert
        monkeypatch.setattr(alert_tasks, "get_session", lambda: _get_session_cm(session))
        monkeypatch.setattr(alert_tasks, "dispatch_alert", MagicMock())

        task = self._make_task()
        alert_tasks._dispatch(task, 77)

        # Attempts must still be 3 — untouched.
        assert alert.delivery_attempts == 3

    def test_past_deliver_after_proceeds_to_delivery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """deliver_after in the past (or NULL) → delivery proceeds normally."""
        from alerts import tasks as alert_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(alert_tasks, "utcnow", lambda: now_fixed)

        alert = MagicMock(name="alert")
        alert.id = 88
        alert.deliver_after = now_fixed - timedelta(seconds=60)  # past
        alert.delivery_status = "pending"
        alert.delivery_attempts = 0

        session = MagicMock()
        session.get.return_value = alert
        monkeypatch.setattr(alert_tasks, "get_session", lambda: _get_session_cm(session))

        deliver_calls: list[int] = []
        monkeypatch.setattr(
            alert_tasks, "deliver", lambda s, a: deliver_calls.append(a.id) or "delivered"
        )

        task = self._make_task()
        result = alert_tasks._dispatch(task, 88)

        assert deliver_calls == [88]
        assert result == "delivered"

    def test_null_deliver_after_proceeds_to_delivery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """deliver_after=None (Pro/Team) → delivery proceeds immediately."""
        from alerts import tasks as alert_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(alert_tasks, "utcnow", lambda: now_fixed)

        alert = MagicMock(name="alert")
        alert.id = 99
        alert.deliver_after = None
        alert.delivery_status = "pending"
        alert.delivery_attempts = 0

        session = MagicMock()
        session.get.return_value = alert
        monkeypatch.setattr(alert_tasks, "get_session", lambda: _get_session_cm(session))

        deliver_calls: list[int] = []
        monkeypatch.setattr(
            alert_tasks, "deliver", lambda s, a: deliver_calls.append(a.id) or "delivered"
        )

        task = self._make_task()
        result = alert_tasks._dispatch(task, 99)

        assert deliver_calls == [99]
        assert result == "delivered"


# ---------------------------------------------------------------------------
# AC3 — resweep respects deliver_after (skips future, enqueues past)
# ---------------------------------------------------------------------------


class TestAC3ResweepDeliver:
    """AC3: resweep query includes deliver_after filter."""

    def test_resweep_skips_future_deliver_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pending alert with deliver_after in the future is NOT re-enqueued."""
        from alerts import tasks as alert_tasks

        # The resweep query returns empty (the DB filter excludes future deliver_after).
        mock_session = _make_session([])  # DB returns nothing (future deliver_after excluded)

        with (
            patch("alerts.tasks.get_session") as mock_get_session,
            patch("alerts.tasks.dispatch_alert") as mock_dispatch,
            patch("alerts.tasks.get_settings") as mock_settings,
        ):
            mock_settings.return_value = _make_settings()
            mock_get_session.return_value = _get_session_cm(mock_session)

            count = alert_tasks._resweep_pending_alerts()

        assert count == 0
        mock_dispatch.apply_async.assert_not_called()

    def test_resweep_enqueues_past_deliver_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pending alert with deliver_after in the past IS re-enqueued."""
        from alerts import tasks as alert_tasks

        # DB returns the stale alert (deliver_after passed → included by filter).
        stale_id = 55
        mock_session = _make_session([stale_id])

        with (
            patch("alerts.tasks.get_session") as mock_get_session,
            patch("alerts.tasks.dispatch_alert") as mock_dispatch,
            patch("alerts.tasks.get_settings") as mock_settings,
        ):
            mock_settings.return_value = _make_settings()
            mock_get_session.return_value = _get_session_cm(mock_session)

            count = alert_tasks._resweep_pending_alerts()

        assert count == 1
        mock_dispatch.apply_async.assert_called_once_with(args=(stale_id,))

    def test_resweep_query_includes_deliver_after_filter(self) -> None:
        """The WHERE clause passed to session.execute includes a deliver_after guard.

        We verify this by inspecting the compiled SQL text of the SELECT statement
        that _resweep_pending_alerts builds — it must mention 'deliver_after'.
        """
        from alerts import tasks as alert_tasks

        captured_stmt: list[object] = []

        session = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute.side_effect = lambda stmt, *a, **kw: captured_stmt.append(stmt) or result

        with (
            patch("alerts.tasks.get_session") as mock_gs,
            patch("alerts.tasks.dispatch_alert"),
            patch("alerts.tasks.get_settings") as mock_settings,
        ):
            mock_settings.return_value = _make_settings()
            mock_gs.return_value = _get_session_cm(session)
            alert_tasks._resweep_pending_alerts()

        assert len(captured_stmt) >= 1
        # Compile to string and assert deliver_after is referenced.
        from sqlalchemy.dialects import postgresql

        stmt_str = str(captured_stmt[0].compile(dialect=postgresql.dialect()))
        assert "deliver_after" in stmt_str.lower()


# ---------------------------------------------------------------------------
# AC4 — expired Pro subscription rolls back to Free → alerts are delayed
# ---------------------------------------------------------------------------


class TestAC4ExpiredPlanFree:
    """AC4: effective_plan(session, user) returns FREE for expired Pro → delay applied."""

    def test_expired_pro_treated_as_free(self) -> None:
        """effective_plan returns FREE for an expired subscription.

        TASK-048: expiry now carries a 72h grace window — «expired» honestly
        means «expired AND the grace elapsed», so the sub expired 4 days ago.
        """
        from billing.limits import effective_plan
        from billing.plans import Plan
        from storage.models.users import User

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Build a Pro user with a subscription expired beyond the grace window.
        user = MagicMock(spec=User)
        user.plan = "pro"
        user.id = 3

        expired_sub = MagicMock()
        expired_sub.expires_at = now_fixed - timedelta(days=4)  # beyond 72h grace

        session = MagicMock()
        session.scalars.return_value.one_or_none.return_value = expired_sub

        with patch("billing.limits.utcnow", return_value=now_fixed):
            plan = effective_plan(session, user)

        assert plan == Plan.FREE

    def test_resolve_deliver_after_for_expired_pro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_deliver_after: expired Pro user gets deliver_after set."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        # effective_plan patched to return FREE (simulates expired Pro).
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.FREE))

        mock_user = MagicMock(id=3, plan="pro")
        session = MagicMock()
        session.get.return_value = mock_user

        result = scorer_tasks._resolve_deliver_after(
            session, user_id=3, settings=_make_settings(_DELAY)
        )

        # Expired Pro → treated as Free → deliver_after is set.
        expected = now_fixed + timedelta(seconds=_DELAY)
        assert result == expected

    def test_scorer_uses_effective_plan_for_delay_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """scorer calls effective_plan; expired Pro → deliver_after set in tuple."""
        from billing.plans import Plan
        from scorer import tasks as scorer_tasks

        now_fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(scorer_tasks, "utcnow", lambda: now_fixed)
        monkeypatch.setattr(scorer_tasks, "get_settings", lambda: _make_settings(_DELAY))

        # effective_plan patched to return FREE (simulates expired Pro).
        monkeypatch.setattr(scorer_tasks, "effective_plan", MagicMock(return_value=Plan.FREE))

        captured: dict[str, object] = {}

        def _fake_create(
            session: object,
            *,
            user_id: int,
            cluster: object,
            score: float,
            channels_count: int,
            deliver_after: datetime | None = None,
        ) -> int:
            captured["deliver_after"] = deliver_after
            return 11

        monkeypatch.setattr(scorer_tasks, "_create_alert_idempotent", _fake_create)

        apply_calls: list[dict] = []

        def _fake_enqueue(alert_id: int, *, countdown: int | None = None) -> None:
            apply_calls.append({"countdown": countdown})

        monkeypatch.setattr(scorer_tasks, "_enqueue_delivery", _fake_enqueue)

        def _fake_score_user(
            sess: object,
            *,
            user_id: int,
            window_start: datetime,
            gbdt: object | None = None,
        ) -> list[tuple[int, int | None]]:
            # Simulate what scorer._score_user must do: effective_plan → FREE → delay.
            plan = scorer_tasks.effective_plan(sess, MagicMock(id=user_id, plan="pro"))
            delay = scorer_tasks.get_settings().free_alert_delay_seconds
            da = now_fixed + timedelta(seconds=delay) if plan == Plan.FREE else None
            cntdown = delay if da is not None else None
            aid = _fake_create(
                sess,
                user_id=user_id,
                cluster=MagicMock(id=9, topic="z", first_seen=now_fixed),
                score=0.9,
                channels_count=1,
                deliver_after=da,
            )
            return [(aid, cntdown)] if aid else []

        monkeypatch.setattr(scorer_tasks, "_score_user", _fake_score_user)
        monkeypatch.setattr(scorer_tasks, "list_active_user_ids", lambda s: [3])

        with patch("scorer.tasks.get_session") as mock_gs:
            mock_gs.return_value = _get_session_cm(MagicMock())
            scorer_tasks.score_recent_clusters()

        assert captured["deliver_after"] == now_fixed + timedelta(seconds=_DELAY)
        assert apply_calls[0]["countdown"] == _DELAY


# ---------------------------------------------------------------------------
# AC1 (settings) — free_alert_delay_seconds setting exists
# ---------------------------------------------------------------------------


def test_settings_has_free_alert_delay_seconds() -> None:
    """Settings must expose free_alert_delay_seconds (default 1800)."""
    from config import get_settings

    settings = get_settings()
    assert hasattr(settings, "free_alert_delay_seconds")
    assert settings.free_alert_delay_seconds == 1800


# ---------------------------------------------------------------------------
# AC1 (model) — Alert.deliver_after field exists
# ---------------------------------------------------------------------------


def test_alert_model_has_deliver_after_field() -> None:
    """Alert ORM model must have a nullable deliver_after column."""
    from storage.models.alerts import Alert

    assert hasattr(Alert, "deliver_after")
    col = Alert.__table__.c["deliver_after"]
    assert col.nullable is True
