"""task-078 / task-083 — the reader MUST fetch the NEWEST posts in a recent window.

Root cause (task-077 diagnosis): `iter_messages(entity, offset_date=since)` with
Telethon's default `reverse=False` treats `offset_date` as an UPPER bound and
walks the ENTIRE channel history backward (prod posts spanned 2026→2017). So
`since` did NOT act as a lower bound: GetHistory flood-wait storms, 100k+ raw
buffers, the collect lock held its full TTL, scores stuck at 0.

task-078 (#121) switched to `reverse=True` so `offset_date` becomes a LOWER bound
and iteration is oldest→newest from `since`. task-083 found that REGRESSED a
different way: `reverse=True` yields the OLDEST messages of the window first, so
with `MAX_MESSAGES_PER_TICK` the NEWEST posts are truncated; and — the prod
launch bug — when the marker is absent (Redis flush) Telethon's own
`_MessagesIter._init` sets `offset_id = 1` for `reverse=True` + no `offset_date`,
returning the channel's OLDEST messages forward (2024 and earlier).

The correct idiom for "the newest posts in the lookback window" is
`reverse=False` (newest→oldest) + `limit=MAX_MESSAGES_PER_TICK` + an early BREAK
once a message older than `since` is seen. These tests model Telethon's REAL
semantics in the fake client (newest→oldest by default, `offset_date` as the
EXCLUSIVE UPPER bound in that mode, `limit`, and the `offset_id=1` oldest-trap
when `reverse=True` + no `offset_date`) so the transport-seam bug is actually
exercised — not assumed.
"""

from datetime import UTC, datetime, timedelta

import pytest

from collector.base import SourceKind, SourceRef
from collector.constants import MAX_MESSAGES_PER_TICK
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, make_message, make_pool

_REF = SourceRef(kind=SourceKind.TELEGRAM, handle="@alpha")
_SINCE = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _msg_at(msg_id: int, when: datetime):
    msg = make_message(msg_id)
    msg.date = when
    return msg


async def _collect(collector: TelegramCollector, since: datetime | None):
    return [post async for post in collector.read([_REF], since=since)]


@pytest.mark.asyncio
async def test_reader_does_not_walk_past_since() -> None:
    # A channel whose history straddles `since`: 3 recent posts (> since) and a
    # deep backlog of OLD posts (the 2017-era tail). The reader must yield ONLY
    # the recent ones — never the backlog.
    recent = [_msg_at(100 + i, _SINCE + timedelta(minutes=i + 1)) for i in range(3)]
    backlog = [
        _msg_at(i, _SINCE - timedelta(days=365 * 3) + timedelta(minutes=i)) for i in range(50)
    ]
    client = FakeClient(messages=[*backlog, *recent])
    collector = TelegramCollector(make_pool([client]))

    posts = await _collect(collector, _SINCE)

    posted = [p.posted_at for p in posts]
    assert posted, "expected the recent posts to be yielded"
    assert all(ts >= _SINCE for ts in posted), f"reader walked past `since`: {posted}"
    assert {p.external_id for p in posts} == {"100", "101", "102"}


@pytest.mark.asyncio
async def test_reader_no_marker_fetches_recent_not_oldest() -> None:
    # REGRESSION (task-083, prod launch bug): with NO marker (Redis flush) the
    # reader is called with a recent `since` (now - lookback). Telethon's
    # `reverse=True` + no/old `offset_date` returns the channel's OLDEST messages
    # (offset_id=1), so prod ingested 2024-era posts. With the correct
    # `reverse=False` newest-first idiom the reader must yield the RECENT posts,
    # never the ancient backlog — even though the recent ones are the minority.
    backlog = [
        _msg_at(i, datetime(2024, 3, 18, tzinfo=UTC) + timedelta(minutes=i)) for i in range(1, 400)
    ]
    recent = [_msg_at(10_000 + i, _SINCE + timedelta(minutes=i + 1)) for i in range(3)]
    client = FakeClient(messages=[*backlog, *recent])
    collector = TelegramCollector(make_pool([client]))

    posts = await _collect(collector, _SINCE)

    posted = [p.posted_at for p in posts]
    assert posted, "expected the recent posts to be yielded, not the 2024 backlog"
    assert all(ts >= _SINCE for ts in posted), f"reader returned ancient posts: {posted}"
    assert {p.external_id for p in posts} == {"10000", "10001", "10002"}


@pytest.mark.asyncio
async def test_reader_prioritizes_newest_when_window_exceeds_cap() -> None:
    # REGRESSION (task-083): when the window holds MORE than MAX_MESSAGES_PER_TICK
    # posts, the reader must keep the NEWEST ones (a viral detector cares about
    # recency). `reverse=True` kept the OLDEST of the window and truncated the
    # newest at the limit — the wrong end. Newest→oldest + limit keeps the right
    # end. Here ids increase with time; the newest `MAX_MESSAGES_PER_TICK` ids
    # must be the ones returned.
    n = MAX_MESSAGES_PER_TICK + 200
    flood = [_msg_at(1000 + i, _SINCE + timedelta(seconds=i + 1)) for i in range(n)]
    client = FakeClient(messages=flood)
    collector = TelegramCollector(make_pool([client]))

    posts = await _collect(collector, _SINCE)

    assert len(posts) == MAX_MESSAGES_PER_TICK
    returned_ids = {int(p.external_id) for p in posts}
    newest_ids = {1000 + i for i in range(n - MAX_MESSAGES_PER_TICK, n)}
    assert returned_ids == newest_ids, "reader kept the OLDEST of the window, not the newest"


@pytest.mark.asyncio
async def test_reader_requests_newest_first_window() -> None:
    # The transport seam: the reader must drive Telethon as a newest→oldest scan
    # bounded by `since` (reverse=False is Telethon's default newest-first order,
    # the reader breaks once it passes `since`), with the hard per-tick cap.
    client = FakeClient(messages=[_msg_at(1, _SINCE + timedelta(minutes=1))])
    collector = TelegramCollector(make_pool([client]))

    await _collect(collector, _SINCE)

    assert client.last_iter_kwargs is not None
    assert client.last_iter_kwargs["reverse"] is False
    assert client.last_iter_kwargs["limit"] == MAX_MESSAGES_PER_TICK


@pytest.mark.asyncio
async def test_reader_caps_messages_per_tick() -> None:
    # Even a misconfigured `since` (e.g. None) must not trigger a deep pull: the
    # hard MAX_MESSAGES_PER_TICK cap is the backstop.
    flood = [_msg_at(i, _SINCE + timedelta(seconds=i)) for i in range(MAX_MESSAGES_PER_TICK + 200)]
    client = FakeClient(messages=flood)
    collector = TelegramCollector(make_pool([client]))

    posts = await _collect(collector, since=None)

    assert len(posts) <= MAX_MESSAGES_PER_TICK
    assert client.last_iter_kwargs is not None
    assert client.last_iter_kwargs["limit"] == MAX_MESSAGES_PER_TICK
