"""task-078 — lock the collector→batch buffer contract forever.

The T2 diagnosis (task-077) traced "scores stuck at 0" partly to the seam where
the collector's WRITE path (`buffer.write_post`, keyed `raw:{kind}:{handle}`) and
the per-user batch's DRAIN path (`batch_processor` → `buffer.drain_source`) must
agree byte-for-byte on the key and the serialized payload. If either side drifts
(key format, serialization), a post the collector buffered is invisible to the
watching user's batch and the pipeline silently starves.

These round-trip tests assert the exact contract: a `RawPost` written by the
collector write path is found, fully reconstructed, by the drain path for the
same source — and that drain is a one-shot read+clear (idempotent).
"""

from datetime import UTC, datetime

import fakeredis

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.buffer import buffer_key, drain_source, write_post

_POSTED_AT = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _post(handle: str, external_id: str, text: str = "viral signal") -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle=handle),
        external_id=external_id,
        author="Author",
        text=text,
        media_hashes=(),
        metrics=PostMetrics(views=123, forwards=4, reactions=7, extra={"reaction_kinds": 2}),
        posted_at=_POSTED_AT,
    )


def test_collector_write_is_found_by_batch_drain() -> None:
    # The exact cross-module contract: what the collector writes, the batch drains.
    redis = fakeredis.FakeRedis()
    written = _post("@alpha", "42")

    key = write_post(redis, written)
    drained = drain_source(redis, SourceKind.TELEGRAM, "@alpha")

    assert key == buffer_key(SourceKind.TELEGRAM, "@alpha")
    assert len(drained) == 1
    got = drained[0]
    # Full reconstruction — every field survives the JSON round-trip.
    assert got.source == written.source
    assert got.external_id == written.external_id
    assert got.author == written.author
    assert got.text == written.text
    assert got.posted_at == written.posted_at
    assert got.metrics.views == written.metrics.views
    assert got.metrics.forwards == written.metrics.forwards
    assert got.metrics.reactions == written.metrics.reactions


def test_drain_preserves_write_order_and_clears_buffer() -> None:
    redis = fakeredis.FakeRedis()
    for i in range(3):
        write_post(redis, _post("@alpha", str(i)))

    drained = drain_source(redis, SourceKind.TELEGRAM, "@alpha")
    assert [p.external_id for p in drained] == ["0", "1", "2"]

    # Idempotent: a second drain sees an empty buffer (read+clear).
    assert drain_source(redis, SourceKind.TELEGRAM, "@alpha") == []
    assert redis.llen(buffer_key(SourceKind.TELEGRAM, "@alpha")) == 0


def test_drain_isolates_sources_by_key() -> None:
    # A watching user's batch must only drain its own source — not a sibling's.
    redis = fakeredis.FakeRedis()
    write_post(redis, _post("@alpha", "a1"))
    write_post(redis, _post("@beta", "b1"))

    alpha = drain_source(redis, SourceKind.TELEGRAM, "@alpha")
    assert [p.external_id for p in alpha] == ["a1"]
    # @beta untouched by the @alpha drain.
    assert redis.llen(buffer_key(SourceKind.TELEGRAM, "@beta")) == 1
