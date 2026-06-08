"""AC2/AC3 — Telegram + webhook backends over a mocked httpx (network-free).

AC2: `TelegramBotBackend.send` POSTs `sendMessage` with `chat_id`+`text`.
AC3: `WebhookBackend.send` POSTs the overview §4 JSON payload.
Error mapping (both backends): 429/5xx → TransientDeliveryError, other 4xx →
PermanentDeliveryError, network error → transient. SSRF guard fires before POST.
"""

import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from alerts.backends import (
    DeliveryResult,
    TelegramBotBackend,
    TelegramTarget,
    WebhookBackend,
    WebhookTarget,
)
from alerts.errors import (
    PermanentDeliveryError,
    TransientDeliveryError,
    WebhookValidationError,
)
from alerts.formatting import AlertView

_VIEW = AlertView(
    topic="crypto",
    title="Bitcoin ETF approval",
    score=94.0,
    channels_count=47,
    first_seen=datetime(2025, 6, 8, 14, 2, 0, tzinfo=UTC),
    velocity=2.3,
)
_BASE = "https://api.telegram.org"
_TIMEOUT = 10


class _Recorder:
    def __init__(self, status_code: int = 200) -> None:
        self.url: str | None = None
        self.json: dict[str, object] | None = None
        self.follow_redirects: bool | None = None
        self._status_code = status_code

    def __call__(self, url: str, **kwargs: object) -> httpx.Response:
        self.url = url
        self.json = kwargs.get("json")  # type: ignore[assignment]
        if "follow_redirects" in kwargs:
            self.follow_redirects = bool(kwargs["follow_redirects"])
        return httpx.Response(status_code=self._status_code, request=httpx.Request("POST", url))


def test_telegram_sends_sendmessage_with_chat_id_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder()
    monkeypatch.setattr("alerts.backends.httpx.post", rec)
    backend = TelegramBotBackend(base_url=_BASE, timeout_seconds=_TIMEOUT)

    result = backend.send(_VIEW, TelegramTarget(bot_token="secret-token", chat_id="123"))

    assert isinstance(result, DeliveryResult)
    assert result.ok
    assert rec.url == "https://api.telegram.org/botsecret-token/sendMessage"
    assert rec.json is not None
    assert rec.json["chat_id"] == "123"
    assert "🔥 Viral alert [crypto]" in str(rec.json["text"])


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, TransientDeliveryError),
        (500, TransientDeliveryError),
        (503, TransientDeliveryError),
        (401, PermanentDeliveryError),
        (403, PermanentDeliveryError),
        (400, PermanentDeliveryError),
    ],
)
def test_telegram_status_mapping(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: type[Exception]
) -> None:
    monkeypatch.setattr("alerts.backends.httpx.post", _Recorder(status_code=status))
    backend = TelegramBotBackend(base_url=_BASE, timeout_seconds=_TIMEOUT)
    with pytest.raises(expected):
        backend.send(_VIEW, TelegramTarget(bot_token="t", chat_id="1"))


def test_telegram_network_error_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("alerts.backends.httpx.post", _boom)
    backend = TelegramBotBackend(base_url=_BASE, timeout_seconds=_TIMEOUT)
    with pytest.raises(TransientDeliveryError):
        backend.send(_VIEW, TelegramTarget(bot_token="t", chat_id="1"))


def _getaddrinfo_returning(ip: str) -> Callable[..., list[object]]:
    def _resolver(host: str, *a: object, **k: object) -> list[object]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    return _resolver


def _install_recording_transport(
    monkeypatch: pytest.MonkeyPatch, *, status_code: int = 200
) -> dict[str, object]:
    """Make `WebhookBackend` use the REAL `PinnedIPTransport` resolve/validate/pin
    logic, but capture the rewritten request and return a canned response instead
    of opening a socket. `seen` reflects the address the connection is pinned to,
    plus the preserved Host header and TLS SNI hostname.
    """
    import alerts.security as security

    seen: dict[str, object] = {"pinned_ip": None, "host_header": None, "sni": None, "body": None}

    def _record(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.scheme != security._ALLOWED_SCHEME:
            raise WebhookValidationError("scheme")
        # Real resolve + validate (raises on a private/loopback IP) → pin to the IP.
        validated_ip = security.resolve_and_validate_host(host)
        seen["pinned_ip"] = validated_ip
        seen["host_header"] = host
        seen["sni"] = host
        seen["body"] = request.read()
        return httpx.Response(status_code=status_code, request=httpx.Request("POST", request.url))

    monkeypatch.setattr(security.PinnedIPTransport, "handle_request", _record)
    return seen


def test_webhook_posts_overview_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alerts.security.socket.getaddrinfo", _getaddrinfo_returning("93.184.216.34")
    )
    seen = _install_recording_transport(monkeypatch)
    backend = WebhookBackend(timeout_seconds=_TIMEOUT)

    result = backend.send(_VIEW, WebhookTarget(url="https://hooks.example.com/x"))

    assert result.ok
    # Connection pinned to the validated public IP; hostname preserved for Host + SNI.
    assert seen["pinned_ip"] == "93.184.216.34"
    assert seen["host_header"] == "hooks.example.com"
    assert seen["sni"] == "hooks.example.com"
    assert seen["body"] is not None
    assert json.loads(str(seen["body"], "utf-8")) == {
        "event": "viral_alert",
        "topic": "crypto",
        "title": "Bitcoin ETF approval",
        "score": 94,
        "channels_count": 47,
        "first_seen": "2025-06-08T14:02:00+00:00",
        "velocity": 2.3,
    }


def test_webhook_ssrf_reject_blocks_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """A loopback host must raise `WebhookValidationError` and open NO socket.

    The real `PinnedIPTransport` resolves + validates inside `handle_request`; if
    it ever reaches the socket layer we fail the test (no bytes may leave).
    """
    monkeypatch.setattr("alerts.security.socket.getaddrinfo", _getaddrinfo_returning("127.0.0.1"))

    def _no_socket(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        msg = "socket must never be opened for a blocked SSRF target"
        raise AssertionError(msg)

    # If validation failed to fire, the parent (socket) handler would run → fail.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_socket)
    backend = WebhookBackend(timeout_seconds=_TIMEOUT)
    with pytest.raises(WebhookValidationError):
        backend.send(_VIEW, WebhookTarget(url="https://attacker.example.com/x"))


def test_webhook_dns_rebinding_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """TOCTOU / DNS-rebinding: an attacker returns a PUBLIC IP at validation time
    and a PRIVATE/loopback IP at connect time. The old code (validate-then-post,
    two independent resolutions) was bypassable. The fix makes the connect use the
    SAME resolution it validates, so the loopback answer is caught and NO socket is
    opened.

    `getaddrinfo` is rigged to flip: 1st call (a hypothetical separate pre-check)
    returns public; every later call (the resolution the transport actually
    connects with) returns loopback.
    """
    from alerts.security import validate_webhook_url

    calls = {"n": 0}

    def _rebinding_getaddrinfo(host: str, *a: object, **k: object) -> list[object]:
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr("alerts.security.socket.getaddrinfo", _rebinding_getaddrinfo)

    # A separate pre-validation would have PASSED (attacker served a public IP)...
    validate_webhook_url("https://attacker.example.com/x")

    # ...but the transport re-resolves AT CONNECT and now gets loopback → blocked.
    # A net to catch any attempt to actually open a socket past the guard.
    def _no_socket(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        msg = "DNS-rebinding bypass: socket opened to a re-resolved private IP"
        raise AssertionError(msg)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_socket)
    backend = WebhookBackend(timeout_seconds=_TIMEOUT)
    with pytest.raises(WebhookValidationError):
        backend.send(_VIEW, WebhookTarget(url="https://attacker.example.com/x"))


def test_webhook_5xx_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alerts.security.socket.getaddrinfo", _getaddrinfo_returning("93.184.216.34")
    )
    _install_recording_transport(monkeypatch, status_code=502)
    backend = WebhookBackend(timeout_seconds=_TIMEOUT)
    with pytest.raises(TransientDeliveryError):
        backend.send(_VIEW, WebhookTarget(url="https://hooks.example.com/x"))


def test_telegram_target_repr_redacts_bot_token() -> None:
    target = TelegramTarget(bot_token="super-secret-token", chat_id="123")
    assert "super-secret-token" not in repr(target)
    assert "123" in repr(target)
