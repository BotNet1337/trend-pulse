"""TASK-139 — FakeProxyProvider unit tests (deterministic, no network).

`allocate(country)` returns a deterministic `socks5://` lease with a non-empty
`lease_id` and the requested country; `release` records the id and never raises;
`balance` returns a `Decimal`. The provider structurally satisfies `ProxyProvider`.
"""

from __future__ import annotations

from decimal import Decimal

from factory.proxy.base import ProxyLease, ProxyProvider
from factory.proxy.fake import FAKE_PROXY_SCHEME, FakeProxyProvider


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProxyProvider(), ProxyProvider)


async def test_fake_allocate_returns_socks5_lease_with_country() -> None:
    provider = FakeProxyProvider()
    lease = await provider.allocate("KE")
    assert isinstance(lease, ProxyLease)
    assert lease.uri.startswith(f"{FAKE_PROXY_SCHEME}://")
    assert lease.lease_id
    assert lease.country == "KE"


async def test_fake_allocate_none_country_is_allowed() -> None:
    provider = FakeProxyProvider()
    lease = await provider.allocate(None)
    assert lease.country is None
    assert lease.uri.startswith(f"{FAKE_PROXY_SCHEME}://")


async def test_fake_allocate_lease_ids_are_unique() -> None:
    provider = FakeProxyProvider()
    first = await provider.allocate("KE")
    second = await provider.allocate("KE")
    assert first.lease_id != second.lease_id


async def test_fake_release_records_id_and_never_raises() -> None:
    provider = FakeProxyProvider()
    lease = await provider.allocate("KE")
    assert await provider.release(lease.lease_id) is None
    assert lease.lease_id in provider.released_ids


async def test_fake_release_unknown_id_does_not_raise() -> None:
    provider = FakeProxyProvider()
    assert await provider.release("never-allocated") is None
    assert "never-allocated" in provider.released_ids


async def test_fake_balance_is_deterministic_decimal() -> None:
    provider = FakeProxyProvider(balance=Decimal("42.50"))
    result = await provider.balance()
    assert isinstance(result, Decimal)
    assert result == Decimal("42.50")


async def test_fake_aclose_is_noop() -> None:
    provider = FakeProxyProvider()
    assert await provider.aclose() is None
