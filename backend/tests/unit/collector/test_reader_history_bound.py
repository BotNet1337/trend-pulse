"""task-078 — the reader MUST bound its fetch to posts newer than `since`.

Root cause (task-077 diagnosis): `iter_messages(entity, offset_date=since)` with
Telethon's default `reverse=False` treats `offset_date` as an UPPER bound and
walks the ENTIRE channel history backward (prod posts spanned 2026→2017). So
`since` did NOT act as a lower bound: GetHistory flood-wait storms, 100k+ raw
buffers, the collect lock held its full TTL, scores stuck at 0.

These tests model Telethon's REAL semantics in the fake client (oldest→newest
when `reverse=True`, `offset_date` as an exclusive lower bound in that mode, and
`limit`) so the transport-seam bug is actually exercised — unlike
`test_first_tick_uses_lookback_window_not_full_history`, which only checks the
`since` VALUE handed to a collector that never models the backward walk.
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
    # A channel whose history straddles `since`: 3 recent posts (>= since) and a
    # deep backlog of OLD posts (the 2017-era tail). The reader must yield ONLY
    # the recent ones — never the backlog.
    # Recent posts are STRICTLY after `since` (Telethon's `offset_date` is an
    # exclusive lower bound in reverse mode — a post landing exactly at `since`
    # was already covered by the previous tick).
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
async def test_reader_requests_forward_window_from_since() -> None:
    # The transport seam: the reader must drive Telethon as a FORWARD scan from
    # `since` (reverse=True + offset_date=since), not a backward history walk.
    client = FakeClient(messages=[_msg_at(1, _SINCE + timedelta(minutes=1))])
    collector = TelegramCollector(make_pool([client]))

    await _collect(collector, _SINCE)

    assert client.last_iter_kwargs is not None
    assert client.last_iter_kwargs["reverse"] is True
    assert client.last_iter_kwargs["offset_date"] == _SINCE


@pytest.mark.asyncio
async def test_reader_caps_messages_per_tick() -> None:
    # Even a misconfigured `since` (e.g. None / huge lookback) must not trigger a
    # deep pull: the hard MAX_MESSAGES_PER_TICK cap is the backstop.
    flood = [_msg_at(i, _SINCE + timedelta(seconds=i)) for i in range(MAX_MESSAGES_PER_TICK + 200)]
    client = FakeClient(messages=flood)
    collector = TelegramCollector(make_pool([client]))

    posts = await _collect(collector, since=None)

    assert len(posts) <= MAX_MESSAGES_PER_TICK
    assert client.last_iter_kwargs is not None
    assert client.last_iter_kwargs["limit"] == MAX_MESSAGES_PER_TICK
