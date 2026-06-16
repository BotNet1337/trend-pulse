"""TASK-118 — the reader records a per-account READ OUTCOME (pool-health honesty).

A clean read stamps success on the current account; the currently-silent transient
catch site (a non-permanent error raised on entity resolve / iteration — the swallowed
"wrong session ID" class) now records a read FAILURE with the error CLASS NAME so the
account can be classified `failing`. Rotation/quarantine behaviour is unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import POOL_FAILING_THRESHOLD
from collector.errors import SourceUnavailableError
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, make_pool

_REF = SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")


class WrongSessionIdError(Exception):
    """Stand-in for the non-permanent Telethon "wrong session ID" class (transient)."""


async def _drain(it: AsyncIterator[RawPost]) -> list[RawPost]:
    return [post async for post in it]


@pytest.mark.asyncio
async def test_clean_read_stamps_success() -> None:
    """A clean read calls note_read_success → consecutive_read_failures stays 0 and
    last_read_ok_at is stamped → the account reads `healthy`."""
    pool = make_pool([FakeClient()])
    collector = TelegramCollector(pool)

    posts = [post async for post in collector.read([_REF], since=None)]
    assert posts  # mapped at least one message

    account = pool._accounts[0]
    assert account.consecutive_read_failures == 0
    assert account.last_read_ok_at is not None
    assert pool.account_statuses()[0].state == "healthy"


@pytest.mark.asyncio
async def test_transient_entity_error_records_read_failure() -> None:
    """A non-permanent error on entity resolve (the previously-silent `auth_error`
    branch) now records a read failure with the error CLASS NAME — never a secret."""
    client = FakeClient(raise_on_entity=WrongSessionIdError("wrong session id"))
    pool = make_pool([client])
    collector = TelegramCollector(pool)

    with pytest.raises(SourceUnavailableError):
        await _drain(collector._read_one(_REF, None))

    account = pool._accounts[0]
    assert account.consecutive_read_failures == 1
    assert account.last_error_reason == "WrongSessionIdError"


@pytest.mark.asyncio
async def test_repeated_transient_errors_reach_failing_state() -> None:
    """Repeated transient read errors accumulate to the `failing` classification."""
    client = FakeClient(raise_on_entity=WrongSessionIdError("wrong session id"))
    pool = make_pool([client])
    collector = TelegramCollector(pool)

    for _ in range(POOL_FAILING_THRESHOLD):
        with pytest.raises(SourceUnavailableError):
            await _drain(collector._read_one(_REF, None))

    assert pool.account_statuses()[0].state == "failing"
    assert pool.account_statuses()[0].last_error_reason == "WrongSessionIdError"
