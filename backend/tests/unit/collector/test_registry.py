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
    sessions, tg_user_ids, display_labels = registry._union_pool_sessions(
        env_sessions=[env_only],
        fingerprint=session_fingerprint,
    )

    # Truncated to the cap (NOT POOL_MAX + 1) — DB-first, so the env overflow is dropped.
    assert len(sessions) == POOL_MAX
    assert len(tg_user_ids) == POOL_MAX
    assert len(display_labels) == POOL_MAX  # positional with sessions (TASK-120)
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

    sessions, tg_user_ids, display_labels = registry._union_pool_sessions(
        env_sessions=["1AbCenv-only-unique-bootstrap"],
        fingerprint=session_fingerprint,
    )

    pool = AccountPool.from_sessions(
        sessions=sessions,
        factory=lambda _s: FakeClient(),
        tg_user_ids=tg_user_ids,
        display_labels=display_labels,
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
