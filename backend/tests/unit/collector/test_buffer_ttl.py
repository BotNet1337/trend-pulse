"""AC6 — Redis buffer keyed BY SOURCE with TTL == RAW_POST_TTL_SECONDS (≤ 48h)."""

from datetime import UTC, datetime
from typing import cast

import fakeredis
import pytest
from redis import Redis

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.buffer import (
    BufferWriteError,
    buffer_key,
    deserialize_post,
    drain_source,
    serialize_post,
    write_post,
)
from collector.constants import MAX_RAW_BUFFER_LEN, RAW_POST_TTL_SECONDS


def _post(handle: str = "@news", external_id: str = "1") -> RawPost:
    return RawPost(
        source=SourceRef(SourceKind.TELEGRAM, handle),
        external_id=external_id,
        author="Author",
        text="hello",
        media_hashes=(),
        metrics=PostMetrics(views=10, forwards=2, reactions=3, extra={"reaction_kinds": 1}),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def test_ttl_is_within_48h() -> None:
    assert RAW_POST_TTL_SECONDS <= 48 * 60 * 60


def test_key_is_by_source_not_by_user() -> None:
    assert buffer_key(SourceKind.TELEGRAM, "@News") == "raw:telegram:@news"


def test_write_sets_key_and_ttl() -> None:
    redis = fakeredis.FakeRedis()
    key = write_post(redis, _post())

    assert key == "raw:telegram:@news"
    assert redis.llen(key) == 1
    ttl = redis.ttl(key)
    assert ttl == RAW_POST_TTL_SECONDS


def test_posts_from_same_source_share_one_key() -> None:
    redis = fakeredis.FakeRedis()
    write_post(redis, _post(external_id="1"))
    write_post(redis, _post(external_id="2"))

    assert redis.llen("raw:telegram:@news") == 2


def test_serialize_is_deterministic() -> None:
    post = _post()
    assert serialize_post(post) == serialize_post(post)


def test_under_cap_keeps_all_posts() -> None:
    redis = fakeredis.FakeRedis()
    for i in range(5):
        write_post(redis, _post(external_id=str(i)))

    assert redis.llen("raw:telegram:@news") == 5


def test_buffer_capped_at_max_len() -> None:
    # Writing more than the cap must never let one source's list grow unbounded:
    # this is the OOM safety belt (TASK-076).
    redis = fakeredis.FakeRedis()
    overflow = MAX_RAW_BUFFER_LEN + 50
    for i in range(overflow):
        write_post(redis, _post(external_id=str(i)))

    assert redis.llen("raw:telegram:@news") == MAX_RAW_BUFFER_LEN


def test_buffer_keeps_newest_posts_on_overflow() -> None:
    # Recency matters for a viral detector: when capped, the OLDEST posts are
    # dropped and the most recent MAX_RAW_BUFFER_LEN are retained.
    redis = fakeredis.FakeRedis()
    overflow = MAX_RAW_BUFFER_LEN + 3
    for i in range(overflow):
        write_post(redis, _post(external_id=str(i)))

    stored = redis.lrange("raw:telegram:@news", 0, -1)
    # Oldest survivor is the (overflow - MAX)th post written; newest is the last.
    first_kept = deserialize_post(stored[0].decode("utf-8"))
    last_kept = deserialize_post(stored[-1].decode("utf-8"))
    assert first_kept.external_id == str(overflow - MAX_RAW_BUFFER_LEN)
    assert last_kept.external_id == str(overflow - 1)


def test_ttl_set_even_after_trim() -> None:
    redis = fakeredis.FakeRedis()
    for i in range(MAX_RAW_BUFFER_LEN + 5):
        write_post(redis, _post(external_id=str(i)))

    assert redis.ttl("raw:telegram:@news") == RAW_POST_TTL_SECONDS


def test_drain_returns_only_capped_window() -> None:
    # Round-trip through the public interface: drain after overflow returns exactly
    # the capped, newest window — the cap and the atomic drain stay consistent.
    redis = fakeredis.FakeRedis()
    overflow = MAX_RAW_BUFFER_LEN + 7
    for i in range(overflow):
        write_post(redis, _post(external_id=str(i)))

    drained = drain_source(cast(Redis, redis), SourceKind.TELEGRAM, "@news")

    assert len(drained) == MAX_RAW_BUFFER_LEN
    assert drained[0].external_id == str(overflow - MAX_RAW_BUFFER_LEN)
    assert drained[-1].external_id == str(overflow - 1)
    assert redis.llen("raw:telegram:@news") == 0


def test_redis_failure_raises_buffer_write_error() -> None:
    class BrokenPipeline:
        def rpush(self, name: str, *values: str) -> object:
            return self

        def ltrim(self, name: str, start: int, end: int) -> object:
            return self

        def expire(self, name: str, time: int) -> object:
            return self

        def execute(self) -> object:
            raise ConnectionError("redis down")

    class BrokenRedis:
        def pipeline(self, transaction: bool = True) -> BrokenPipeline:
            return BrokenPipeline()

    with pytest.raises(BufferWriteError):
        write_post(BrokenRedis(), _post())
