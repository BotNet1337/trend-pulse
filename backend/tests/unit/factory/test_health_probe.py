"""TASK-141 — health-probe unit tests (deterministic, no network).

`FakeHealthProbe` is the CI-safe deterministic probe; `TelethonHealthProbe` is the
real one, exercised here with an INJECTED fake telethon client (no network). The
session string + proxy URI MUST NEVER appear in a log line or in a `HealthResult.reason`.
"""

from __future__ import annotations

import logging

import pytest

from config import Settings, get_settings
from factory.health.base import HealthProbe, HealthResult
from factory.health.factory import get_health_probe
from factory.health.fake import FakeHealthProbe
from factory.health.telethon import TelethonHealthProbe

_SESSION = "1AsuperSECRETsessionSTRINGdonotlog"
_PROXY = "socks5://secretuser:secretpass@10.9.8.7:1080"


def test_fake_probe_satisfies_protocol() -> None:
    assert isinstance(FakeHealthProbe(), HealthProbe)


async def test_fake_probe_ok_by_default() -> None:
    result = await FakeHealthProbe().check(session_string=_SESSION, proxy=_PROXY)
    assert result == HealthResult(ok=True, reason=None)


async def test_fake_probe_can_fail() -> None:
    result = await FakeHealthProbe(ok=False).check(session_string=_SESSION, proxy=None)
    assert result.ok is False


# --- TelethonHealthProbe with an injected fake telethon client (no network). ---


class _FakeMessage:
    """A single message stand-in (only its presence in the list matters)."""


class _BaseFakeClient:
    """Records connect/disconnect; resolves an entity; returns a scripted message list."""

    def __init__(self, session: object, api_id: int, api_hash: str, proxy: object = None) -> None:
        self.session = session
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def get_entity(self, channel: str) -> object:
        return object()


class _PassthroughStringSession:
    """A StringSession stand-in that stores the raw string verbatim (no base64 decode).

    The real `StringSession(s)` base64-decodes `s` in its constructor; the probe's logic
    is independent of that, so we swap it out to let an arbitrary SECRET test string flow
    through unchanged (and prove it never reaches a log line or the result reason).
    """

    def __init__(self, value: str = "") -> None:
        self.value = value


def _patch_client(monkeypatch: pytest.MonkeyPatch, client_cls: type) -> dict[str, object]:
    """Monkeypatch `telethon.TelegramClient` (+ StringSession) ; return the captured instance."""
    import telethon
    import telethon.sessions

    captured: dict[str, object] = {}

    def _factory(session: object, api_id: int, api_hash: str, proxy: object = None) -> object:
        instance = client_cls(session, api_id, api_hash, proxy=proxy)
        captured["client"] = instance
        return instance

    monkeypatch.setattr(telethon, "TelegramClient", _factory)
    monkeypatch.setattr(telethon.sessions, "StringSession", _PassthroughStringSession)
    return captured


async def test_telethon_probe_ok_when_message_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReadOne(_BaseFakeClient):
        async def get_messages(self, channel: str, limit: int) -> list[_FakeMessage]:
            return [_FakeMessage()]

    captured = _patch_client(monkeypatch, _ReadOne)
    probe = TelethonHealthProbe(api_id=1, api_hash="h", channel="@durov", read_limit=1)

    result = await probe.check(session_string=_SESSION, proxy=_PROXY)

    assert result.ok is True
    assert result.reason is None
    assert captured["client"].disconnected is True  # always disconnects


async def test_telethon_probe_fail_when_zero_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReadNone(_BaseFakeClient):
        async def get_messages(self, channel: str, limit: int) -> list[_FakeMessage]:
            return []

    captured = _patch_client(monkeypatch, _ReadNone)
    probe = TelethonHealthProbe(api_id=1, api_hash="h", channel="@durov", read_limit=1)

    result = await probe.check(session_string=_SESSION, proxy=None)

    assert result.ok is False
    assert captured["client"].disconnected is True


async def test_telethon_probe_fail_with_exc_class_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom(_BaseFakeClient):
        async def get_messages(self, channel: str, limit: int) -> list[_FakeMessage]:
            raise RuntimeError("the proxy died and so did this client")

    captured = _patch_client(monkeypatch, _Boom)
    probe = TelethonHealthProbe(api_id=1, api_hash="h", channel="@durov", read_limit=1)

    result = await probe.check(session_string=_SESSION, proxy=_PROXY)

    assert result.ok is False
    assert result.reason == "RuntimeError"  # class name only — no message, no secret
    # The client connected → it MUST have been disconnected even on the raise.
    assert captured["client"].disconnected is True


async def test_telethon_probe_fail_on_connect_still_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConnectBoom(_BaseFakeClient):
        async def connect(self) -> None:
            raise ConnectionError("could not reach socks5://secretuser:secretpass@host")

    _patch_client(monkeypatch, _ConnectBoom)
    probe = TelethonHealthProbe(api_id=1, api_hash="h", channel="@durov", read_limit=1)

    result = await probe.check(session_string=_SESSION, proxy=_PROXY)

    assert result.ok is False
    assert result.reason == "ConnectionError"
    assert "secret" not in (result.reason or "")  # only the class name


async def test_telethon_probe_never_logs_session_or_proxy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Boom(_BaseFakeClient):
        async def get_messages(self, channel: str, limit: int) -> list[_FakeMessage]:
            raise RuntimeError("boom socks5://secretuser:secretpass@10.9.8.7:1080")

    _patch_client(monkeypatch, _Boom)
    probe = TelethonHealthProbe(api_id=1, api_hash="h", channel="@durov", read_limit=1)

    with caplog.at_level(logging.DEBUG):
        result = await probe.check(session_string=_SESSION, proxy=_PROXY)

    # Neither the session string nor any part of the proxy URI may appear in logs/reason.
    haystack = caplog.text + (result.reason or "")
    assert _SESSION not in haystack
    assert "secretuser" not in haystack
    assert "secretpass" not in haystack
    assert "10.9.8.7" not in haystack


# --- get_health_probe selection (mirrors get_registrar gating). ---


def _settings_with(**overrides: object) -> Settings:
    return get_settings().model_copy(update=overrides)


def test_get_health_probe_fake_when_provider_unset() -> None:
    settings = _settings_with(
        account_factory_provider="fake",
        telegram_api_id=1,
        telegram_api_hash="h",
        account_factory_health_probe_channel="@durov",
    )
    assert isinstance(get_health_probe(settings), FakeHealthProbe)


def test_get_health_probe_fake_when_channel_empty() -> None:
    settings = _settings_with(
        account_factory_provider="smspva",
        telegram_api_id=1,
        telegram_api_hash="h",
        account_factory_health_probe_channel="",
    )
    assert isinstance(get_health_probe(settings), FakeHealthProbe)


def test_get_health_probe_fake_when_creds_missing() -> None:
    settings = _settings_with(
        account_factory_provider="smspva",
        telegram_api_id=None,
        telegram_api_hash=None,
        account_factory_health_probe_channel="@durov",
    )
    assert isinstance(get_health_probe(settings), FakeHealthProbe)


def test_get_health_probe_real_when_fully_configured() -> None:
    settings = _settings_with(
        account_factory_provider="smspva",
        telegram_api_id=1,
        telegram_api_hash="h",
        account_factory_health_probe_channel="@durov",
    )
    assert isinstance(get_health_probe(settings), TelethonHealthProbe)
