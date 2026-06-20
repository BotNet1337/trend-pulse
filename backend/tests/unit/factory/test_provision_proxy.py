"""TASK-140 — `_provision` allocates / registers-through / releases a dynamic proxy.

When a `ProxyProvider` is wired, `_provision` must:
  * allocate a lease AFTER a number is secured (never hold a proxy without a number);
  * register over `lease.uri` and return the lease so the caller persists it;
  * on registration failure: cancel the number AND release the lease (both best-effort,
    never masking the original error);
  * on allocate failure: cancel the number and re-raise (never hold a number alone).

No network, no DB — `FakeProxyProvider` + recording SMS provider / registrar.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.errors import RegistrarBannedError
from factory.providers.base import PurchasedNumber
from factory.proxy.base import ProxyLease
from factory.proxy.fake import FakeProxyProvider
from factory.registrar.base import RegisteredSession
from factory.tasks import _provision

_COUNTRY = "RU"


class _RecordingProvider:
    """A minimal SmsProvider recording finish/cancel + the proxy register received."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.finished: list[str] = []

    async def balance(self) -> Decimal:
        return Decimal("10.00")

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        return PurchasedNumber(order_id="o1", phone="+70000000000")

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        return "123456"

    async def finish(self, order_id: str) -> None:
        self.finished.append(order_id)

    async def cancel(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    async def aclose(self) -> None:
        return None


class _CapturingOkRegistrar:
    """Succeeds; records the proxy URI it was asked to register over."""

    def __init__(self) -> None:
        self.proxies: list[str | None] = []

    async def register(self, *, phone, code_cb, proxy=None):  # type: ignore[no-untyped-def]
        self.proxies.append(proxy)
        await code_cb()
        return RegisteredSession(session_string="1Aok", tg_user_id=42)


class _FailingRegistrar:
    """Consumes the code then fails — as Telegram rejects SMS numbers."""

    def __init__(self) -> None:
        self.proxies: list[str | None] = []

    async def register(self, *, phone, code_cb, proxy=None):  # type: ignore[no-untyped-def]
        self.proxies.append(proxy)
        await code_cb()
        raise RegistrarBannedError("telegram banned this phone number")


class _FailingProxyProvider:
    """A ProxyProvider whose `allocate` fails (records `released_ids` for the contract)."""

    def __init__(self) -> None:
        self.released_ids: set[str] = set()

    async def allocate(self, country):  # type: ignore[no-untyped-def]
        raise RuntimeError("proxy provider out of stock")

    async def release(self, lease_id: str) -> None:
        self.released_ids.add(lease_id)

    async def balance(self) -> Decimal:
        return Decimal("0")

    async def aclose(self) -> None:
        return None


async def test_provision_allocates_and_registers_through_proxy() -> None:
    provider = _RecordingProvider()
    proxy_provider = FakeProxyProvider()
    registrar = _CapturingOkRegistrar()

    purchased, registered, lease = await _provision(
        provider,
        registrar,
        proxy_provider=proxy_provider,
        country=_COUNTRY,
        static_proxy=None,
    )

    assert purchased.order_id == "o1"
    assert registered.tg_user_id == 42
    assert isinstance(lease, ProxyLease)
    # register ran over the leased uri; the lease carries the requested country.
    assert registrar.proxies == [lease.uri]
    assert lease.country == _COUNTRY
    # success: number finished, nothing cancelled, lease NOT released (sticky).
    assert provider.finished == ["o1"]
    assert provider.cancelled == []
    assert proxy_provider.released_ids == set()


async def test_provision_releases_proxy_and_cancels_number_on_register_fail() -> None:
    provider = _RecordingProvider()
    proxy_provider = FakeProxyProvider()
    registrar = _FailingRegistrar()

    with pytest.raises(RegistrarBannedError):
        await _provision(
            provider,
            registrar,
            proxy_provider=proxy_provider,
            country=_COUNTRY,
            static_proxy=None,
        )

    # number released, finish NOT called, and the lease released once (best-effort).
    assert provider.cancelled == ["o1"]
    assert provider.finished == []
    assert len(proxy_provider.released_ids) == 1


async def test_provision_cancels_number_when_allocate_fails() -> None:
    provider = _RecordingProvider()
    proxy_provider = _FailingProxyProvider()
    registrar = _CapturingOkRegistrar()

    with pytest.raises(RuntimeError):
        await _provision(
            provider,
            registrar,
            proxy_provider=proxy_provider,
            country=_COUNTRY,
            static_proxy=None,
        )

    # the number was bought then released; registration never ran; nothing to release.
    assert provider.cancelled == ["o1"]
    assert provider.finished == []
    assert registrar.proxies == []
    assert proxy_provider.released_ids == set()


async def test_provision_static_proxy_path_returns_no_lease() -> None:
    """No provider → register over the static proxy, return lease=None (byte-compat)."""
    provider = _RecordingProvider()
    registrar = _CapturingOkRegistrar()
    static = "socks5://user:pass@10.0.0.1:1080"

    _purchased, _registered, lease = await _provision(
        provider,
        registrar,
        proxy_provider=None,
        country=_COUNTRY,
        static_proxy=static,
    )

    assert lease is None
    assert registrar.proxies == [static]
    assert provider.finished == ["o1"]
    assert provider.cancelled == []
