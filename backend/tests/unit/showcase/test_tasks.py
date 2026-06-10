"""Unit tests for showcase/tasks.py (AC2, AC3, AC4).

Tests the beat task body via _run_tick_body:
- AC2: tick with candidate → mocked Bot API sendMessage called with chat_id+text,
       row showcase_posts status=posted.
- AC3: second tick same cluster → no second send (idempotency).
       send failure → status stays pending → next tick retries (see integration/).
- AC4: empty token/chat_id → no-op + warn-once, no crash.
       empty public_base_url → no-op + warn-once (CTA skip, Fix #5).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _FakeCluster:
    """Minimal cluster stub satisfying ClusterLike for task tests."""

    def __init__(
        self,
        cluster_id: int,
        topic: str,
        viral_score: float,
        first_seen: datetime,
    ) -> None:
        self.id = cluster_id
        self.topic = topic
        self.viral_score = viral_score
        self.first_seen = first_seen


class _FakeShowcasePost:
    """Minimal showcase_posts row stub."""

    def __init__(self, cluster_id: int, status: str = "pending") -> None:
        self.cluster_id = cluster_id
        self.status = status
        self.posted_at: datetime | None = None


class _FakeSettings:
    """Minimal settings stub for task tests."""

    showcase_bot_token: str = "test-bot-token"
    showcase_channel_chat_id: str = "-100123456789"
    showcase_post_interval_seconds: int = 900
    showcase_post_delay_seconds: int = 2400
    showcase_post_min_score: float = 85.0
    showcase_posts_per_day_max: int = 8
    trending_window_seconds: int = 86_400
    showcase_user_email: str = "showcase@internal"
    telegram_api_base_url: str = "https://api.telegram.org"
    alert_http_timeout_seconds: int = 10
    public_base_url: str = "https://foresignal.biz"


def _now() -> datetime:
    return datetime(2026, 6, 10, 14, 0, 0, tzinfo=UTC)


def _import_tasks() -> Any:
    """Defer import so RED phase captures ImportError."""
    from showcase import tasks  # type: ignore[import]

    return tasks


def _import_sender() -> Any:
    """Defer import so RED phase captures ImportError."""
    from showcase import sender  # type: ignore[import]

    return sender


# ---------------------------------------------------------------------------
# Autouse fixture: reset warn-once module globals between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_warn_once_flags() -> Any:
    """Reset module-level warn-once flags so tests don't cross-contaminate.

    Also patches `showcase.cases.fix_cases` to a no-op for all unit tests in this
    file: these tests exercise the posting path only; fixation is covered by
    integration/test_showcase_autopost.py::test_fix_cases_runs_without_tg_creds.
    Patching ensures the mock-session scalar/execute sequences are not disrupted
    by fix_cases DB calls that run before the posting path (TASK-045 restructure).
    """
    import showcase.sender as sender_mod
    import showcase.tasks as tasks_mod

    # Save
    old_warned_creds = tasks_mod._WARNED_NO_CREDS
    old_warned_public = tasks_mod._WARNED_NO_PUBLIC_BASE_URL
    old_sender_warned = frozenset(sender_mod._WARNED_MISSING)

    tasks_mod._WARNED_NO_CREDS = False
    tasks_mod._WARNED_NO_PUBLIC_BASE_URL = False
    sender_mod._WARNED_MISSING.clear()

    with patch("showcase.cases.fix_cases", return_value=None):
        yield

    # Restore (or leave reset — tests are isolated either way)
    tasks_mod._WARNED_NO_CREDS = old_warned_creds
    tasks_mod._WARNED_NO_PUBLIC_BASE_URL = old_warned_public
    sender_mod._WARNED_MISSING.clear()
    sender_mod._WARNED_MISSING.update(old_sender_warned)


# ---------------------------------------------------------------------------
# Helper: build a fully-mocked session that simulates one qualifying cluster
# ---------------------------------------------------------------------------


def _make_fake_session(
    *,
    cluster: _FakeCluster,
    existing_sp: _FakeShowcasePost | None = None,
    posts_today: int = 0,
) -> MagicMock:
    """Return a mock session wired up for a single-cluster happy-path tick."""
    session = MagicMock()

    # Showcase user lookup → user with id=1
    fake_user = MagicMock()
    fake_user.id = 1

    # Cluster query rows
    fake_row = MagicMock()
    fake_row.id = cluster.id
    fake_row.topic = cluster.topic
    fake_row.viral_score = cluster.viral_score
    fake_row.first_seen = cluster.first_seen

    # posted_cluster_ids query (status=posted only) — empty by default
    fake_posted_ids_result = MagicMock()
    fake_posted_ids_result.all.return_value = []

    # posts_today scalar
    scalar_results = [
        fake_user,  # showcase user
        posts_today,  # posts_today count
        existing_sp,  # re-fetch after insert (or None → not yet posted)
    ]
    scalar_call_count = [0]

    def _scalar(stmt: object) -> Any:
        idx = scalar_call_count[0]
        scalar_call_count[0] += 1
        return scalar_results[idx] if idx < len(scalar_results) else None

    session.scalar.side_effect = _scalar

    # cluster rows execute
    fake_clusters_result = MagicMock()
    fake_clusters_result.all.return_value = [fake_row]

    # posted ids execute
    fake_execute_results = [fake_clusters_result, fake_posted_ids_result]
    execute_call_count = [0]

    def _execute(stmt: object) -> Any:
        idx = execute_call_count[0]
        execute_call_count[0] += 1
        return fake_execute_results[idx] if idx < len(fake_execute_results) else MagicMock()

    session.execute.side_effect = _execute

    return session


# ---------------------------------------------------------------------------
# AC2 — tick with candidate → sendMessage called + status=posted
# ---------------------------------------------------------------------------


class TestTickWithCandidate:
    def test_send_called_with_correct_chat_id_and_text(self) -> None:
        """When a candidate exists, send_showcase_post is called with chat_id+text."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        now = _now()
        cluster = _FakeCluster(
            cluster_id=42,
            topic="Bitcoin ETF",
            viral_score=92.0,
            first_seen=now - timedelta(seconds=3000),
        )

        fake_sp = _FakeShowcasePost(cluster_id=42, status="pending")
        session = _make_fake_session(cluster=cluster, existing_sp=fake_sp)

        send_calls: list[dict[str, Any]] = []

        def fake_send(**kwargs: Any) -> bool:
            send_calls.append(kwargs)
            return True

        with (
            patch("config.get_settings", return_value=settings),
            patch("showcase.tasks.send_showcase_post", side_effect=fake_send),
        ):
            tasks._run_tick_body(session)

        assert len(send_calls) == 1
        assert send_calls[0]["chat_id"] == settings.showcase_channel_chat_id
        assert send_calls[0]["token"] == settings.showcase_bot_token
        assert "обнаружено" in send_calls[0]["text"]
        assert "utm_source=tg_showcase" in send_calls[0]["text"]

    def test_status_set_to_posted_on_success(self) -> None:
        """On send success the showcase_posts row status becomes posted."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        now = _now()
        cluster = _FakeCluster(
            cluster_id=43,
            topic="Ethereum staking",
            viral_score=88.0,
            first_seen=now - timedelta(seconds=3000),
        )

        fake_sp = _FakeShowcasePost(cluster_id=43, status="pending")
        session = _make_fake_session(cluster=cluster, existing_sp=fake_sp)

        with (
            patch("config.get_settings", return_value=settings),
            patch("showcase.tasks.send_showcase_post", return_value=True),
        ):
            tasks._run_tick_body(session)

        assert fake_sp.status == "posted"
        assert fake_sp.posted_at is not None

    def test_post_text_contains_time_stamp_and_utm_cta(self) -> None:
        """Constructed post text must contain обнаружено в HH:MM UTC + utm CTA."""
        from showcase.formatting import build_showcase_post

        first_seen = datetime(2026, 6, 10, 14, 2, 0, tzinfo=UTC)
        text = build_showcase_post(
            topic="Test topic",
            score=94.0,
            first_seen=first_seen,
            public_base_url="https://foresignal.biz",
        )

        assert "обнаружено в 14:02 UTC" in text
        assert "utm_source=tg_showcase" in text
        assert "utm_campaign=autopost" in text
        assert "🔥" in text


# ---------------------------------------------------------------------------
# AC3 — idempotency: second tick no re-send, send failure → pending (see integration)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_tick_same_cluster_no_send_when_already_posted(self) -> None:
        """If cluster already has status=posted in posted_cluster_ids, no send attempted."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        now = _now()
        cluster = _FakeCluster(
            cluster_id=44,
            topic="Already posted",
            viral_score=90.0,
            first_seen=now - timedelta(seconds=3000),
        )

        session = MagicMock()
        fake_user = MagicMock()
        fake_user.id = 1

        # posted_ids_rows contains this cluster → it will be excluded by dedup
        fake_posted_row = MagicMock()
        fake_posted_row.cluster_id = 44

        fake_clusters_result = MagicMock()
        fake_row = MagicMock()
        fake_row.id = cluster.id
        fake_row.topic = cluster.topic
        fake_row.viral_score = cluster.viral_score
        fake_row.first_seen = cluster.first_seen
        fake_clusters_result.all.return_value = [fake_row]

        fake_posted_ids_result = MagicMock()
        fake_posted_ids_result.all.return_value = [fake_posted_row]

        execute_calls = [fake_clusters_result, fake_posted_ids_result]
        exec_idx = [0]

        def _execute(stmt: object) -> Any:
            idx = exec_idx[0]
            exec_idx[0] += 1
            return execute_calls[idx] if idx < len(execute_calls) else MagicMock()

        session.execute.side_effect = _execute
        scalar_idx = [0]
        scalar_results = [fake_user, 0]

        def _scalar(stmt: object) -> Any:
            idx = scalar_idx[0]
            scalar_idx[0] += 1
            return scalar_results[idx] if idx < len(scalar_results) else None

        session.scalar.side_effect = _scalar

        send_calls: list[Any] = []

        with (
            patch("config.get_settings", return_value=settings),
            patch(
                "showcase.tasks.send_showcase_post",
                side_effect=lambda **kw: send_calls.append(kw) or True,
            ),
        ):
            tasks._run_tick_body(session)

        assert len(send_calls) == 0, "Must not send when cluster is already in posted set"

    def test_send_failure_leaves_status_pending(self) -> None:
        """If send fails, the row status stays pending so next tick retries."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        now = _now()
        cluster = _FakeCluster(
            cluster_id=45,
            topic="Pending retry topic",
            viral_score=89.0,
            first_seen=now - timedelta(seconds=3000),
        )

        fake_sp = _FakeShowcasePost(cluster_id=45, status="pending")
        session = _make_fake_session(cluster=cluster, existing_sp=fake_sp)

        with (
            patch("config.get_settings", return_value=settings),
            patch("showcase.tasks.send_showcase_post", return_value=False),
        ):
            tasks._run_tick_body(session)

        assert fake_sp.status == "pending", "Status must remain pending after failed send"
        assert fake_sp.posted_at is None


# ---------------------------------------------------------------------------
# AC4 — empty creds → no-op + warn-once, no crash
# ---------------------------------------------------------------------------


class TestEmptyCredentials:
    def test_empty_token_no_op_no_crash(self, caplog: pytest.LogCaptureFixture) -> None:
        """Empty showcase_bot_token → no-op, task does not raise."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        settings.showcase_bot_token = ""

        session = MagicMock()

        with (
            caplog.at_level(logging.WARNING, logger="showcase.tasks"),
            patch("config.get_settings", return_value=settings),
        ):
            tasks._run_tick_body(session)

        # Must not have called execute / scalar (no DB queries after creds check)
        session.execute.assert_not_called()
        # Warning must be logged (warn-once)
        assert any(
            "missing" in r.message.lower() or "disabled" in r.message.lower()
            for r in caplog.records
        )

    def test_empty_chat_id_no_op_no_crash(self) -> None:
        """Empty showcase_channel_chat_id → no-op, task does not raise."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        settings.showcase_channel_chat_id = ""

        session = MagicMock()

        with patch("config.get_settings", return_value=settings):
            tasks._run_tick_body(session)

        session.execute.assert_not_called()

    def test_warn_once_not_repeated(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warn-once: two no-creds ticks emit only one warning (no log flooding)."""
        tasks = _import_tasks()
        settings = _FakeSettings()
        settings.showcase_bot_token = ""

        session = MagicMock()

        with (
            caplog.at_level(logging.WARNING, logger="showcase.tasks"),
            patch("config.get_settings", return_value=settings),
        ):
            tasks._run_tick_body(session)
            tasks._run_tick_body(session)

        warning_count = sum(
            1
            for r in caplog.records
            if "disabled" in r.message.lower() or "missing" in r.message.lower()
        )
        assert warning_count == 1, f"Expected 1 warning, got {warning_count}"

    def test_empty_public_base_url_no_op_warns_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """Fix #5: empty public_base_url while creds present → no-op + warn-once.

        A CTA-less post defeats the feature — skip entirely rather than posting
        without a link.
        """
        tasks = _import_tasks()
        settings = _FakeSettings()
        settings.public_base_url = ""

        session = MagicMock()
        send_calls: list[Any] = []

        with (
            caplog.at_level(logging.WARNING, logger="showcase.tasks"),
            patch("config.get_settings", return_value=settings),
            patch(
                "showcase.tasks.send_showcase_post",
                side_effect=lambda **kw: send_calls.append(kw) or True,
            ),
        ):
            tasks._run_tick_body(session)
            tasks._run_tick_body(session)

        assert len(send_calls) == 0, "Must not send when public_base_url is empty"
        warning_count = sum(1 for r in caplog.records if "public_base_url" in r.message.lower())
        assert warning_count == 1, f"Expected 1 no_public_base_url warning, got {warning_count}"
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Sender unit tests (httpx mocking)
# ---------------------------------------------------------------------------


class TestSender:
    def test_send_posts_to_correct_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_showcase_post POSTs to bot<token>/sendMessage with chat_id+text."""
        sender = _import_sender()

        posted: list[dict[str, Any]] = []

        def fake_post(url: str, **kwargs: Any) -> MagicMock:
            posted.append({"url": url, "json": kwargs.get("json")})
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("showcase.sender.httpx.post", fake_post)

        result = sender.send_showcase_post(
            token="mytoken",
            chat_id="-100abc",
            text="🔥 Bitcoin ETF · score 94 · обнаружено в 14:02 UTC",
            base_url="https://api.telegram.org",
            timeout=10,
        )

        assert result is True
        assert len(posted) == 1
        assert posted[0]["url"] == "https://api.telegram.org/botmytoken/sendMessage"
        assert posted[0]["json"]["chat_id"] == "-100abc"
        assert "🔥" in posted[0]["json"]["text"]

    def test_send_returns_false_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 429 → return False (will retry next tick)."""
        sender = _import_sender()

        def fake_post(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 429
            return resp

        monkeypatch.setattr("showcase.sender.httpx.post", fake_post)

        result = sender.send_showcase_post(
            token="mytoken",
            chat_id="-100abc",
            text="Post text",
            base_url="https://api.telegram.org",
            timeout=10,
        )

        assert result is False

    def test_send_returns_false_on_network_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Network exception → return False (will retry next tick), not raise."""
        import httpx

        sender = _import_sender()

        def fake_post(url: str, **kwargs: Any) -> MagicMock:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("showcase.sender.httpx.post", fake_post)

        result = sender.send_showcase_post(
            token="mytoken",
            chat_id="-100abc",
            text="Post text",
            base_url="https://api.telegram.org",
            timeout=10,
        )

        assert result is False

    def test_token_not_in_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Token must never appear in log output."""
        sender = _import_sender()
        secret_token = "SUPER_SECRET_TOKEN_XYZ"

        def fake_post(url: str, **kwargs: Any) -> MagicMock:
            raise Exception("unexpected error")

        monkeypatch.setattr("showcase.sender.httpx.post", fake_post)

        with caplog.at_level(logging.DEBUG):
            sender.send_showcase_post(
                token=secret_token,
                chat_id="-100abc",
                text="Post text",
                base_url="https://api.telegram.org",
                timeout=10,
            )

        for record in caplog.records:
            assert secret_token not in str(record.message)
            assert secret_token not in str(getattr(record, "exc_text", ""))

    def test_success_log_event_does_not_include_chat_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fix #7: success log_event must NOT include chat_id (static per-deployment)."""
        sender = _import_sender()

        logged_events: list[dict[str, Any]] = []

        def fake_post(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            return resp

        def fake_log_event(event_name: str, **kwargs: Any) -> None:
            logged_events.append({"event": event_name, "kwargs": kwargs})

        monkeypatch.setattr("showcase.sender.httpx.post", fake_post)
        monkeypatch.setattr("showcase.sender.log_event", fake_log_event)

        sender.send_showcase_post(
            token="mytoken",
            chat_id="-100specific",
            text="Post text",
            base_url="https://api.telegram.org",
            timeout=10,
        )

        sent_events = [e for e in logged_events if e["event"] == "showcase_post_sent"]
        assert len(sent_events) == 1
        assert "chat_id" not in sent_events[0]["kwargs"], (
            "chat_id must not appear in the showcase_post_sent log_event"
        )
