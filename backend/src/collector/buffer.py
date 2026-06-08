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
from typing import Protocol

from collector.base import RawPost, SourceKind
from collector.constants import RAW_POST_TTL_SECONDS
from collector.errors import BufferWriteError
from collector.telegram.dedup import normalize_handle

logger = logging.getLogger(__name__)

_KEY_PREFIX = "raw"


class _RedisLike(Protocol):
    """Minimal Redis surface the buffer uses (sync redis-py client / fakeredis)."""

    def rpush(self, name: str, *values: str) -> int: ...

    def expire(self, name: str, time: int) -> bool: ...


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
    """Append `post` to its by-source buffer and (re)set the TTL. Returns the key."""
    key = buffer_key(post.source.kind, post.source.handle)
    try:
        redis.rpush(key, serialize_post(post))
        redis.expire(key, RAW_POST_TTL_SECONDS)
    except Exception as exc:
        logger.error("failed writing raw post to buffer key=%s", key)
        raise BufferWriteError(f"could not buffer raw post for {key}") from exc
    return key
