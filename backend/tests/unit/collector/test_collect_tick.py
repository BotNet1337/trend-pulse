"""collect-tick — the beat ingest task wiring collector/ into the runtime.

Launch-blocker fix: before this task existed nothing ever called
`registry.get(kind).read(...)` / `collector.buffer.write_post`, so every
`process_user_batch` drained an empty buffer (prod: permanent `warming_up`).

Infra-free unit tests: fake collector + fakeredis; no Telethon, no Postgres.
Covers: beat entry from settings, DISTINCT ref gathering, RawPost →
`write_post` wiring + the `since` last-tick marker, flood/source errors that
skip a ref without killing the tick, unconfigured pool → warn-once no-op, and
the global Redis lock (overlapping ticks are a clean no-op).
"""

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from collector import registry, tasks
from collector.base import PostMetrics, RawPost, SourceCollector, SourceKind, SourceRef
from collector.buffer import buffer_key
from collector.constants import COLLECT_LAST_TICK_KEY, RAW_POST_TTL_SECONDS
from collector.errors import (
    AllAccountsFloodWaitError,
    CollectorError,
    PoolConfigError,
    SourceUnavailableError,
)
from collector.locks import (
    acquire_collect_tick_lock,
    collect_tick_lock,
    release_collect_tick_lock,
)
from config import get_settings

_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _make_post(handle: str, external_id: str) -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle=handle),
        external_id=external_id,
        author="Author",
        text="hi",
        media_hashes=(),
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=_NOW - timedelta(minutes=1),
    )


class FakeCollector:
    """SourceCollector double: yields canned posts per handle, can raise per handle."""

    kind = SourceKind.TELEGRAM

    def __init__(
        self,
        posts_by_handle: dict[str, list[RawPost]] | None = None,
        raise_for: dict[str, Exception] | None = None,
    ) -> None:
        self._posts_by_handle = posts_by_handle or {}
        self._raise_for = raise_for or {}
        self.read_calls: list[tuple[list[SourceRef], datetime | None]] = []

    async def validate_ref(self, ref: SourceRef) -> bool:
        return True

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        self.read_calls.append((list(refs), since))
        for ref in refs:
            error = self._raise_for.get(ref.handle)
            if error is not None:
                raise error
            for post in self._posts_by_handle.get(ref.handle, []):
                yield post


@contextmanager
def _registered(collector_factory: Callable[[], SourceCollector]) -> Iterator[None]:
    """Register a test factory for TELEGRAM; restore the production one after."""
    registry.register(SourceKind.TELEGRAM, collector_factory)
    try:
        yield
    finally:
        registry.register(SourceKind.TELEGRAM, registry._build_telegram_collector)


@contextmanager
def _fake_session() -> Iterator[MagicMock]:
    yield MagicMock(name="session")


def _patch_refs(refs: list[SourceRef]) -> object:
    return patch.object(tasks, "watched_source_refs", return_value=refs)


# ---------------------------------------------------------------------------
# Beat schedule + settings
# ---------------------------------------------------------------------------


def test_beat_schedule_has_collect_tick_entry_with_config_interval() -> None:
    from collector.constants import COLLECT_TICK_TASK
    from scheduler import beat_schedule

    settings = get_settings()
    entry = beat_schedule["collect-tick"]
    assert entry["task"] == COLLECT_TICK_TASK
    assert entry["schedule"] == float(settings.collect_interval_seconds)


def test_collect_ticks_at_least_as_often_as_batch() -> None:
    # The batch drains what collect wrote: a slower collect starves every batch
    # into a no-op, so collect must tick at least as often as batch.
    settings = get_settings()
    assert settings.collect_interval_seconds <= settings.batch_interval_seconds
    assert settings.collect_interval_seconds == 60
    assert settings.collect_lookback_seconds == 600


def test_collect_tick_task_is_registered_on_celery_app() -> None:
    import collector.tasks  # noqa: F401  (import for registration side effect)
    from celery_app import celery_app
    from collector.constants import COLLECT_TICK_TASK

    assert COLLECT_TICK_TASK in celery_app.tasks
    assert "collector.tasks" in celery_app.conf.include


def test_collect_tick_has_soft_and_hard_time_limits() -> None:
    # Safety net for the pool=1 prod hang: a wedged read must free the celery
    # slot — soft limit = the lock TTL (a tick may use its whole lock window),
    # hard limit = soft + a small grace so even a stuck cleanup is recycled.
    import collector.tasks  # noqa: F401  (import for registration side effect)
    from celery_app import celery_app
    from collector.constants import (
        COLLECT_TICK_HARD_LIMIT_GRACE_SECONDS,
        COLLECT_TICK_TASK,
    )

    settings = get_settings()
    task = celery_app.tasks[COLLECT_TICK_TASK]
    assert task.soft_time_limit == settings.collect_lock_ttl_seconds
    assert task.time_limit == (
        settings.collect_lock_ttl_seconds + COLLECT_TICK_HARD_LIMIT_GRACE_SECONDS
    )


def test_collect_tick_soft_time_limit_is_partial_run_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # SoftTimeLimitExceeded mid-read is a VALID partial tick (already-buffered
    # posts stay buffered) — warn specifically, never crash beat.
    from celery.exceptions import SoftTimeLimitExceeded

    @contextmanager
    def _acquired(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield True

    with (
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "collect_tick_lock", _acquired),
        patch.object(tasks, "collect_watched_sources", side_effect=SoftTimeLimitExceeded()),
        caplog.at_level(logging.WARNING),
    ):
        tasks.collect_tick()  # must not raise

    assert any("soft time limit" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# DISTINCT ref gathering
# ---------------------------------------------------------------------------


def test_watched_source_refs_is_distinct_and_maps_kinds() -> None:
    from storage.models.channels import SourceKind as ChannelSourceKind

    session = MagicMock(name="session")
    session.execute.return_value.all.return_value = [
        (ChannelSourceKind.TELEGRAM, "@alpha"),
        (ChannelSourceKind.TELEGRAM, "@beta"),
    ]

    refs = tasks.watched_source_refs(session)

    assert refs == [
        SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha"),
        SourceRef(kind=SourceKind.TELEGRAM, handle="@beta"),
    ]
    # The SQL itself must be DISTINCT — a channel on many watchlists is read once.
    stmt = session.execute.call_args.args[0]
    assert "DISTINCT" in str(stmt).upper()


# ---------------------------------------------------------------------------
# Collect body: write_post wiring + since marker
# ---------------------------------------------------------------------------


def test_collect_writes_posts_to_by_source_buffer_and_sets_marker() -> None:
    redis = fakeredis.FakeRedis()
    refs = [
        SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha"),
        SourceRef(kind=SourceKind.TELEGRAM, handle="@beta"),
    ]
    collector = FakeCollector(
        posts_by_handle={
            "@alpha": [_make_post("@alpha", "1"), _make_post("@alpha", "2")],
            "@beta": [_make_post("@beta", "7")],
        }
    )

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
    ):
        written = tasks.collect_watched_sources(redis, now=_NOW)

    assert written == 3
    assert redis.llen(buffer_key(SourceKind.TELEGRAM, "@alpha")) == 2
    assert redis.llen(buffer_key(SourceKind.TELEGRAM, "@beta")) == 1
    # Last-tick marker = the tick's start time, so the next tick reads from here.
    assert redis.get(COLLECT_LAST_TICK_KEY) == _NOW.isoformat().encode()


def test_first_tick_uses_lookback_window_not_full_history() -> None:
    redis = fakeredis.FakeRedis()
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")]
    collector = FakeCollector(posts_by_handle={"@alpha": [_make_post("@alpha", "1")]})

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
    ):
        tasks.collect_watched_sources(redis, now=_NOW)

    lookback = get_settings().collect_lookback_seconds
    assert collector.read_calls == [
        ([refs[0]], _NOW - timedelta(seconds=lookback)),
    ]


def test_next_tick_reads_since_previous_marker() -> None:
    redis = fakeredis.FakeRedis()
    previous = _NOW - timedelta(seconds=90)
    redis.set(COLLECT_LAST_TICK_KEY, previous.isoformat())
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")]
    collector = FakeCollector()

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
    ):
        tasks.collect_watched_sources(redis, now=_NOW)

    assert collector.read_calls[0][1] == previous


def test_stale_marker_is_clamped_to_retention_window() -> None:
    # After a long outage we never re-read beyond the 48h compliance window.
    redis = fakeredis.FakeRedis()
    redis.set(COLLECT_LAST_TICK_KEY, (_NOW - timedelta(days=5)).isoformat())
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")]
    collector = FakeCollector()

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
    ):
        tasks.collect_watched_sources(redis, now=_NOW)

    assert collector.read_calls[0][1] == _NOW - timedelta(seconds=RAW_POST_TTL_SECONDS)


def test_corrupt_marker_falls_back_to_lookback() -> None:
    redis = fakeredis.FakeRedis()
    redis.set(COLLECT_LAST_TICK_KEY, "not-a-timestamp")
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")]
    collector = FakeCollector()

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
    ):
        tasks.collect_watched_sources(redis, now=_NOW)

    lookback = get_settings().collect_lookback_seconds
    assert collector.read_calls[0][1] == _NOW - timedelta(seconds=lookback)


# ---------------------------------------------------------------------------
# Error handling: flood / unavailable source / unconfigured pool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [AllAccountsFloodWaitError("all cooling"), SourceUnavailableError("gone private")],
)
def test_failing_ref_is_skipped_but_others_are_collected(
    error: CollectorError, caplog: pytest.LogCaptureFixture
) -> None:
    redis = fakeredis.FakeRedis()
    refs = [
        SourceRef(kind=SourceKind.TELEGRAM, handle="@bad"),
        SourceRef(kind=SourceKind.TELEGRAM, handle="@good"),
    ]
    collector = FakeCollector(
        posts_by_handle={"@good": [_make_post("@good", "1")]},
        raise_for={"@bad": error},
    )

    with (
        _registered(lambda: collector),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
        caplog.at_level(logging.WARNING),
    ):
        written = tasks.collect_watched_sources(redis, now=_NOW)

    assert written == 1
    assert redis.llen(buffer_key(SourceKind.TELEGRAM, "@good")) == 1
    assert any("source skipped" in r.message for r in caplog.records)
    # The tick completed → the marker still advances.
    assert redis.get(COLLECT_LAST_TICK_KEY) is not None


def test_unconfigured_pool_is_warn_once_no_op(caplog: pytest.LogCaptureFixture) -> None:
    redis = fakeredis.FakeRedis()
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")]

    def _boom() -> SourceCollector:
        raise PoolConfigError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")

    tasks._WARNED_UNCONFIGURED_KINDS.clear()
    with (
        _registered(_boom),
        patch.object(tasks, "get_session", _fake_session),
        _patch_refs(refs),
        caplog.at_level(logging.WARNING),
    ):
        first = tasks.collect_watched_sources(redis, now=_NOW)
        second = tasks.collect_watched_sources(redis, now=_NOW)

    assert first == 0 and second == 0
    warnings = [r for r in caplog.records if "collector unconfigured" in r.message]
    assert len(warnings) == 1  # warn-once (TASK-044 / showcase pattern)
    # Nothing was attempted → the marker must NOT advance (no silent data gap).
    assert redis.get(COLLECT_LAST_TICK_KEY) is None


# ---------------------------------------------------------------------------
# Global tick lock (max_instances=1)
# ---------------------------------------------------------------------------


def test_collect_tick_skips_when_locked(caplog: pytest.LogCaptureFixture) -> None:
    @contextmanager
    def _locked(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield False

    with (
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "collect_tick_lock", _locked),
        patch.object(tasks, "collect_watched_sources") as body,
        caplog.at_level(logging.INFO),
    ):
        tasks.collect_tick()

    body.assert_not_called()
    assert any("skipped: locked" in r.message for r in caplog.records)


def test_collect_tick_runs_body_when_acquired() -> None:
    @contextmanager
    def _acquired(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield True

    redis = MagicMock()
    with (
        patch.object(tasks, "get_redis_client", return_value=redis),
        patch.object(tasks, "collect_tick_lock", _acquired),
        patch.object(tasks, "collect_watched_sources", return_value=0) as body,
    ):
        tasks.collect_tick()

    body.assert_called_once_with(redis)


def test_collect_tick_no_op_while_real_lock_held() -> None:
    """End-to-end against fakeredis: a held global lock makes the tick a no-op."""
    redis = fakeredis.FakeRedis()
    assert acquire_collect_tick_lock(redis, "in-flight", 600) is True

    with (
        patch.object(tasks, "get_redis_client", return_value=redis),
        patch.object(tasks, "collect_watched_sources") as body,
    ):
        tasks.collect_tick()

    body.assert_not_called()


def test_collect_tick_never_crashes_beat(caplog: pytest.LogCaptureFixture) -> None:
    @contextmanager
    def _acquired(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield True

    with (
        patch.object(tasks, "get_redis_client", return_value=MagicMock()),
        patch.object(tasks, "collect_tick_lock", _acquired),
        patch.object(tasks, "collect_watched_sources", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.WARNING),
    ):
        tasks.collect_tick()  # must not raise

    assert any("unexpected error" in r.message for r in caplog.records)


def test_collect_lock_acquire_release_cycle() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_collect_tick_lock(redis, "tok-a", 600) is True
    # Held → contender fails; foreign release is a no-op (owner-checked CAS).
    assert acquire_collect_tick_lock(redis, "tok-b", 600) is False
    assert release_collect_tick_lock(redis, "tok-b") is False
    assert release_collect_tick_lock(redis, "tok-a") is True
    assert acquire_collect_tick_lock(redis, "tok-b", 600) is True


def test_collect_tick_lock_context_manager_releases() -> None:
    redis = fakeredis.FakeRedis()
    with collect_tick_lock(redis, ttl=600) as acquired:
        assert acquired is True
        with collect_tick_lock(redis, ttl=600) as nested:
            assert nested is False
    # Released on exit → a new tick can acquire again.
    with collect_tick_lock(redis, ttl=600) as again:
        assert again is True
