"""AC5/AC6/AC7 — batch_processor: empty buffer no-op, persists scoped by user_id.

Infra-free: the DB session, Redis client, buffer drain, source resolution and the
cluster repository are all patched. A fake encoder stands in for the model, so no
torch is imported. We assert clusters are persisted with the right `user_id` and
that the entry point takes a plain `int`.
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


def test_entry_point_takes_plain_int() -> None:
    sig = inspect.signature(batch_processor.process_user_batch)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "user_id"
    assert params[0].annotation is int


def test_empty_buffer_is_no_op_no_persist() -> None:
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session"),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=[]),
        patch.object(batch_processor, "ClusterRepository") as repo_cls,
    ):
        result = batch_processor.process_user_batch(7)

    assert result == 0
    # No repository instantiated / no create called → no Postgres write (AC5).
    repo_cls.assert_not_called()


def test_persists_clusters_scoped_by_user_id() -> None:
    user_id = 42
    refs = [SourceRef(kind=SourceKind.TELEGRAM, handle="@chan")]
    posts = [_raw("1", "alpha news today"), _raw("2", "beta different story")]
    repo = MagicMock()

    with (
        patch.object(batch_processor, "get_redis_client", return_value=MagicMock()),
        patch.object(batch_processor, "get_session"),
        patch.object(batch_processor, "user_source_refs", return_value=refs),
        patch.object(batch_processor, "drain_source", return_value=posts),
        patch.object(batch_processor, "ClusterRepository", return_value=repo),
        patch.object(batch_processor.embed, "_get_model", return_value=_FakeEncoder()),
    ):
        result = batch_processor.process_user_batch(user_id)

    assert result == repo.create.call_count
    assert result >= 1
    # Every persisted Cluster row is scoped to the given user_id (AC6).
    for call in repo.create.call_args_list:
        cluster_row = call.args[1]
        assert cluster_row.user_id == user_id


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
