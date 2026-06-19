"""registry: TELEGRAM + TWITTER registered (TASK-031 superseded task-005 AC7)."""

import pytest

from collector import registry
from collector.base import SourceKind
from collector.constants import POOL_MAX
from collector.errors import PoolConfigError
from collector.telegram.account_pool import AccountPool, session_fingerprint
from collector.telegram.reader import TelegramCollector
from storage.pool_session_store import StoredSession

from .conftest import FakeClient


def test_telegram_is_registered() -> None:
    assert registry.is_registered(SourceKind.TELEGRAM)


def test_twitter_is_registered() -> None:
    # TASK-031: TWITTER is now a registered source (was a future-marker only under
    # task-005 AC7). The factory still fails fast without a Bearer token (lazy),
    # so an unconfigured deploy is a warn-once no-op tick, not a crash.
    assert SourceKind.TWITTER.value == "twitter"
    assert registry.is_registered(SourceKind.TWITTER)


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


def test_union_truncates_to_pool_max_when_db_plus_env_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASK-119 HIGH fix: DB rows at POOL_MAX + a UNIQUE env session must NOT make the
    union exceed POOL_MAX (which would crash `from_sessions`). The union truncates to the
    cap, DB-first, so the live identity-keyed slots survive — deterministically."""
    db_rows = [
        StoredSession(
            tg_user_id=900_000 + i,
            fingerprint=session_fingerprint(f"1AbCdb-session-{i}"),
            display_label=f"@db{i}",
            session_string=f"1AbCdb-session-{i}",
        )
        for i in range(POOL_MAX)
    ]
    monkeypatch.setattr(registry, "_load_db_store_sessions", lambda: db_rows)

    env_only = "1AbCenv-only-unique-bootstrap"
    # TASK-129: _union_pool_sessions now returns a 4-tuple (sessions, tg_user_ids,
    # display_labels, proxies).
    sessions, tg_user_ids, display_labels, proxies = registry._union_pool_sessions(
        env_sessions=[env_only],
        fingerprint=session_fingerprint,
    )

    # Truncated to the cap (NOT POOL_MAX + 1) — DB-first, so the env overflow is dropped.
    assert len(sessions) == POOL_MAX
    assert len(tg_user_ids) == POOL_MAX
    assert len(display_labels) == POOL_MAX  # positional with sessions (TASK-120)
    assert len(proxies) == POOL_MAX  # TASK-129: proxies list is positional with sessions
    assert env_only not in sessions  # the env overflow slot was dropped (DB-first)
    assert all(tid is not None for tid in tg_user_ids)  # every surviving slot is a DB row
    assert all(label is not None for label in display_labels)  # DB rows carry labels


def test_from_sessions_builds_at_cap_not_raises_on_overflowing_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end of the HIGH fix: the truncated union builds a pool of size==POOL_MAX
    via `from_sessions` (NOT a PoolConfigError raise → ingest stays up)."""
    db_rows = [
        StoredSession(
            tg_user_id=900_000 + i,
            fingerprint=session_fingerprint(f"1AbCdb-session-{i}"),
            display_label=f"@db{i}",
            session_string=f"1AbCdb-session-{i}",
        )
        for i in range(POOL_MAX)
    ]
    monkeypatch.setattr(registry, "_load_db_store_sessions", lambda: db_rows)

    # TASK-129: _union_pool_sessions now returns a 4-tuple (sessions, tg_user_ids,
    # display_labels, proxies).
    sessions, tg_user_ids, display_labels, proxies = registry._union_pool_sessions(
        env_sessions=["1AbCenv-only-unique-bootstrap"],
        fingerprint=session_fingerprint,
    )

    pool = AccountPool.from_sessions(
        sessions=sessions,
        factory=lambda _s, _p=None: FakeClient(),
        tg_user_ids=tg_user_ids,
        display_labels=display_labels,
        proxies=proxies,
    )
    assert pool.size == POOL_MAX


def test_get_telegram_returns_telegram_collector() -> None:
    # Register a test factory (no real telethon sessions needed) and assert `get`
    # returns and caches a TelegramCollector for TELEGRAM.
    from .conftest import make_pool

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


def test_invalidate_pops_and_next_get_rebuilds_fresh() -> None:
    """fix/pool-live-pickup: `invalidate` drops the cache so the NEXT `get` rebuilds.

    This is the live-pickup path — a session QR-added after the pool was built sits in the
    store, unused, until the cache is invalidated and the next tick rebuilds from DB + env.
    """
    from .conftest import FakeClient, make_pool

    built: list[TelegramCollector] = []

    def build() -> TelegramCollector:
        collector = TelegramCollector(make_pool([FakeClient()]))
        built.append(collector)
        return collector

    registry.register(SourceKind.TELEGRAM, build)
    try:
        first = registry.get(SourceKind.TELEGRAM)
        popped = registry.invalidate(SourceKind.TELEGRAM)
        assert popped is first  # the cached instance is returned for the caller to aclose
        second = registry.get(SourceKind.TELEGRAM)
        assert second is not first  # rebuilt fresh from the (store-backed) factory
        assert len(built) == 2
    finally:
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)


def test_invalidate_on_empty_cache_is_a_noop() -> None:
    """`invalidate` returns None when nothing was cached (no build happened yet)."""
    from .conftest import FakeClient, make_pool

    registry.register(SourceKind.TELEGRAM, lambda: TelegramCollector(make_pool([FakeClient()])))
    try:
        # No get() yet → nothing cached.
        assert registry.invalidate(SourceKind.TELEGRAM) is None
    finally:
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)


@pytest.mark.asyncio
async def test_ainvalidate_acloses_old_before_pop_and_rebuild() -> None:
    """AuthKeyDuplicated invariant: `ainvalidate` DISCONNECTS the old collector (aclose)
    BEFORE the cache is empty for a rebuild — so a session is never connected on two clients
    at once. Asserts the old pool's clients were disconnected and the next get rebuilds."""
    from .conftest import FakeClient, make_pool

    old_clients = [FakeClient(), FakeClient()]
    built: list[TelegramCollector] = []

    def build() -> TelegramCollector:
        # First build uses the tracked clients; later builds use fresh ones.
        clients = old_clients if not built else [FakeClient()]
        collector = TelegramCollector(make_pool(clients))
        built.append(collector)
        return collector

    registry.register(SourceKind.TELEGRAM, build)
    try:
        first = registry.get(SourceKind.TELEGRAM)
        # Connect the pool clients so aclose has something to disconnect.
        for c in old_clients:
            await c.connect()
        assert all(c.is_connected() for c in old_clients)

        await registry.ainvalidate(SourceKind.TELEGRAM)

        # aclose-before-rebuild: every OLD client is disconnected (the invariant).
        assert all(c.disconnect_calls >= 1 for c in old_clients)
        assert not any(c.is_connected() for c in old_clients)
        # The cache is empty → the next get rebuilds a DIFFERENT collector.
        second = registry.get(SourceKind.TELEGRAM)
        assert second is not first
    finally:
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)


@pytest.mark.asyncio
async def test_ainvalidate_on_empty_cache_is_a_noop() -> None:
    """`ainvalidate` is safe with nothing cached (no aclose, no raise)."""
    from .conftest import FakeClient, make_pool

    registry.register(SourceKind.TELEGRAM, lambda: TelegramCollector(make_pool([FakeClient()])))
    try:
        await registry.ainvalidate(SourceKind.TELEGRAM)  # must not raise
    finally:
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)
