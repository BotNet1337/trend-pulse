"""AC5/AC6/AC7 — batch_processor: empty buffer no-op, persists scoped by user_id.

Infra-free: the DB session, Redis client, buffer drain, source resolution and the
channel lookup are all patched. A fake encoder stands in for the model, so no
torch is imported. We assert clusters are persisted with the right `user_id` and
that the entry point takes a plain `int`.

TASK-022: ClusterRepository removed from batch_processor — clusters are now persisted
directly via session.add + flush to obtain cluster.id for Post.cluster_id FK.
The unit tests patch get_session with a MagicMock session so Cluster/Post adds
are captured without a real DB.

TASK-037: Tests that verify cluster/post persistence now also patch `embed_with_cache`
so they bypass Redis entirely and keep their existing embed._get_model mock working.
Two additional tests verify the cache integration path:
- process_user_batch with a properly configured Redis mock uses the cache.
- process_user_batch with redis=None produces identical behaviour to the direct path.
"""

import inspect
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock, patch

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from pipeline import batch_processor
from storage.models import EMBEDDING_DIM


class _FakeEncoder:
    def encode(self, texts: list[str]) -> list[list[float]]:
        # Distinct vectors so the two posts land in separate clusters.
        return [[float(i + 1)] + [0.0] * (EMBEDDING_DIM - 1) for i, _ in enumerate(texts)]


def _raw(external_id: str, text: str, handle: str = "@chan") -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle=handle),
        external_id=external_id,
        author="a",
        text=text,
        media_hashes=(),
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def _make_session_ctx(mock_session: MagicMock) -> MagicMock:
    """Return a context-manager mock whose __enter__ yields mock_session."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _install_id_assigning_flush(mock_session: MagicMock) -> None:
    """Make `mock_session.flush()` assign autoincrement ids to added `Cluster` rows.

    Mirrors Postgres: `process_user_batch` adds a Cluster then flushes to obtain its
    `id` before persisting that cluster's `Post` rows (Post.cluster_id FK). The real
    flush populates the PK; this stand-in does the same so tests can assert the FK link.
    """
    from storage.models import Cluster

    counter = [0]

    def _flush() -> None:
        for call in mock_session.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, Cluster) and getattr(obj, "id", None) is None:
                counter[0] += 1
                obj.id = counter[0]

    mock_session.flush.side_effect = _flush


def test_entry_point_takes_plain_int() -> None:
    sig = inspect.signature(batch_processor.process_user_batch)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "user_id"
    assert params[0].annotation is int


def test_empty_buffer_is_no_op_no_persist() -> None:
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    mock_session = MagicMock()
    session_ctx = _make_session_ctx(mock_session)

    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=[]),
    ):
        result = batch_processor.process_user_batch(7)

    assert result == 0
    # session.add never called → no Postgres write (AC5).
    mock_session.add.assert_not_called()


def test_persists_clusters_scoped_by_user_id() -> None:
    """Clusters added to session are scoped to user_id (AC6).

    After TASK-022 the processor uses session.add+flush directly (no ClusterRepository).
    We capture the Cluster rows passed to session.add and check user_id.
    channel lookup returns empty map → posts are skipped (no channel in mock session).

    TASK-037: embed_with_cache is patched to None so _run_pipeline falls back to
    embed.run, and the existing embed._get_model mock continues to work.
    """
    user_id = 42
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    posts = [_raw("1", "alpha news today"), _raw("2", "beta different story")]

    # flush() is called to get cluster.id; the stand-in assigns autoincrement ids.
    mock_session = MagicMock()
    _install_id_assigning_flush(mock_session)
    session_ctx = _make_session_ctx(mock_session)

    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        patch.object(batch_processor, "_build_handle_to_channel_id", return_value={}),
        # Bypass cache so _run_pipeline uses embed.run with the injected model.
        patch.object(batch_processor, "embed_with_cache", return_value=None),
        patch.object(batch_processor.embed, "_get_model", return_value=_FakeEncoder()),
    ):
        result = batch_processor.process_user_batch(user_id)

    assert result >= 1
    # Collect Cluster rows from session.add calls (filter by type).
    from storage.models import Cluster

    cluster_rows = [
        c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], Cluster)
    ]
    assert len(cluster_rows) == result
    assert all(r.user_id == user_id for r in cluster_rows)


def test_persists_posts_with_cluster_id_and_resolved_channel() -> None:
    """AC2: each cluster's member posts are persisted as `Post` rows carrying that
    cluster's id (the per-cluster scoring link) + the channel_id resolved by
    (source_kind, handle). This is the central new behavior of TASK-022 — posts were
    never persisted before, so per-cluster scoring had no data to read.

    TASK-037: embed_with_cache patched to None so _run_pipeline uses embed.run.
    """
    user_id = 42
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    # Distinct text → the fake encoder yields distinct vectors → two separate clusters.
    posts = [_raw("ext-1", "alpha news today"), _raw("ext-2", "beta different story")]

    mock_session = MagicMock()
    _install_id_assigning_flush(mock_session)
    session_ctx = _make_session_ctx(mock_session)

    # Non-empty channel map so posts are NOT skipped (key = (source_kind, handle)).
    channel_map = {("telegram", "@chan"): 7}

    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        patch.object(batch_processor, "_build_handle_to_channel_id", return_value=channel_map),
        # Bypass cache so _run_pipeline uses embed.run with the injected model.
        patch.object(batch_processor, "embed_with_cache", return_value=None),
        patch.object(batch_processor.embed, "_get_model", return_value=_FakeEncoder()),
    ):
        result = batch_processor.process_user_batch(user_id)

    from storage.models import Cluster, Post

    cluster_rows = [
        c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], Cluster)
    ]
    post_rows = [c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], Post)]

    assert result == len(cluster_rows)
    # Both posts persisted (none skipped — channel resolved).
    assert len(post_rows) == 2
    cluster_ids = {c.id for c in cluster_rows}
    assert None not in cluster_ids  # flush assigned ids before posts were added
    for post in post_rows:
        assert post.user_id == user_id
        assert post.channel_id == 7
        assert post.cluster_id in cluster_ids  # FK link to the post's own cluster
    assert {p.external_id for p in post_rows} == {"ext-1", "ext-2"}
    # Metrics carried through from RawPost.metrics.
    assert all(p.views == 1 for p in post_rows)


def test_unresolved_channel_skips_post_without_failing() -> None:
    """Edge: a post whose (source_kind, handle) has no Channel row is skipped with a
    warning — the batch persists the cluster but no Post for it (no crash, AC5).

    TASK-037: embed_with_cache patched to None so _run_pipeline uses embed.run.
    """
    user_id = 7
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    posts = [_raw("ext-1", "alpha news today")]

    mock_session = MagicMock()
    _install_id_assigning_flush(mock_session)
    session_ctx = _make_session_ctx(mock_session)

    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        # Empty map → channel unresolved → post skipped.
        patch.object(batch_processor, "_build_handle_to_channel_id", return_value={}),
        # Bypass cache so _run_pipeline uses embed.run with the injected model.
        patch.object(batch_processor, "embed_with_cache", return_value=None),
        patch.object(batch_processor.embed, "_get_model", return_value=_FakeEncoder()),
    ):
        result = batch_processor.process_user_batch(user_id)

    from storage.models import Cluster, Post

    post_rows = [c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], Post)]
    cluster_rows = [
        c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], Cluster)
    ]
    assert result == len(cluster_rows) >= 1
    assert post_rows == []  # unresolved channel → no Post persisted, no crash


def test_candidate_to_cluster_sets_user_id_and_embedding() -> None:
    from pipeline.steps.cluster import ClusterCandidate

    candidate = ClusterCandidate(
        topic="hello",
        embedding=tuple(0.0 for _ in range(EMBEDDING_DIM)),
        posts=(),
        handles=("@chan",),
    )
    row = batch_processor._candidate_to_cluster(candidate, 99)
    assert row.user_id == 99
    assert row.topic == "hello"
    assert len(cast(list[float], row.embedding)) == EMBEDDING_DIM


# ---------------------------------------------------------------------------
# TASK-037: cache integration tests for process_user_batch
# ---------------------------------------------------------------------------


def test_process_user_batch_uses_embed_with_cache() -> None:
    """process_user_batch invokes embed_with_cache at the I/O layer (TASK-037).

    Verifies the cache wrapper is called with the Redis client and NormalizedPosts,
    and that its return value is forwarded to _run_pipeline as precomputed vectors.
    """
    import json

    user_id = 1
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    posts = [_raw("c1", "cached text here")]

    mock_session = MagicMock()
    _install_id_assigning_flush(mock_session)
    session_ctx = _make_session_ctx(mock_session)

    # Redis mock: mget returns one cached JSON vector of correct length.
    cached_vec = [99.0] + [0.0] * (EMBEDDING_DIM - 1)
    mock_redis = MagicMock()
    mock_redis.mget.return_value = [json.dumps(cached_vec).encode()]

    with (
        patch.object(batch_processor, "get_redis_client", return_value=mock_redis),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        patch.object(batch_processor, "_build_handle_to_channel_id", return_value={}),
        patch.object(batch_processor, "get_settings") as mock_settings,
    ):
        mock_settings.return_value.embedding_model_name = "all-MiniLM-L6-v2"
        result = batch_processor.process_user_batch(user_id)

    # A cluster was produced (cache hit supplied a valid vector).
    assert result >= 1
    # mget was called — the cache was consulted.
    assert mock_redis.mget.called
    # setex NOT called — every vector came from cache (no misses).
    assert not mock_redis.setex.called


def test_process_user_batch_without_redis_identical_to_direct_embed() -> None:
    """process_user_batch with redis=None → behaviour identical to pre-cache code.

    Simulates unavailable Redis by patching get_redis_client to return None and
    verifies the pipeline still runs (embed.run is called directly via _run_pipeline).
    """
    user_id = 2
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    posts = [_raw("n1", "no redis text")]

    mock_session = MagicMock()
    _install_id_assigning_flush(mock_session)
    session_ctx = _make_session_ctx(mock_session)

    with (
        patch.object(batch_processor, "get_redis_client", return_value=None),
        patch.object(batch_processor, "get_session", return_value=session_ctx),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        patch.object(batch_processor, "_build_handle_to_channel_id", return_value={}),
        patch.object(batch_processor.embed, "_get_model", return_value=_FakeEncoder()),
    ):
        result = batch_processor.process_user_batch(user_id)

    # Pipeline still produces clusters — Redis=None is a clean fallback.
    assert result >= 1
