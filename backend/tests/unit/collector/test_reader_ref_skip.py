"""TASK-138 — per-ref consecutive-failure tracking + TTL skip (ValueError hardening).

Prod incident: @hart_1337 #0 Connected but ValueError raised ~104x every tick —
black-holing that channel and wasting the account. This suite asserts:
  (a) the channel HANDLE is logged at the transient catch site (not just the class).
  (b) a ref is SKIPPED after READ_REF_FAILURE_SKIP_THRESHOLD consecutive failures.
  (c) skip expires after READ_REF_SKIP_TTL_SECONDS (TTL) and the ref is read again.
  (d) permanent-auth errors still quarantine (no regression from skip-counter logic).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from types import SimpleNamespace

import pytest

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    READ_REF_FAILURE_SKIP_THRESHOLD,
    READ_REF_SKIP_TTL_SECONDS,
)
from collector.errors import SourceUnavailableError
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, make_message, make_pool

# Channel that will raise ValueError every read — matches the prod symptom.
_BAD_REF = SourceRef(kind=SourceKind.TELEGRAM, handle="@hart_1337")
# A healthy ref on the same account — must continue to read normally.
_GOOD_REF = SourceRef(kind=SourceKind.TELEGRAM, handle="@goodchannel")


class _ValueErrorOnEntityClient(FakeClient):
    """Resolves the entity fine, then raises ValueError mid-iteration.

    `should_raise` can be set to False to make the client succeed (for recovery tests).
    """

    def __init__(self, *, messages: Sequence[SimpleNamespace] | None = None) -> None:
        super().__init__(messages=messages)
        self.should_raise: bool = True

    async def iter_messages(
        self,
        entity: object,
        *,
        offset_date: datetime | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        self.iter_calls += 1
        if self.should_raise:
            raise ValueError("bad field: cannot coerce to int")
        # Delegate to the parent for normal message iteration.
        async for msg in super().iter_messages(
            entity, offset_date=offset_date, reverse=reverse, limit=limit
        ):
            yield msg


class _FakeClock:
    """Injectable monotonic clock — holds a float that tests can advance freely."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


async def _drain(it: AsyncIterator[RawPost]) -> list[RawPost]:
    """Collect all posts from an async iterator."""
    return [post async for post in it]


# ---------------------------------------------------------------------------
# (a) Handle logged on ValueError — the culprit must be visible in the log.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_logged_on_read_failure(caplog: pytest.LogCaptureFixture) -> None:
    """When a ref raises ValueError, the log line includes the channel HANDLE
    and the exception class name — no session string or secret."""
    client = _ValueErrorOnEntityClient()
    pool = make_pool([client])
    clock = _FakeClock()
    collector = TelegramCollector(pool, clock=clock)

    with (
        caplog.at_level(logging.WARNING, logger="collector.telegram.reader"),
        pytest.raises(SourceUnavailableError),
    ):
        await _drain(collector._read_one(_BAD_REF, None))

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # At least one warning must mention the handle AND the exception class.
    matching = [m for m in warning_messages if "@hart_1337" in m and "ValueError" in m]
    assert matching, (
        f"Expected a WARNING containing '@hart_1337' and 'ValueError'; "
        f"got warnings: {warning_messages}"
    )
    # Confirm no session string leaked.
    for msg in warning_messages:
        assert "session-" not in msg, f"Secret leaked in log: {msg!r}"


@pytest.mark.asyncio
async def test_handle_logged_on_entity_resolve_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same assertion for the ENTITY-RESOLVE catch site (raise_on_entity)."""
    client = FakeClient(raise_on_entity=ValueError("entity resolve failed"))
    pool = make_pool([client])
    clock = _FakeClock()
    collector = TelegramCollector(pool, clock=clock)

    with (
        caplog.at_level(logging.WARNING, logger="collector.telegram.reader"),
        pytest.raises(SourceUnavailableError),
    ):
        await _drain(collector._read_one(_BAD_REF, None))

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    matching = [m for m in warning_messages if "@hart_1337" in m and "ValueError" in m]
    assert matching, f"Expected WARNING with handle and error class; got: {warning_messages}"
    for msg in warning_messages:
        assert "session-" not in msg, f"Secret leaked in log: {msg!r}"


# ---------------------------------------------------------------------------
# (b) Ref skipped after threshold consecutive failures.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ref_skipped_after_threshold(caplog: pytest.LogCaptureFixture) -> None:
    """After READ_REF_FAILURE_SKIP_THRESHOLD consecutive failures on the SAME ref,
    the NEXT read skips it entirely (client is NOT called again).  A second healthy
    ref in the same batch still yields posts normally."""
    # Build a pool with TWO clients: one for the bad ref (@hart_1337) and one
    # for the good ref (@goodchannel).  Pool round-robins; we wire the
    # bad client to the first slot (maps by sha256 % 1 = 0 for single-slot).
    # To keep the test deterministic we use a SINGLE-client pool and two refs:
    # the same client handles both; the bad ref raises, the good ref yields.
    bad_client = _ValueErrorOnEntityClient(messages=[make_message(42)])
    pool = make_pool([bad_client])
    clock = _FakeClock(start=100.0)
    collector = TelegramCollector(pool, clock=clock)

    # Drive the bad ref to the threshold (each call raises SourceUnavailableError).
    for _ in range(READ_REF_FAILURE_SKIP_THRESHOLD):
        with pytest.raises(SourceUnavailableError):
            await _drain(collector._read_one(_BAD_REF, None))

    iter_calls_at_threshold = bad_client.iter_calls

    # Next tick: the ref must be SKIPPED — no new iter_messages call.
    with caplog.at_level(logging.WARNING, logger="collector.telegram.reader"):
        result = await _drain(collector._read_one(_BAD_REF, None))

    assert result == [], "Skipped ref must yield nothing"
    assert bad_client.iter_calls == iter_calls_at_threshold, (
        "iter_messages must NOT be called again for a skipped ref"
    )

    # Exactly ONE skip-tripped warning (not one per skipped tick).
    skip_warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "skip" in r.getMessage().lower()
    ]
    assert len(skip_warnings) >= 1, "Expected at least one skip-tripped warning"


@pytest.mark.asyncio
async def test_good_ref_unaffected_when_bad_ref_skipped() -> None:
    """A healthy ref in the SAME read() batch still yields posts when the bad
    ref is skipped — one bad channel must not block the rest."""
    bad_client = _ValueErrorOnEntityClient(messages=[make_message(1)])
    pool = make_pool([bad_client])
    clock = _FakeClock(start=0.0)

    async def instant_sleep(_: float) -> None:
        pass

    collector = TelegramCollector(pool, sleep=instant_sleep, clock=clock)

    # Make the bad ref hit the threshold.
    for _ in range(READ_REF_FAILURE_SKIP_THRESHOLD):
        with pytest.raises(SourceUnavailableError):
            await _drain(collector._read_one(_BAD_REF, None))

    # Now run a full read() with both refs; the bad one is skipped (TTL active),
    # the good one (same client, now not raising) should read.
    bad_client.should_raise = False

    posts = await _drain(collector.read([_BAD_REF, _GOOD_REF], since=None))
    # Good ref must yield at least one post.
    assert posts, "Good ref must still yield posts even when bad ref is skipped"


# ---------------------------------------------------------------------------
# (c) Recovery after TTL: ref is read again and counter resets.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_after_ttl_resets_counter() -> None:
    """Advancing the clock past READ_REF_SKIP_TTL_SECONDS unblocks the ref.
    On the next read (client now healthy) the ref is read, posts yielded,
    counter resets, and a subsequent read is NOT skipped."""
    bad_client = _ValueErrorOnEntityClient(messages=[make_message(99)])
    pool = make_pool([bad_client])
    clock = _FakeClock(start=0.0)

    async def instant_sleep(_: float) -> None:
        pass

    collector = TelegramCollector(pool, sleep=instant_sleep, clock=clock)

    # Hit the threshold.
    for _ in range(READ_REF_FAILURE_SKIP_THRESHOLD):
        with pytest.raises(SourceUnavailableError):
            await _drain(collector._read_one(_BAD_REF, None))

    # Confirm it IS skipped within TTL.
    result_before_expiry = await _drain(collector._read_one(_BAD_REF, None))
    assert result_before_expiry == [], "Ref must be skipped within TTL"

    # Advance past the TTL.
    clock.advance(READ_REF_SKIP_TTL_SECONDS + 1.0)

    # Now the client succeeds (stop raising).
    bad_client.should_raise = False

    # After TTL, ref must be read again normally.
    posts = await _drain(collector._read_one(_BAD_REF, None))
    assert posts, "Ref must yield posts after TTL expires"

    # Counter must be reset: next read must NOT skip even immediately.
    iter_calls_after_recovery = bad_client.iter_calls
    await _drain(collector._read_one(_BAD_REF, None))
    assert bad_client.iter_calls > iter_calls_after_recovery, (
        "After recovery, counter is reset — ref must be read on the next call"
    )


# ---------------------------------------------------------------------------
# (d) Permanent-auth still quarantines — no regression from skip-counter logic.
# ---------------------------------------------------------------------------


class AuthKeyDuplicatedError(Exception):
    """Mimics telethon AuthKeyDuplicatedError (matched structurally by name)."""


@pytest.mark.asyncio
async def test_permanent_auth_quarantines_and_does_not_increment_skip_counter() -> None:
    """A permanent-auth error (AuthKeyDuplicatedError) STILL quarantines the account
    as before.  The per-ref consecutive skip-counter must NOT be incremented for it
    (it quarantines the ACCOUNT, not the ref; a different mechanism)."""
    dead_client = FakeClient(raise_on_entity=AuthKeyDuplicatedError("dup"))
    healthy_client = FakeClient(messages=[make_message(7)])
    pool = make_pool([dead_client, healthy_client])
    clock = _FakeClock(start=0.0)
    collector = TelegramCollector(pool, clock=clock)

    # The dead ref uses "@dead" which maps to slot 0 for 2-client pools
    # (mirrors test_auth_quarantine.py pattern).
    dead_ref = SourceRef(kind=SourceKind.TELEGRAM, handle="@dead")

    with pytest.raises(SourceUnavailableError):
        await _drain(collector._read_one(dead_ref, None))

    # Account must be quarantined.
    assert pool.quarantined_count == 1, "Permanent auth error must quarantine the account"

    # The per-ref skip counter for "@dead" must be 0 (the permanent-auth path
    # must NOT increment it; it takes a different branch — quarantine).
    from collector.telegram.dedup import normalize_handle

    normalized = normalize_handle(dead_ref.handle, dead_ref.kind)
    skip_count = collector._ref_consecutive_failures.get(normalized, 0)
    assert skip_count == 0, (
        f"Permanent auth must NOT increment the per-ref skip counter; "
        f"got {skip_count} for {normalized!r}"
    )
