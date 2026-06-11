"""Unit tests for alerts.formatting.build_reply_markup — AC1 (TASK-042).

AC1: Given an alert is delivered via TelegramBotBackend, the payload contains
reply_markup with two URL buttons 👍/👎 with valid signed tokens.

Pure compute (no DB / no network) — runs under `make ci-fast`.
"""

from datetime import UTC, datetime

import pytest

from alerts.feedback_tokens import verify_feedback_token
from alerts.formatting import AlertView, build_reply_markup

_JWT_SECRET = "test-jwt-secret-for-markup"
_TTL = 604800
_BASE_URL = "https://app.example.com"

_VIEW = AlertView(
    topic="crypto",
    title="Bitcoin ETF approval",
    score=94.0,
    channels_count=47,
    first_seen=datetime(2025, 6, 8, 14, 2, 0, tzinfo=UTC),
    velocity=2.3,
)


def test_build_reply_markup_has_two_buttons() -> None:
    """reply_markup contains exactly two inline keyboard buttons."""
    markup = build_reply_markup(
        view=_VIEW,
        alert_id=42,
        jwt_secret=_JWT_SECRET,
        public_base_url=_BASE_URL,
        ttl_seconds=_TTL,
    )
    assert markup is not None
    keyboard = markup["inline_keyboard"]
    assert isinstance(keyboard, list)
    assert len(keyboard) == 1  # one row
    buttons = keyboard[0]
    assert len(buttons) == 2


def test_build_reply_markup_buttons_are_url_type() -> None:
    """Both buttons have a 'url' field (not callback_data)."""
    markup = build_reply_markup(
        view=_VIEW,
        alert_id=42,
        jwt_secret=_JWT_SECRET,
        public_base_url=_BASE_URL,
        ttl_seconds=_TTL,
    )
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    for btn in buttons:
        assert "url" in btn
        assert "callback_data" not in btn


def test_build_reply_markup_up_button() -> None:
    """👍 button URL contains a valid 'up' token for the given alert_id."""
    markup = build_reply_markup(
        view=_VIEW,
        alert_id=55,
        jwt_secret=_JWT_SECRET,
        public_base_url=_BASE_URL,
        ttl_seconds=_TTL,
    )
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    up_btn = next((b for b in buttons if "👍" in b.get("text", "")), None)
    assert up_btn is not None

    url = up_btn["url"]
    assert url.startswith(_BASE_URL)
    assert "/api/v1/feedback/" in url

    # Extract token and verify it
    token = url.split("/api/v1/feedback/")[-1]
    payload = verify_feedback_token(token, jwt_secret=_JWT_SECRET)
    assert payload["alert_id"] == 55
    assert payload["verdict"] == "up"


def test_build_reply_markup_down_button() -> None:
    """👎 button URL contains a valid 'down' token for the given alert_id."""
    markup = build_reply_markup(
        view=_VIEW,
        alert_id=55,
        jwt_secret=_JWT_SECRET,
        public_base_url=_BASE_URL,
        ttl_seconds=_TTL,
    )
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    down_btn = next((b for b in buttons if "👎" in b.get("text", "")), None)
    assert down_btn is not None

    url = down_btn["url"]
    token = url.split("/api/v1/feedback/")[-1]
    payload = verify_feedback_token(token, jwt_secret=_JWT_SECRET)
    assert payload["alert_id"] == 55
    assert payload["verdict"] == "down"


def test_build_reply_markup_empty_base_url_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When public_base_url is empty, build_reply_markup returns None (graceful degradation)."""
    import logging

    with caplog.at_level(logging.WARNING):
        result = build_reply_markup(
            view=_VIEW,
            alert_id=1,
            jwt_secret=_JWT_SECRET,
            public_base_url="",
            ttl_seconds=_TTL,
        )
    assert result is None


def test_telegram_backend_includes_reply_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TelegramBotBackend.send includes reply_markup in the sendMessage body when markup is set."""
    import httpx

    from alerts.backends import TelegramBotBackend, TelegramTarget

    calls: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, "json": kwargs.get("json")})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("alerts.backends.httpx.post", _fake_post)

    backend = TelegramBotBackend(
        base_url="https://api.telegram.org",
        timeout_seconds=10,
        jwt_secret=_JWT_SECRET,
        public_base_url=_BASE_URL,
        feedback_token_ttl_seconds=_TTL,
    )
    backend.send(_VIEW, TelegramTarget(bot_token="tok", chat_id="123"), alert_id=42)

    assert len(calls) == 1
    body = calls[0]["json"]
    assert isinstance(body, dict)
    assert "reply_markup" in body
    markup = body["reply_markup"]
    assert isinstance(markup, dict)
    assert "inline_keyboard" in markup


def test_telegram_backend_no_reply_markup_when_base_url_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When public_base_url is empty, reply_markup is absent from sendMessage body."""
    import httpx

    from alerts.backends import TelegramBotBackend, TelegramTarget

    calls: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, "json": kwargs.get("json")})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("alerts.backends.httpx.post", _fake_post)

    backend = TelegramBotBackend(
        base_url="https://api.telegram.org",
        timeout_seconds=10,
        jwt_secret=_JWT_SECRET,
        public_base_url="",  # empty → no markup
        feedback_token_ttl_seconds=_TTL,
    )
    backend.send(_VIEW, TelegramTarget(bot_token="tok", chat_id="123"), alert_id=42)

    body = calls[0]["json"]
    assert isinstance(body, dict)
    assert "reply_markup" not in body
