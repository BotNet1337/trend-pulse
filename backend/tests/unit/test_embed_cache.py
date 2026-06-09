"""Unit tests for embed_with_cache (TASK-037, AC1-AC4).

Pure unit tests: fake encoder (counts encode calls) + MagicMock Redis.
No fakeredis dependency, no torch import.

AC1 — hit does NOT call model (failing-test anchor)
AC2 — miss calls model, stores correct Redis key/TTL/JSON
AC3 — mixed batch [cached, new, cached] preserves original order
AC4 — fail-open: redis errors / corrupt value → computed by model, warn logged
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from collector.base import PostMetrics, SourceKind, SourceRef
from pipeline import batch_processor
from pipeline.steps.normalize import NormalizedPost
from storage.models import EMBEDDING_DIM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(text: str) -> NormalizedPost:
    """Build a minimal NormalizedPost with the given text."""
    return NormalizedPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle="@test"),
        external_id="x",
        text=text,
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=datetime(2026, 6, 10, tzinfo=UTC),
    )


class _FakeEncoder:
    """Fake encoder: returns deterministic per-text vectors, counts encode calls."""

    def __init__(self) -> None:
        self.call_count: int = 0
        self.last_texts: list[str] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.last_texts = list(texts)
        # Deterministic vector per text: hash-based first float, rest 0.
        result: list[list[float]] = []
        for text in texts:
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % 1000
            result.append([float(seed)] + [0.0] * (EMBEDDING_DIM - 1))
        return result


def _cache_key(model: str, text: str) -> str:
    sha = hashlib.sha256(text.encode()).hexdigest()
    return f"embed:{model}:{sha}"


def _cached_vector(seed: int = 42) -> str:
    """Return a JSON-serialized valid vector for seeding a mock Redis."""
    return json.dumps([float(seed)] + [0.0] * (EMBEDDING_DIM - 1))


def _make_redis_mock(get_return: list[bytes | None] | None = None) -> MagicMock:
    """Return a MagicMock redis with mget/pipeline configured.

    ``r.pipeline()`` returns a child MagicMock that tracks setex/execute
    calls; access it via ``r.pipeline.return_value``.
    """
    r = MagicMock()
    r.mget.return_value = get_return
    # pipeline() returns the same child mock on every call so callers can
    # inspect pipe.setex.call_args_list and pipe.execute.call_count.
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    return r


# ---------------------------------------------------------------------------
# AC1 — hit does NOT call the model
# ---------------------------------------------------------------------------


def test_ac1_cache_hit_skips_encoder() -> None:
    """Second batch with same text → encoder.encode never called; vector identical."""
    encoder = _FakeEncoder()
    posts = [_norm("hello world")]
    model_name = "all-MiniLM-L6-v2"

    # Pre-seed: vector that would be returned by encoder for "hello world"
    seed = int(hashlib.md5(b"hello world").hexdigest()[:8], 16) % 1000
    cached_vec = [float(seed)] + [0.0] * (EMBEDDING_DIM - 1)
    cached_json = json.dumps(cached_vec)

    redis = _make_redis_mock(get_return=[cached_json.encode()])

    with patch("pipeline.batch_processor.get_settings") as mock_settings:
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 0, "encoder must NOT be called on cache hit"
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert vectors[0] == cached_vec


# ---------------------------------------------------------------------------
# AC2 — cache miss: model called, Redis key/TTL/JSON stored
# ---------------------------------------------------------------------------


def test_ac2_cache_miss_calls_model_and_stores_in_redis() -> None:
    """On miss: encoder called, key embed:{model}:{sha256}, TTL=48h, JSON len=EMBEDDING_DIM."""
    from pipeline.constants import EMBEDDING_CACHE_KEY_PREFIX, EMBEDDING_CACHE_TTL_SECONDS

    assert EMBEDDING_CACHE_TTL_SECONDS == 48 * 60 * 60, "TTL constant must be 48h"

    encoder = _FakeEncoder()
    text = "breaking news article"
    posts = [_norm(text)]
    model_name = "all-MiniLM-L6-v2"

    redis = _make_redis_mock(get_return=[None])

    with patch("pipeline.batch_processor.get_settings") as mock_settings:
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM

    # Validate Redis pipeline write — misses are batched via pipeline().setex() + execute().
    expected_key = _cache_key(model_name, text)
    pipe = redis.pipeline.return_value
    assert redis.pipeline.call_count == 1, "pipeline() must be called once for miss writes"
    assert pipe.execute.call_count == 1, "pipeline.execute() must be called to flush writes"
    assert pipe.setex.call_count == 1, "one miss → one pipeline.setex call"

    setex_call = pipe.setex.call_args
    stored_key = setex_call.args[0] if setex_call.args else setex_call.kwargs.get("name")
    stored_ttl = setex_call.args[1] if len(setex_call.args) > 1 else setex_call.kwargs.get("time")
    stored_val = setex_call.args[2] if len(setex_call.args) > 2 else setex_call.kwargs.get("value")

    assert stored_key == expected_key, f"key mismatch: {stored_key!r} != {expected_key!r}"
    expected_ttl = EMBEDDING_CACHE_TTL_SECONDS
    assert stored_ttl == expected_ttl, f"TTL mismatch: {stored_ttl} != {expected_ttl}"

    parsed = json.loads(stored_val)
    assert len(parsed) == EMBEDDING_DIM, (
        f"stored JSON vector length {len(parsed)} != {EMBEDDING_DIM}"
    )
    # Key starts with correct prefix
    assert stored_key.startswith(f"{EMBEDDING_CACHE_KEY_PREFIX}:"), "key must start with 'embed:'"


# ---------------------------------------------------------------------------
# AC3 — mixed batch [cached, new, cached] preserves original order
# ---------------------------------------------------------------------------


def test_ac3_mixed_batch_order_preserved() -> None:
    """[cached, new, cached] → output vectors parallel to posts in original order."""
    encoder = _FakeEncoder()
    model_name = "all-MiniLM-L6-v2"

    text_a = "cached post A"
    text_b = "new post B"
    text_c = "cached post C"

    vec_a = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    vec_c = [3.0] + [0.0] * (EMBEDDING_DIM - 1)

    posts = [_norm(text_a), _norm(text_b), _norm(text_c)]

    # mget returns [cached_A, None, cached_C]
    redis = MagicMock()
    redis.mget.return_value = [
        json.dumps(vec_a).encode(),
        None,
        json.dumps(vec_c).encode(),
    ]

    with patch("pipeline.batch_processor.get_settings") as mock_settings:
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert len(vectors) == 3

    # Position 0 and 2 should be from cache (identical to what we seeded)
    assert vectors[0] == vec_a, "first vector (cached) must match cache"
    assert vectors[2] == vec_c, "third vector (cached) must match cache"

    # Position 1 should be computed by encoder
    assert encoder.call_count == 1
    assert encoder.last_texts == [text_b], "encoder should only process the uncached text"
    assert len(vectors[1]) == EMBEDDING_DIM


# ---------------------------------------------------------------------------
# AC4 — fail-open: errors and corrupt data → computed by model, warn logged
# ---------------------------------------------------------------------------


def test_ac4_redis_get_raises_fail_open(caplog: pytest.LogCaptureFixture) -> None:
    """redis.mget raises → fall through to model, warn logged, no raise."""
    encoder = _FakeEncoder()
    posts = [_norm("some text")]
    model_name = "all-MiniLM-L6-v2"

    redis = MagicMock()
    redis.mget.side_effect = ConnectionError("redis down")

    with (
        caplog.at_level(logging.WARNING, logger="pipeline.batch_processor"),
        patch("pipeline.batch_processor.get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    # At least one warning logged
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_ac4_redis_set_raises_fail_open(caplog: pytest.LogCaptureFixture) -> None:
    """pipeline.execute raises after a miss → warn logged, vector still returned, no raise."""
    encoder = _FakeEncoder()
    posts = [_norm("new uncached text")]
    model_name = "all-MiniLM-L6-v2"

    redis = _make_redis_mock(get_return=[None])
    # Simulate pipeline.execute() raising — the fail-open guard must catch it.
    redis.pipeline.return_value.execute.side_effect = ConnectionError("redis down on write")

    with (
        caplog.at_level(logging.WARNING, logger="pipeline.batch_processor"),
        patch("pipeline.batch_processor.get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_ac4_corrupt_json_falls_back_to_model(caplog: pytest.LogCaptureFixture) -> None:
    """Cached value is not valid JSON → treated as miss, model called, warn logged."""
    encoder = _FakeEncoder()
    posts = [_norm("some text")]
    model_name = "all-MiniLM-L6-v2"

    redis = _make_redis_mock(get_return=[b"not-json-at-all!!!"])

    with (
        caplog.at_level(logging.WARNING, logger="pipeline.batch_processor"),
        patch("pipeline.batch_processor.get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    # Corrupt key should be overwritten via pipeline
    pipe = redis.pipeline.return_value
    assert pipe.setex.called, "corrupt key must be overwritten via pipeline.setex"
    assert pipe.execute.called, "pipeline.execute() must be called to flush the overwrite"


def test_ac4_wrong_dimension_falls_back_to_model(caplog: pytest.LogCaptureFixture) -> None:
    """Cached value has wrong vector length → treated as miss, model called, warn logged."""
    encoder = _FakeEncoder()
    posts = [_norm("some text")]
    model_name = "all-MiniLM-L6-v2"

    # Wrong dimension: only 10 floats
    wrong_vec = json.dumps([0.5] * 10)
    redis = _make_redis_mock(get_return=[wrong_vec.encode()])

    with (
        caplog.at_level(logging.WARNING, logger="pipeline.batch_processor"),
        patch("pipeline.batch_processor.get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    # Corrupt key should be overwritten with correct vector via pipeline
    pipe = redis.pipeline.return_value
    assert pipe.setex.called, "wrong-dim key must be overwritten via pipeline.setex"
    assert pipe.execute.called, "pipeline.execute() must be called to flush the overwrite"


# ---------------------------------------------------------------------------
# AC4 — fail-open when redis is None
# ---------------------------------------------------------------------------


def test_ac4_none_redis_falls_back_to_model() -> None:
    """redis=None → embed_with_cache behaves like direct embed.run (no cache, no crash)."""
    encoder = _FakeEncoder()
    posts = [_norm("text without cache")]

    vectors = batch_processor.embed_with_cache(None, posts, encoder=encoder)

    assert encoder.call_count == 1
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Fix-1 — element-type validation: string-element vector → miss + overwrite
# ---------------------------------------------------------------------------


def test_string_element_vector_treated_as_miss_and_overwritten(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cached JSON list of correct length but string elements → miss, warn, key overwritten.

    A vector like '["a", "b", ...]' passes the list/length check but its elements
    are not numeric, so np.asarray would produce dtype=object and crash cluster.run.
    The fix must treat it as corrupt: fall back to the encoder, log a warning, and
    overwrite the key via pipeline with the freshly computed float vector.
    """
    encoder = _FakeEncoder()
    text = "some article text"
    posts = [_norm(text)]
    model_name = "all-MiniLM-L6-v2"

    # Correct-length list of strings — passes isinstance(list) + len but not numeric.
    string_vec = json.dumps(["a"] * EMBEDDING_DIM)
    redis = _make_redis_mock(get_return=[string_vec.encode()])

    with (
        caplog.at_level(logging.WARNING, logger="pipeline.batch_processor"),
        patch("pipeline.batch_processor.get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    # Encoder must have been called (treated as miss).
    assert encoder.call_count == 1, "encoder must be called when cached elements are strings"
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    # All returned elements must be floats.
    assert all(isinstance(x, float) for x in vectors[0])

    # Warning must have been logged.
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a WARNING must be logged for the corrupt string-element vector"
    )

    # Key must be overwritten via pipeline with the valid computed vector.
    pipe = redis.pipeline.return_value
    assert pipe.setex.called, "corrupt key must be overwritten via pipeline.setex"
    assert pipe.execute.called, "pipeline.execute() must flush the overwrite"

    # The value written to cache must be a JSON float vector.
    setex_call = pipe.setex.call_args
    stored_val = setex_call.args[2] if len(setex_call.args) > 2 else setex_call.kwargs.get("value")
    parsed = json.loads(stored_val)
    assert len(parsed) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in parsed), (
        "overwritten cache value must contain only floats"
    )


# ---------------------------------------------------------------------------
# Fix-2 — within-batch duplicate dedup: 2 identical texts → encoder sees 1
# ---------------------------------------------------------------------------


def test_within_batch_duplicate_texts_encoded_once() -> None:
    """3 posts where 2 share identical text, all cold → encoder gets 2 unique texts.

    Both duplicates must receive the identical vector object; all 3 output slots
    must be filled; the pipeline must write 3 keys (one per miss index, duplicates
    each get their own cache key pointing to the same content).
    """
    encoder = _FakeEncoder()
    model_name = "all-MiniLM-L6-v2"

    text_shared = "shared breaking news"
    text_unique = "other unique text"

    posts = [_norm(text_shared), _norm(text_unique), _norm(text_shared)]

    # All three are cache misses.
    redis = _make_redis_mock(get_return=[None, None, None])

    with patch("pipeline.batch_processor.get_settings") as mock_settings:
        mock_settings.return_value.embedding_model_name = model_name
        vectors = batch_processor.embed_with_cache(redis, posts, encoder=encoder)

    # Encoder must have been called exactly once, for the 2 unique texts.
    assert encoder.call_count == 1, (
        f"encoder must be called once for 2 unique miss texts; got {encoder.call_count}"
    )
    assert len(encoder.last_texts) == 2, (
        f"encoder must receive 2 unique texts; got {encoder.last_texts!r}"
    )
    assert set(encoder.last_texts) == {text_shared, text_unique}

    # All 3 output slots must be filled.
    assert len(vectors) == 3
    assert all(len(v) == EMBEDDING_DIM for v in vectors)

    # Posts at index 0 and 2 share the same text → must get identical vectors.
    assert vectors[0] == vectors[2], (
        "duplicate posts with identical text must receive the same vector"
    )

    # All 3 miss slots must be written to cache (via pipeline).
    pipe = redis.pipeline.return_value
    assert pipe.setex.call_count == 3, (
        f"3 miss indices → 3 pipeline.setex calls; got {pipe.setex.call_count}"
    )
    assert pipe.execute.call_count == 1, "pipeline.execute() must be called once"
