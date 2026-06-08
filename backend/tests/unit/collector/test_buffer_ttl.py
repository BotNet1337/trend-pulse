"""AC6 — Redis buffer keyed BY SOURCE with TTL == RAW_POST_TTL_SECONDS (≤ 48h)."""

from datetime import UTC, datetime

import fakeredis
import pytest

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.buffer import BufferWriteError, buffer_key, serialize_post, write_post
from collector.constants import RAW_POST_TTL_SECONDS


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


def test_redis_failure_raises_buffer_write_error() -> None:
    class BrokenRedis:
        def rpush(self, name: str, *values: str) -> int:
            raise ConnectionError("redis down")

        def expire(self, name: str, time: int) -> bool:
            return True

    with pytest.raises(BufferWriteError):
        write_post(BrokenRedis(), _post())
