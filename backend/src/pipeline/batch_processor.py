"""Per-user batch pipeline body (task-007, AC5/AC6; task-037 embedding cache).

`process_user_batch(user_id)` is the plain function the locked Celery task
`pipeline.tasks.run_user_batch` calls inside its acquired lock. It:

1. resolves the user's distinct sources (channels across their watchlists),
2. drains those by-source Redis buffers (collector.buffer — idempotent read+clear),
3. runs the pure pipeline `dedup → normalize → embed → cluster`,
4. persists each resulting cluster scoped by `user_id`: a candidate either MERGES
   into the nearest fresh existing cluster of the same user (cross-batch continuity,
   task-080 — `_find_mergeable_cluster`) or creates a new `Cluster` row (session.add
   + flush to obtain `cluster.id`). Either way that cluster's member posts are then
   persisted as `Post` rows carrying `cluster_id` + the `channel_id` resolved by
   (source_kind, handle) — this is the post↔cluster link the per-cluster scorer
   reads (task-022). Returns the number of clusters touched (merged + created).

task-080: clustering is per-batch (`cluster.run` sees only this batch), so the same
recurring topic used to spawn a NEW cluster every tick. The persist step now reuses
an existing cluster when centroids are similar (cosine >= `cluster_merge_cosine_threshold`)
and it is recent (`updated_at` within `cluster_merge_window_seconds`), updating that
cluster's centroid as a running mean over members. Merges happen under the per-user
batch lock (`max_instances=1`), so no two batches race the same user.

An empty buffer is a clean no-op: no Postgres write, returns 0 (AC5). A post whose
channel can't be resolved is skipped with a warning (never aborts the batch). The
entry point takes only `user_id` (JSON-serializable id, never an ORM object —
CONVENTIONS). Cross-module access is via storage/collector public service functions only.

task-037: `embed_with_cache(redis, posts, encoder)` is the I/O-layer cache wrapper.
It lives here (not inside `embed.run`) to preserve pipeline-step purity (CONVENTIONS).
`_run_pipeline` is kept pure by accepting pre-computed `vectors` instead of calling
`embed.run` itself; `process_user_batch` computes vectors via `embed_with_cache` and
passes them in.
"""

import hashlib
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collector.base import RawPost, SourceKind, SourceRef
from collector.buffer import drain_source
from config import get_settings
from observability import log_event
from pipeline.constants import EMBEDDING_CACHE_KEY_PREFIX, EMBEDDING_CACHE_TTL_SECONDS
from pipeline.steps import cluster, dedup, embed, normalize
from pipeline.steps.cluster import ClusterCandidate
from pipeline.steps.embed import Encoder
from pipeline.steps.normalize import NormalizedPost
from storage.database import get_session
from storage.models import EMBEDDING_DIM, Channel, Cluster, Watchlist
from storage.models.base import utcnow
from storage.models.channels import SourceKind as ChannelSourceKind
from storage.models.posts import Post
from storage.redis_client import get_redis_client

if TYPE_CHECKING:
    from redis import Redis

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


def _find_mergeable_cluster(
    session: Session,
    user_id: int,
    centroid: list[float],
) -> Cluster | None:
    """Return the nearest fresh existing cluster to merge `centroid` into, or None.

    Cross-batch continuity fix (TASK-080): instead of always creating a new `Cluster`
    row for each batch candidate, attach it to an EXISTING cluster of the same user
    whose centroid is close enough (cosine-similarity >= `cluster_merge_cosine_threshold`),
    that is recent (`updated_at >= now - cluster_merge_window_seconds`), AND that has
    not exceeded its max lifetime (`first_seen >= now - cluster_max_span_seconds`).

    The span cap (scoring-v2) stops a DAILY recurring template from keeping one cluster
    perpetually "fresh" and chaining it for months: once a cluster is older than the
    span, a new one seeds instead of merging — so a viral EVENT stays one cluster while
    boilerplate can't accrete into a corpus-spanning mega-cluster (real-data eval).

    pgvector's ``<=>`` operator (``Vector.cosine_distance``) returns cosine DISTANCE
    = ``1 - cosine_similarity``. So "similarity >= threshold" is equivalent to
    "distance <= 1 - threshold". The query is bounded by user + freshness + span,
    filtered by that max distance, and ordered nearest-first with LIMIT 1 (the NN lookup).

    TASK-123: this merge site uses the LOOSER `cluster_merge_cosine_threshold` (0.65),
    NOT the tight `cluster_cosine_threshold` (0.75) that intra-batch grouping/dedup
    (`pipeline/steps/cluster.py`) uses. Different channels paraphrase one story, so their
    centroids sit below the tight dedup cutoff; the loose tier lets "the same story across
    channels" collapse into ONE cluster (`channels_count > 1` — cross-channel breadth)
    without loosening intra-batch dedup. The config invariant guarantees the merge
    threshold never exceeds the tight one.
    """
    settings = get_settings()
    max_distance = 1.0 - settings.cluster_merge_cosine_threshold
    now = utcnow()
    window_start = now - timedelta(seconds=settings.cluster_merge_window_seconds)
    span_start = now - timedelta(seconds=settings.cluster_max_span_seconds)
    distance = Cluster.embedding.cosine_distance(centroid)
    stmt = (
        select(Cluster)
        .where(Cluster.user_id == user_id)
        .where(Cluster.updated_at >= window_start)
        .where(Cluster.first_seen >= span_start)
        .where(distance <= max_distance)
        .order_by(distance)
        .limit(1)
    )
    return session.scalars(stmt).first()


def _existing_member_count(session: Session, cluster_id: int) -> int:
    """Number of `Post` rows already attached to `cluster_id` (centroid weight)."""
    stmt = select(func.count()).select_from(Post).where(Post.cluster_id == cluster_id)
    return int(session.scalar(stmt) or 0)


def _merged_centroid(
    old_centroid: list[float],
    old_count: int,
    new_centroid: list[float],
    new_count: int,
) -> list[float]:
    """Running mean of two centroids weighted by their member counts.

    Immutable: returns a NEW list, mutates neither input. Falls back to the new
    centroid when the combined weight is zero (degenerate / empty cluster).
    """
    total = old_count + new_count
    if total <= 0:
        return list(new_centroid)
    return [
        (old * old_count + new * new_count) / total
        for old, new in zip(old_centroid, new_centroid, strict=True)
    ]


def _embedding_for_post(vector: tuple[float, ...] | None) -> list[float] | None:
    """Return a persistable per-post embedding, or None when it can't be trusted.

    task-082: persist the SAME vector the pipeline already computed for clustering so
    it survives the 48h text purge (go-forward backtests / vector ML). The 384-d
    invariant (EMBEDDING_DIM) is enforced here too — if a vector is missing or the
    wrong dimension we persist NULL (embedding is nullable) rather than crashing the
    batch or corrupting pgvector.
    """
    if vector is None or len(vector) != EMBEDDING_DIM:
        return None
    return list(vector)


def _build_handle_to_channel_id(
    session: Session,
    posts: list[NormalizedPost],
) -> dict[tuple[str, str], int]:
    """Return mapping of (source_kind_value, handle) → channel_id for all post sources.

    Queries Channel once (no N+1). Posts without a matching Channel are logged and
    skipped — the caller guards against missing keys.
    """
    handles = {post.source.handle for post in posts}
    if not handles:
        return {}
    stmt = select(Channel.id, Channel.source_kind, Channel.handle).where(
        Channel.handle.in_(handles)
    )
    result = session.execute(stmt).all()
    return {(str(row.source_kind.value), row.handle): row.id for row in result}


def embed_with_cache(
    redis: "Redis | None",
    posts: list[NormalizedPost],
    encoder: Encoder | None = None,
) -> list[list[float]]:
    """Return embedding vectors for `posts`, reading/writing a Redis cache.

    Cache key: ``embed:{model_name}:{sha256(post.text)}``.
    Cache value: JSON-serialised list[float] of length EMBEDDING_DIM.
    TTL: EMBEDDING_CACHE_TTL_SECONDS (48 h).

    Fail-open contract: any Redis error or corrupt cached value is treated as a
    miss — the model is called and a warning is logged. The pipeline never fails
    because the cache is unavailable. When ``redis`` is None the function
    degrades gracefully to a direct ``embed.run`` call (identical behaviour to
    pre-cache code).
    """
    if not posts:
        return []

    model_name = get_settings().embedding_model_name

    # --- fast path: no Redis ---
    if redis is None:
        return embed.run(posts, encoder=encoder)

    texts = [p.text for p in posts]
    keys = [
        f"{EMBEDDING_CACHE_KEY_PREFIX}:{model_name}:{hashlib.sha256(t.encode()).hexdigest()}"
        for t in texts
    ]

    # --- batch fetch from Redis ---
    try:
        raw_values: list[bytes | None] = cast(list[bytes | None], redis.mget(keys))
    except Exception as exc:
        logger.warning(
            "embed_with_cache: redis.mget failed (%s), falling back to model",
            type(exc).__name__,
        )
        raw_values = [None] * len(posts)

    # --- parse cached entries; treat invalid entries as misses ---
    cached: list[list[float] | None] = []
    for idx, raw in enumerate(raw_values):
        if raw is None:
            cached.append(None)
            continue
        try:
            vec: list[float] = json.loads(raw)
            length = len(vec) if isinstance(vec, list) else "?"
            if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
                raise ValueError(f"cached vector at index {idx} has wrong length {length}")
            # Reject booleans and non-numeric elements — bool is a subclass of int
            # in Python so the isinstance check must exclude it explicitly.
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vec):
                raise ValueError(f"cached vector at index {idx} contains non-numeric elements")
            cached.append(vec)
        except Exception as exc:
            logger.warning(
                "embed_with_cache: corrupt cached value at key %s (%s), treating as miss",
                keys[idx],
                type(exc).__name__,
            )
            cached.append(None)

    # --- identify uncached positions and compute missing vectors ---
    miss_indices = [i for i, v in enumerate(cached) if v is None]
    miss_posts = [posts[i] for i in miss_indices]

    # De-duplicate miss texts so identical texts are encoded only once.
    # unique_miss_texts preserves first-seen order; text_to_vector maps back.
    text_to_vector: dict[str, list[float]] = {}
    if miss_posts:
        seen: dict[str, int] = {}
        unique_miss_posts: list[NormalizedPost] = []
        for p in miss_posts:
            if p.text not in seen:
                seen[p.text] = len(unique_miss_posts)
                unique_miss_posts.append(p)
        unique_computed = embed.run(unique_miss_posts, encoder=encoder)
        for p, vec in zip(unique_miss_posts, unique_computed, strict=True):
            text_to_vector[p.text] = vec

    # Map miss positions back to their computed vectors (duplicates reuse same vector).
    computed: list[list[float]] = [text_to_vector[posts[i].text] for i in miss_indices]

    # --- merge: fill miss slots with computed vectors ---
    result: list[list[float]] = []
    computed_iter = iter(computed)
    for hit in cached:
        if hit is not None:
            result.append(hit)
        else:
            result.append(next(computed_iter))

    # --- write new entries to Redis via pipeline (fail-open) ---
    if miss_indices:
        try:
            pipe = redis.pipeline(transaction=False)
            for i, miss_idx in enumerate(miss_indices):
                pipe.setex(keys[miss_idx], EMBEDDING_CACHE_TTL_SECONDS, json.dumps(computed[i]))
            pipe.execute()
        except Exception as exc:
            logger.warning(
                "embed_with_cache: redis pipeline write failed (%s), continuing",
                type(exc).__name__,
            )

    hits = len(posts) - len(miss_indices)
    log_event("embed_cache", hits=hits, misses=len(miss_indices), model=model_name)

    return result


def _run_pipeline(
    posts: list[RawPost],
    vectors: list[list[float]] | None = None,
) -> list[ClusterCandidate]:
    """Pure chain: dedup → normalize → (embed if vectors not provided) → cluster.

    Accepts pre-computed ``vectors`` from the I/O layer (``embed_with_cache``) so
    the cache lives outside this pure function. When ``vectors`` is None the step
    falls back to ``embed.run`` directly — preserving backward-compatibility and
    enabling independent unit testing of the pure chain.
    """
    deduped = dedup.run(posts)
    normalized = normalize.run(deduped)
    if vectors is None:
        vectors = embed.run(normalized)
    return cluster.run(normalized, vectors)


def process_user_batch(user_id: int) -> int:
    """Drain the user's buffers, run the pipeline, persist clusters. Returns count.

    Empty buffer → early return 0 with no Postgres write (AC5). Clusters are
    persisted scoped by `user_id` (AC6).

    task-037: embedding vectors are computed via ``embed_with_cache`` at the I/O
    layer (here) so the pure ``_run_pipeline`` chain receives pre-computed vectors
    and ``embed.run`` is never called for texts already in the Redis cache.
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

    # Compute vectors at the I/O boundary using the embedding cache (task-037).
    # dedup + normalize happen inside _run_pipeline (pure), but we need the
    # normalized texts for the cache keys. We run them here for cache lookup only;
    # _run_pipeline runs its own dedup+normalize step so nothing is skipped.
    deduped_for_cache = dedup.run(posts)
    normalized_for_cache = normalize.run(deduped_for_cache)
    precomputed_vectors = embed_with_cache(redis, normalized_for_cache)

    candidates = _run_pipeline(posts, vectors=precomputed_vectors)
    if not candidates:
        logger.info("process_user_batch produced no clusters user_id=%s", user_id)
        return 0

    # Collect all normalized posts from all candidates for handle→channel_id lookup.
    all_normalized: list[NormalizedPost] = [
        np_post for candidate in candidates for np_post in candidate.posts
    ]

    with get_session() as session:
        handle_to_channel_id = _build_handle_to_channel_id(session, all_normalized)
        for candidate in candidates:
            candidate_centroid = list(candidate.embedding)
            # Cross-batch merge (TASK-080): attach to the nearest fresh existing
            # cluster of the same user when centroids are similar; else create new.
            existing = _find_mergeable_cluster(session, user_id, candidate_centroid)
            if existing is not None:
                # Refresh centroid as a running mean weighted by current members,
                # then mark the cluster recently-updated so it stays mergeable/fresh.
                old_count = _existing_member_count(session, existing.id)
                existing.embedding = _merged_centroid(
                    list(existing.embedding),
                    old_count,
                    candidate_centroid,
                    len(candidate.posts),
                )
                existing.updated_at = utcnow()
                cluster_row = existing
            else:
                cluster_row = _candidate_to_cluster(candidate, user_id)
                session.add(cluster_row)
                session.flush()  # obtain cluster_row.id before persisting posts

            # Pair each member post with its own embedding (parallel to posts). When
            # a candidate carries no per-post vectors (defensive: directly-built
            # candidates), fall back to None so embedding persists as NULL.
            post_vectors: tuple[tuple[float, ...] | None, ...] = candidate.post_embeddings or (
                (None,) * len(candidate.posts)
            )
            for np_post, post_vector in zip(candidate.posts, post_vectors, strict=False):
                kind_value = str(np_post.source.kind.value)
                channel_id = handle_to_channel_id.get((kind_value, np_post.source.handle))
                if channel_id is None:
                    logger.warning(
                        "process_user_batch: no Channel handle=%s kind=%s "
                        "user_id=%s — post skipped",
                        np_post.source.handle,
                        kind_value,
                        user_id,
                    )
                    continue
                session.add(
                    Post(
                        user_id=user_id,
                        channel_id=channel_id,
                        cluster_id=cluster_row.id,
                        external_id=np_post.external_id,
                        views=np_post.metrics.views,
                        forwards=np_post.metrics.forwards,
                        reactions=np_post.metrics.reactions,
                        # task-082: persist the per-post vector the pipeline already
                        # computed (NULL on dimension drift / missing — never crash).
                        embedding=_embedding_for_post(post_vector),
                        posted_at=np_post.posted_at,
                    )
                )

    logger.info(
        "process_user_batch persisted clusters user_id=%s count=%d",
        user_id,
        len(candidates),
    )
    return len(candidates)
