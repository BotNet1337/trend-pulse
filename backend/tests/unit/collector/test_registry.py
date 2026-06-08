"""AC7 — registry: TELEGRAM registered, TWITTER declared but NOT registered."""

import pytest

from collector import registry
from collector.base import SourceKind
from collector.errors import PoolConfigError
from collector.telegram.reader import TelegramCollector


def test_telegram_is_registered() -> None:
    assert registry.is_registered(SourceKind.TELEGRAM)


def test_twitter_is_declared_but_not_registered() -> None:
    # Declared in the enum as a future marker...
    assert SourceKind.TWITTER.value == "twitter"
    # ...but no collector is registered for it (ADR-001 scope guard).
    assert not registry.is_registered(SourceKind.TWITTER)
    with pytest.raises(KeyError):
        registry.get(SourceKind.TWITTER)


def test_build_telegram_collector_fails_fast_without_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("TELEGRAM_POOL_SESSIONS", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(PoolConfigError):
            registry._build_telegram_collector()
    finally:
        get_settings.cache_clear()


def test_get_telegram_returns_telegram_collector() -> None:
    # Register a test factory (no real telethon sessions needed) and assert `get`
    # returns and caches a TelegramCollector for TELEGRAM.
    from .conftest import FakeClient, make_pool

    def build() -> TelegramCollector:
        pool = make_pool([FakeClient(), FakeClient(), FakeClient()])
        return TelegramCollector(pool)

    registry.register(SourceKind.TELEGRAM, build)
    try:
        collector = registry.get(SourceKind.TELEGRAM)
        assert isinstance(collector, TelegramCollector)
        assert collector.kind is SourceKind.TELEGRAM
        # Cached: second get returns the same instance.
        assert registry.get(SourceKind.TELEGRAM) is collector
    finally:
        # Restore the production factory so other tests/modules see the default.
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)
