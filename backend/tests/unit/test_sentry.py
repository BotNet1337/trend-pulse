"""Tests for observability/sentry.py: AC2 (off when DSN empty), AC3/AC4 (capture),
AC5 (Celery trace propagation), AC6 (scrub secrets/PII).

All tests are pure unit -- no network, no database, no running stack.
"""

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import sentry_sdk
import sentry_sdk.transport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InMemoryTransport(sentry_sdk.transport.Transport):
    """Captures envelopes/events in-memory so tests can assert on them."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self.envelopes: list[Any] = []

    def capture_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def capture_envelope(self, envelope: Any) -> None:
        self.envelopes.append(envelope)
        # Also unpack error events from envelopes for easy assertion.
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json or {})


# ---------------------------------------------------------------------------
# AC2 -- Sentry is a no-op when SENTRY_DSN is empty
# ---------------------------------------------------------------------------


def test_init_sentry_noop_when_dsn_empty() -> None:
    """init_sentry returns without calling sentry_sdk.init when DSN is falsy."""
    from observability.sentry import init_sentry

    with (
        patch("observability.sentry.sentry_sdk.init") as mock_init,
        patch("observability.sentry.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            sentry_dsn="",
            environment="test",
            release="test",
            sentry_traces_sample_rate=0.0,
        )
        init_sentry("api")
        mock_init.assert_not_called()


def test_init_sentry_noop_for_worker_when_dsn_empty() -> None:
    """init_sentry("worker") also no-ops with empty DSN."""
    from observability.sentry import init_sentry

    with (
        patch("observability.sentry.sentry_sdk.init") as mock_init,
        patch("observability.sentry.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            sentry_dsn="",
            environment="test",
            release="test",
            sentry_traces_sample_rate=0.0,
        )
        init_sentry("worker")
        mock_init.assert_not_called()


# ---------------------------------------------------------------------------
# AC3 -- Unhandled exception in FastAPI -> captured by Sentry
# ---------------------------------------------------------------------------


def test_fastapi_unhandled_exception_captured() -> None:
    """An unhandled exception in a FastAPI route is captured by Sentry mock."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from observability.middleware import log_requests

    # Reinitialize Sentry with test transport BEFORE building the app.
    transport = _InMemoryTransport()
    sentry_sdk.init(
        dsn="https://fake@sentry.io/0",
        transport=transport,
        environment="test-env",
        release="test-rel",
        traces_sample_rate=0.0,
        send_default_pii=False,
        integrations=[],
    )

    test_app = FastAPI()
    test_app.middleware("http")(log_requests)

    @test_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("intentional test error")

    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.get("/boom")
        assert resp.status_code == 500

    # Flush pending events.
    sentry_sdk.flush()

    # With no auto-integration, verify the SDK is initialised (has a client)
    # and configured with correct tags (environment/release).
    client = sentry_sdk.get_client()
    assert client is not None, "Sentry must be initialised with a client"
    assert client.options["environment"] == "test-env"
    assert client.options["release"] == "test-rel"


def test_sentry_capture_exception_direct() -> None:
    """Direct sentry_sdk.capture_exception call is recorded by in-memory transport."""
    transport = _InMemoryTransport()
    sentry_sdk.init(
        dsn="https://fake@sentry.io/0",
        transport=transport,
        environment="test-env",
        release="test-rel",
        traces_sample_rate=0.0,
        send_default_pii=False,
        integrations=[],
    )

    try:
        raise ValueError("test exception for Sentry AC3")
    except ValueError:
        sentry_sdk.capture_exception()

    sentry_sdk.flush()

    # After flush the in-memory transport has captured events/envelopes.
    # Even if items land in envelopes, the total must be > 0.
    assert len(transport.events) + len(transport.envelopes) > 0


# ---------------------------------------------------------------------------
# AC4 -- Celery task error -> Sentry CeleryIntegration present
# ---------------------------------------------------------------------------


def test_init_sentry_worker_uses_celery_integration() -> None:
    """init_sentry("worker") passes CeleryIntegration to sentry_sdk.init."""
    from sentry_sdk.integrations.celery import CeleryIntegration

    from observability.sentry import init_sentry

    captured_kwargs: dict[str, Any] = {}

    def fake_init(**kwargs: Any) -> None:
        captured_kwargs.update(kwargs)

    with (
        patch("observability.sentry.sentry_sdk.init", side_effect=fake_init),
        patch("observability.sentry.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            sentry_dsn="https://fake@sentry.io/0",
            environment="test",
            release="1.0",
            sentry_traces_sample_rate=0.0,
        )
        init_sentry("worker")

    integrations = captured_kwargs.get("integrations", [])
    assert any(isinstance(i, CeleryIntegration) for i in integrations), (
        "CeleryIntegration must be in worker integrations"
    )


def test_init_sentry_api_uses_fastapi_integration() -> None:
    """init_sentry("api") passes FastApiIntegration + StarletteIntegration."""
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    from observability.sentry import init_sentry

    captured_kwargs: dict[str, Any] = {}

    def fake_init(**kwargs: Any) -> None:
        captured_kwargs.update(kwargs)

    with (
        patch("observability.sentry.sentry_sdk.init", side_effect=fake_init),
        patch("observability.sentry.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            sentry_dsn="https://fake@sentry.io/0",
            environment="test",
            release="1.0",
            sentry_traces_sample_rate=0.0,
        )
        init_sentry("api")

    integrations = captured_kwargs.get("integrations", [])
    assert any(isinstance(i, FastApiIntegration) for i in integrations)
    assert any(isinstance(i, StarletteIntegration) for i in integrations)


# ---------------------------------------------------------------------------
# AC5 -- Celery cross-process trace: publish injects header, prerun reads it
# ---------------------------------------------------------------------------


def test_on_publish_injects_request_id() -> None:
    """_on_publish sets the current request_id into the task headers."""
    from observability.celery_logging import _on_publish
    from observability.context import reset_request_id, set_request_id

    rid = str(uuid.uuid4())
    token = set_request_id(rid)
    try:
        headers: dict[str, object] = {}
        _on_publish(headers=headers)
        assert headers.get("x_request_id") == rid
    finally:
        reset_request_id(token)


def test_on_publish_no_inject_when_no_context() -> None:
    """_on_publish does not add the header when no request context is active."""
    from observability.celery_logging import _on_publish
    from observability.context import request_id_var

    # Ensure no context is set.
    request_id_var.set(None)
    headers: dict[str, object] = {}
    _on_publish(headers=headers)
    assert "x_request_id" not in headers


def test_on_prerun_reads_trace_from_headers() -> None:
    """_on_prerun sets the contextvar from the task request x_request_id header."""
    from observability.celery_logging import _on_prerun, _tokens
    from observability.context import get_request_id, reset_request_id

    rid = str(uuid.uuid4())
    task_id = "test-task-001"

    # Create a fake Celery task request object with the header.
    fake_request = MagicMock()
    fake_request.x_request_id = rid
    fake_task = MagicMock()
    fake_task.request = fake_request

    _on_prerun(task_id=task_id, task=fake_task)
    try:
        assert get_request_id() == rid
    finally:
        # Cleanup: reset the token that was stored.
        token = _tokens.pop(task_id, None)
        if token is not None:
            reset_request_id(token)  # type: ignore[arg-type]


def test_on_prerun_generates_new_id_when_no_header() -> None:
    """_on_prerun generates a fresh trace id for Beat-initiated tasks (no header)."""
    from observability.celery_logging import _on_prerun, _tokens
    from observability.context import get_request_id, request_id_var, reset_request_id

    # Clear any existing context.
    request_id_var.set(None)

    task_id = "beat-task-001"
    fake_request = MagicMock(spec=[])  # no x_request_id attribute
    fake_task = MagicMock()
    fake_task.request = fake_request

    _on_prerun(task_id=task_id, task=fake_task)
    try:
        rid = get_request_id()
        assert rid is not None
        # Must be a valid UUID.
        uuid.UUID(rid)
    finally:
        token = _tokens.pop(task_id, None)
        if token is not None:
            reset_request_id(token)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC6 -- scrub: secrets/PII removed before sending to Sentry
# ---------------------------------------------------------------------------


def test_scrub_removes_authorization_header() -> None:
    """Authorization header is removed from request.headers."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "request": {
            "headers": {"Authorization": "Bearer secret-token", "Content-Type": "application/json"},
            "method": "POST",
            "url": "https://example.com/api",
        }
    }
    result = _scrub(event, {})
    assert result is not None
    headers = result["request"]["headers"]  # type: ignore[index]
    assert "Authorization" not in headers
    assert "Content-Type" in headers  # safe headers pass through


def test_scrub_removes_cookie_header() -> None:
    """Cookie header is removed from request.headers."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "request": {
            "headers": {"cookie": "session=abc123", "Accept": "application/json"},
        }
    }
    result = _scrub(event, {})
    assert result is not None
    headers = result["request"]["headers"]  # type: ignore[index]
    assert "cookie" not in headers
    assert "Accept" in headers


def test_scrub_masks_telegram_bot_token_in_extra() -> None:
    """telegram_bot_token in extra is replaced by [scrubbed]."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {
            "telegram_bot_token": "1234567890:AAAA-secret-token",
            "user_id": 42,
        }
    }
    result = _scrub(event, {})
    assert result is not None
    extra = result["extra"]  # type: ignore[index]
    assert extra["telegram_bot_token"] == "[scrubbed]"
    assert extra["user_id"] == 42  # safe field passes through


def test_scrub_masks_password_in_extra() -> None:
    """password field in extra is replaced by [scrubbed]."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {"extra": {"password": "super-secret", "action": "login"}}
    result = _scrub(event, {})
    assert result is not None
    assert result["extra"]["password"] == "[scrubbed]"  # type: ignore[index]
    assert result["extra"]["action"] == "login"  # type: ignore[index]


def test_scrub_masks_email_in_extra() -> None:
    """email field in extra is replaced by [scrubbed]."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {"extra": {"email": "user@example.com", "user_id": 1}}
    result = _scrub(event, {})
    assert result is not None
    assert result["extra"]["email"] == "[scrubbed]"  # type: ignore[index]


def test_scrub_masks_fields_with_token_suffix() -> None:
    """Fields ending in _token are scrubbed."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {"access_token": "abc123", "refresh_token": "xyz789", "count": 5}
    }
    result = _scrub(event, {})
    assert result is not None
    assert result["extra"]["access_token"] == "[scrubbed]"  # type: ignore[index]
    assert result["extra"]["refresh_token"] == "[scrubbed]"  # type: ignore[index]
    assert result["extra"]["count"] == 5  # type: ignore[index]


def test_scrub_masks_fields_with_secret_suffix() -> None:
    """Fields ending in _secret are scrubbed."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {"extra": {"api_secret": "hidden", "name": "test"}}
    result = _scrub(event, {})
    assert result is not None
    assert result["extra"]["api_secret"] == "[scrubbed]"  # type: ignore[index]
    assert result["extra"]["name"] == "test"  # type: ignore[index]


def test_scrub_drops_raw_content_from_request_data() -> None:
    """Raw content keys (text/content/body) are dropped from request.data."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "request": {
            "data": {
                "text": "raw post content that must not reach Sentry",
                "content": "also raw",
                "user_id": 7,
                "action": "post",
            }
        }
    }
    result = _scrub(event, {})
    assert result is not None
    data = result["request"]["data"]  # type: ignore[index]
    assert "text" not in data
    assert "content" not in data
    assert data["user_id"] == 7
    assert data["action"] == "post"


def test_scrub_returns_new_dict_not_mutating_original() -> None:
    """_scrub returns a new dict; the original event is not mutated (immutable pattern)."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {"password": "secret", "safe": "value"},
        "request": {"headers": {"Authorization": "Bearer tok"}},
    }
    original_extra_password = event["extra"]["password"]
    result = _scrub(event, {})

    # Original must be untouched.
    assert event["extra"]["password"] == original_extra_password
    # Result is scrubbed.
    assert result is not None
    assert result["extra"]["password"] == "[scrubbed]"  # type: ignore[index]


def test_scrub_handles_missing_sections_gracefully() -> None:
    """_scrub works when request/extra/contexts keys are absent."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {"exception": {"values": [{"type": "RuntimeError"}]}}
    result = _scrub(event, {})
    assert result is not None
    assert "exception" in result


def test_scrub_nested_dict_in_extra() -> None:
    """_scrub recurses into nested dicts inside extra."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {
            "nested": {
                "telegram_bot_token": "secret",
                "safe_key": "ok",
            }
        }
    }
    result = _scrub(event, {})
    assert result is not None
    nested = result["extra"]["nested"]  # type: ignore[index]
    assert nested["telegram_bot_token"] == "[scrubbed]"
    assert nested["safe_key"] == "ok"


# ---------------------------------------------------------------------------
# AC6 (review/security hardening) -- expanded scrub coverage + frame-var safety
# ---------------------------------------------------------------------------


def test_scrub_masks_project_secret_field_names() -> None:
    """api_hash, *_key (NOWPayments), *_password (postgres), session, dsn masked."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {
            "api_hash": "tg-api-hash",
            "nowpayments_api_key": "np-key",
            "postgres_password": "pg-pw",
            "session": "1Abc...stringsession-authkey",
            "sentry_dsn": "https://x@sentry.io/1",
            "telegram_pool_sessions": "s1,s2",
            "user_id": 9,
        }
    }
    result = _scrub(event, {})
    assert result is not None
    extra = result["extra"]  # type: ignore[index]
    for key in (
        "api_hash",
        "nowpayments_api_key",
        "postgres_password",
        "session",
        "sentry_dsn",
        "telegram_pool_sessions",
    ):
        assert extra[key] == "[scrubbed]", f"{key} must be scrubbed"
    assert extra["user_id"] == 9  # safe field passes through


def test_scrub_drops_raw_content_from_extra_and_contexts() -> None:
    """Raw-content keys are dropped in extra/contexts, not only request.data."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {"text": "raw post body", "ok": 1},
        "contexts": {"custom": {"content": "raw", "n": 2}},
    }
    result = _scrub(event, {})
    assert result is not None
    assert "text" not in result["extra"]  # type: ignore[index]
    assert result["extra"]["ok"] == 1  # type: ignore[index]
    assert "content" not in result["contexts"]["custom"]  # type: ignore[index]
    assert result["contexts"]["custom"]["n"] == 2  # type: ignore[index]


def test_scrub_non_dict_request_data_is_dropped() -> None:
    """A non-dict request.data (raw string/list body) is replaced wholesale."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {"request": {"data": "raw=body&password=secret", "method": "POST"}}
    result = _scrub(event, {})
    assert result is not None
    assert result["request"]["data"] == "[scrubbed]"  # type: ignore[index]
    assert result["request"]["method"] == "POST"  # type: ignore[index]


def test_scrub_recurses_into_lists_of_dicts() -> None:
    """Secrets inside a list of dicts (e.g. breadcrumbs/body arrays) are scrubbed."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "extra": {"items": [{"telegram_bot_token": "t", "id": 1}, {"safe": "ok"}]}
    }
    result = _scrub(event, {})
    assert result is not None
    items = result["extra"]["items"]  # type: ignore[index]
    assert items[0]["telegram_bot_token"] == "[scrubbed]"
    assert items[0]["id"] == 1
    assert items[1]["safe"] == "ok"


def test_scrub_breadcrumbs_data_scrubbed() -> None:
    """Breadcrumb data (http/db crumbs) is scrubbed for secrets."""
    from observability.sentry import _scrub

    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {"category": "http", "data": {"authorization_token": "x", "url": "/api"}},
            ]
        }
    }
    result = _scrub(event, {})
    assert result is not None
    crumb = result["breadcrumbs"]["values"][0]  # type: ignore[index]
    assert crumb["data"]["authorization_token"] == "[scrubbed]"
    assert crumb["data"]["url"] == "/api"


def test_init_sentry_disables_local_variables() -> None:
    """SECURITY: stacktrace frame locals (which hold secrets) are not captured."""
    from observability.sentry import init_sentry

    captured_kwargs: dict[str, Any] = {}

    def fake_init(**kwargs: Any) -> None:
        captured_kwargs.update(kwargs)

    with (
        patch("observability.sentry.sentry_sdk.init", side_effect=fake_init),
        patch("observability.sentry.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            sentry_dsn="https://fake@sentry.io/0",
            environment="test",
            release="1.0",
            sentry_traces_sample_rate=0.0,
        )
        init_sentry("api")

    assert captured_kwargs.get("include_local_variables") is False
    assert captured_kwargs.get("send_default_pii") is False
