"""Per-user batch pipeline body (task-007, AC5/AC6).

`process_user_batch(user_id)` is the plain function the locked Celery task
`pipeline.tasks.run_user_batch` calls inside its acquired lock. It:

1. resolves the user's distinct sources (channels across their watchlists),
2. drains those by-source Redis buffers (collector.buffer — idempotent read+clear),
3. runs the pure pipeline `dedup → normalize → embed → cluster`,
4. persists each resulting cluster as a `Cluster` row scoped by `user_id`
   (ClusterRepository, ADR-002), and returns the number of clusters persisted.

An empty buffer is a clean no-op: no Postgres write, returns 0 (AC5). The entry
point takes only `user_id` (JSON-serializable id, never an ORM object — CONVENTIONS).
Cross-module access is via storage/collector public service functions only.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.base import RawPost, SourceKind, SourceRef
from collector.buffer import drain_source
from pipeline.steps import cluster, dedup, embed, normalize
from pipeline.steps.cluster import ClusterCandidate
from storage.database import get_session
from storage.models import Channel, Cluster, Watchlist
from storage.models.channels import SourceKind as ChannelSourceKind
from storage.redis_client import get_redis_client
from storage.repositories.cluster_repo import ClusterRepository

logger = logging.getLogger(__name__)

# The storage `Channel.source_kind` enum and the collector `SourceKind` are distinct
# StrEnums (different modules/layers); map by value so the buffer key matches what
# the collector wrote (`raw:{kind}:{handle}`). Both are platform StrEnums.
_KIND_BY_VALUE: dict[str, SourceKind] = {k.value: k for k in SourceKind}


def _channel_source_kind_to_collector(kind: ChannelSourceKind) -> SourceKind:
    """Map a storage `Channel.source_kind` to the collector `SourceKind` by value."""
    return _KIND_BY_VALUE[kind.value]


def user_source_refs(session: Session, user_id: int) -> list[SourceRef]:
    """Return the distinct `SourceRef`s the user watches (channels across watchlists).

    Read-only join `watchlists → channels` filtered by `user_id` (tenant-scoped,
    ADR-002). Distinct so a channel on several watchlists is read once.
    """
    stmt = (
        select(Channel.source_kind, Channel.handle)
        .join(Watchlist, Watchlist.channel_id == Channel.id)
        .where(Watchlist.user_id == user_id)
        .distinct()
    )
    rows = session.execute(stmt).all()
    return [
        SourceRef(kind=_channel_source_kind_to_collector(source_kind), handle=handle)
        for source_kind, handle in rows
    ]


def _candidate_to_cluster(candidate: ClusterCandidate, user_id: int) -> Cluster:
    """Build a tenant-scoped `Cluster` ORM row from a pipeline `ClusterCandidate`."""
    return Cluster(
        user_id=user_id,
        topic=candidate.topic,
        embedding=list(candidate.embedding),
    )


def _run_pipeline(posts: list[RawPost]) -> list[ClusterCandidate]:
    """Pure chain: dedup → normalize → embed → cluster. No I/O."""
    deduped = dedup.run(posts)
    normalized = normalize.run(deduped)
    vectors = embed.run(normalized)
    return cluster.run(normalized, vectors)


def process_user_batch(user_id: int) -> int:
    """Drain the user's buffers, run the pipeline, persist clusters. Returns count.

    Empty buffer → early return 0 with no Postgres write (AC5). Clusters are
    persisted scoped by `user_id` (AC6).
    """
    redis = get_redis_client()
    with get_session() as session:
        refs = user_source_refs(session, user_id)

    posts: list[RawPost] = []
    for ref in refs:
        posts.extend(drain_source(redis, ref.kind, ref.handle))

    if not posts:
        logger.info("process_user_batch no-op (empty buffer) user_id=%s", user_id)
        return 0

    candidates = _run_pipeline(posts)
    if not candidates:
        logger.info("process_user_batch produced no clusters user_id=%s", user_id)
        return 0

    repo = ClusterRepository()
    with get_session() as session:
        for candidate in candidates:
            repo.create(session, _candidate_to_cluster(candidate, user_id))

    logger.info(
        "process_user_batch persisted clusters user_id=%s count=%d",
        user_id,
        len(candidates),
    )
    return len(candidates)
