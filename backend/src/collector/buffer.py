"""Raw-post Redis buffer keyed BY SOURCE with a 48h TTL (AC6, ADR-002 §3/§4).

Posts are buffered under `raw:{kind}:{handle}` (by source, NOT by user) so a
channel read once serves every tenant; the per-user batch (task-006/007) filters
this buffer by watchlist later. Every key carries `RAW_POST_TTL_SECONDS` (≤ 48h):
raw content never persists beyond the compliance window.

Serialization is deterministic JSON (sorted keys). Redis failures surface as a
domain `BufferWriteError` — never silently swallowed (CONVENTIONS / edge case).
"""

import json
import logging
from datetime import datetime
from typing import Protocol, cast

from redis import Redis

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.constants import MAX_RAW_BUFFER_LEN, RAW_POST_TTL_SECONDS
from collector.errors import BufferWriteError
from collector.telegram.dedup import normalize_handle

logger = logging.getLogger(__name__)

_KEY_PREFIX = "raw"


class _PipelineLike(Protocol):
    """Minimal MULTI/EXEC pipeline surface `write_post` queues onto.

    Return types are `object` (the buffer ignores per-command queue results):
    redis-py's stubs type these as `Pipeline | Awaitable[...]` unions, which a
    narrower protocol could not match against a concrete `Pipeline`.
    """

    def rpush(self, name: str, *values: str) -> object: ...

    def ltrim(self, name: str, start: int, end: int) -> object: ...

    def expire(self, name: str, time: int) -> object: ...

    def execute(self) -> object: ...


class _RedisLike(Protocol):
    """Minimal Redis surface the buffer uses (sync redis-py client / fakeredis).

    `pipeline` lets `write_post` run rpush+ltrim+expire as one MULTI/EXEC so a
    concurrent drain can never observe an unbounded or untrimmed intermediate
    state. Return types are `object` (the buffer ignores them): redis-py's stubs
    type these as `Awaitable[...] | ...` unions, which would otherwise fail to
    match a narrower protocol when a concrete `Redis` client is passed (as the
    collect-tick producer does).
    """

    def pipeline(self, transaction: bool = ...) -> _PipelineLike: ...


def buffer_key(kind: SourceKind, handle: str) -> str:
    """Return the by-source buffer key `raw:{kind}:{normalized-handle}`."""
    return f"{_KEY_PREFIX}:{kind.value}:{normalize_handle(handle, kind)}"


def serialize_post(post: RawPost) -> str:
    """Deterministically serialize a `RawPost` to JSON (sorted keys)."""
    payload = {
        "kind": post.source.kind.value,
        "handle": post.source.handle,
        "external_id": post.external_id,
        "author": post.author,
        "text": post.text,
        "media_hashes": list(post.media_hashes),
        "metrics": {
            "views": post.metrics.views,
            "forwards": post.metrics.forwards,
            "reactions": post.metrics.reactions,
            "extra": dict(post.metrics.extra),
        },
        "posted_at": post.posted_at.isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def write_post(redis: _RedisLike, post: RawPost) -> str:
    """Append `post` to its by-source buffer, cap its length, (re)set TTL.

    Append + cap + TTL run in one MULTI/EXEC pipeline: a source's buffer is bounded
    to `MAX_RAW_BUFFER_LEN` (OOM safety belt, TASK-076) atomically, so a concurrent
    `drain_source` can never see an unbounded or half-trimmed list. `ltrim(-MAX, -1)`
    keeps the NEWEST `MAX` posts (rpush appends to the tail); on overflow the oldest
    are dropped — recency matters for a viral detector. Returns the key.
    """
    key = buffer_key(post.source.kind, post.source.handle)
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.rpush(key, serialize_post(post))
        pipe.ltrim(key, -MAX_RAW_BUFFER_LEN, -1)
        pipe.expire(key, RAW_POST_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:
        logger.error("failed writing raw post to buffer key=%s", key, exc_info=exc)
        raise BufferWriteError(f"could not buffer raw post for {key}") from exc
    return key


def deserialize_post(payload: str) -> RawPost:
    """Reconstruct a `RawPost` from its deterministic JSON form (inverse of write)."""
    data = json.loads(payload)
    metrics = data["metrics"]
    return RawPost(
        source=SourceRef(kind=SourceKind(data["kind"]), handle=data["handle"]),
        external_id=data["external_id"],
        author=data["author"],
        text=data["text"],
        media_hashes=tuple(data["media_hashes"]),
        metrics=PostMetrics(
            views=metrics["views"],
            forwards=metrics["forwards"],
            reactions=metrics["reactions"],
            extra=dict(metrics["extra"]),
        ),
        posted_at=datetime.fromisoformat(data["posted_at"]),
    )


def drain_source(redis: Redis, kind: SourceKind, handle: str) -> list[RawPost]:
    """Read + clear one source's buffer, returning its `RawPost`s.

    Read-and-delete so a batch never reprocesses the same posts (idempotent drain,
    task-006 SEAM). Returns `[]` for an empty/absent buffer. Used by the per-user
    pipeline (task-007), which consumes what the collector (task-005) produced —
    an acceptable cross-module read of the buffer this module owns.

    The read+clear is ATOMIC: `lrange` + `delete` run in a single MULTI/EXEC
    transaction so a concurrent collector `rpush` between the two can't be silently
    dropped — it lands in a fresh key after the delete and is drained next batch.
    The concrete sync `Redis` is used (as in `pipeline.locks`); `execute()` returns
    a sync/async union, narrowed with `cast` rather than an inline ignore.
    """
    key = buffer_key(kind, handle)
    pipe = redis.pipeline(transaction=True)
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    results = cast(list[object], pipe.execute())
    raw = cast(list[bytes], results[0])
    if not raw:
        return []
    return [deserialize_post(item.decode("utf-8")) for item in raw]
