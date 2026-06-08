"""Scorer task body (task-008): per-user fresh-cluster scoring + alert trigger.

`score_recent_clusters()` is the plain function the beat-scheduled Celery seam
`pipeline.tasks.score_tick` (task-006) delegates to — there is exactly ONE
scheduled scorer tick, registered in `pipeline.tasks` (kept there so the existing
`include`/route/queue wiring is untouched), whose body is this module. For each
active user it walks their FRESH clusters (recent by `Cluster.updated_at`, within
`scorer_recent_window_seconds`), derives a platform-independent `ScoreInputs` from
that user's recent `Post` rows, computes the viral score (`scorer.score`), persists
a `Score` row, and — when the cluster's topic matches a watched topic AND
`viral_score > that watchlist's threshold` — creates exactly one `Alert`.

Input sourcing (task-008 approximation): the `Cluster` model (task-002) stores
embedding/topic/timestamps but NOT metrics, and there is no post↔cluster FK. So the
score inputs are aggregated from the user's recent `Post` rows for the channels they
watch under the cluster's topic (views/forwards/reactions totals, unique channel
count, the posted_at time delta). A precise post↔cluster link is a future refinement.

Idempotency (AC6): an alert is unique per `(user_id, cluster_id)` via the DB unique
constraint `uq_alerts_user_cluster` (migration 0003) — a duplicate insert raises
`IntegrityError`, which is caught and skipped, so a repeated tick (or a race between
two ticks) never creates a second alert. Args are JSON-serializable (ids, not ORM —
CONVENTIONS); no platform/collector import (the scorer is platform-independent).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from scorer.score import ScoreInputs, compute_components
from storage.database import get_session
from storage.models.alerts import Alert
from storage.models.base import utcnow
from storage.models.clusters import Cluster
from storage.models.posts import Post
from storage.models.scores import Score
from storage.models.watchlists import Watchlist

logger = logging.getLogger(__name__)

# Seconds → hours conversion for the velocity time delta (named, not a magic literal).
_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class _TopicConfig:
    """Per-topic alert config aggregated from a user's watchlists for that topic."""

    threshold: float
    channel_ids: frozenset[int]


def list_active_user_ids(session: Session) -> list[int]:
    """Distinct ids of users with at least one watchlist (read-only).

    "Active" == owns a watchlist (only such users have topics/thresholds to score
    against). A pure read over `watchlists.user_id`; no model/migration change.
    """
    stmt = select(Watchlist.user_id).distinct()
    return list(session.scalars(stmt).all())


def _recent_clusters(
    session: Session, *, user_id: int, window_start: datetime
) -> Sequence[Cluster]:
    """The user's clusters updated within the freshness window (tenant-scoped)."""
    stmt = (
        select(Cluster).where(Cluster.user_id == user_id).where(Cluster.updated_at >= window_start)
    )
    return session.scalars(stmt).all()


def _topic_configs(session: Session, *, user_id: int) -> dict[str, _TopicConfig]:
    """Map each watched topic → its alert config (min threshold + watched channels).

    A user may watch a topic across several channels/watchlists; the topic is
    "watched" if any watchlist carries it. The effective threshold is the MINIMUM
    across those watchlists (alert if it crosses the most permissive bar), and the
    watched-channel set is the union (the `cross_channel` denominator).
    """
    stmt = select(Watchlist).where(Watchlist.user_id == user_id)
    configs: dict[str, list[Watchlist]] = {}
    for watchlist in session.scalars(stmt).all():
        configs.setdefault(watchlist.topic, []).append(watchlist)
    return {
        topic: _TopicConfig(
            threshold=min(w.threshold for w in watchlists),
            channel_ids=frozenset(w.channel_id for w in watchlists),
        )
        for topic, watchlists in configs.items()
    }


def _build_score_inputs(
    session: Session,
    *,
    user_id: int,
    channel_ids: frozenset[int],
    watched_channels_count: int,
    window_start: datetime,
) -> ScoreInputs:
    """Aggregate the user's recent posts (for the watched channels) into ScoreInputs.

    task-008 approximation (no post↔cluster FK): totals + unique channel count +
    the posted_at span over the user's recent posts on the topic's channels.
    `channel_avg` is the mean views across those posts (engagement denominator).
    Degenerate aggregates (no posts) yield zeroed inputs the formula guards handle.
    """
    stmt = (
        select(Post)
        .where(Post.user_id == user_id)
        .where(Post.channel_id.in_(channel_ids))
        .where(Post.posted_at >= window_start)
    )
    posts = list(session.scalars(stmt).all())
    if not posts:
        return ScoreInputs(
            views=0,
            forwards=0,
            reactions=0,
            channel_avg=0.0,
            delta_channel_count=0,
            delta_hours=0.0,
            unique_channels_count=0,
            watched_channels_count=watched_channels_count,
        )

    views = sum(p.views for p in posts)
    forwards = sum(p.forwards for p in posts)
    reactions = sum(p.reactions for p in posts)
    unique_channels = {p.channel_id for p in posts}
    earliest = min(p.posted_at for p in posts)
    latest = max(p.posted_at for p in posts)
    delta_hours = (latest - earliest).total_seconds() / _SECONDS_PER_HOUR
    channel_avg = views / len(posts)

    return ScoreInputs(
        views=views,
        forwards=forwards,
        reactions=reactions,
        channel_avg=channel_avg,
        delta_channel_count=len(unique_channels),
        delta_hours=delta_hours,
        unique_channels_count=len(unique_channels),
        watched_channels_count=watched_channels_count,
    )


def _persist_score(
    session: Session, *, user_id: int, cluster_id: int, inputs: ScoreInputs
) -> float:
    """Compute the score components, persist a `Score` row, return the viral score."""
    components = compute_components(inputs)
    session.add(
        Score(
            user_id=user_id,
            cluster_id=cluster_id,
            velocity=components.velocity,
            engagement=components.engagement,
            cross_channel=components.cross_channel,
            viral_score=components.viral_score,
        )
    )
    session.flush()
    return components.viral_score


def _create_alert_idempotent(
    session: Session,
    *,
    user_id: int,
    cluster: Cluster,
    score: float,
    channels_count: int,
) -> bool:
    """Insert an `Alert` for `(user_id, cluster_id)`; skip if it already exists.

    A pre-check `SELECT` short-circuits the common already-alerted case, and the
    insert itself is wrapped in a SAVEPOINT (`begin_nested`) guarded by the
    `uq_alerts_user_cluster` unique constraint (migration 0003): a concurrent tick
    that inserted first raises `IntegrityError`, which rolls back ONLY this savepoint
    (not the surrounding transaction's earlier work) and is treated as a no-op
    (AC6 — idempotent, race-safe). Returns True iff a new alert was created.
    """
    existing = session.scalar(
        select(Alert.id).where(Alert.user_id == user_id).where(Alert.cluster_id == cluster.id)
    )
    if existing is not None:
        return False
    try:
        with session.begin_nested():
            session.add(
                Alert(
                    user_id=user_id,
                    cluster_id=cluster.id,
                    score=score,
                    channels_count=channels_count,
                    first_seen=cluster.first_seen,
                )
            )
    except IntegrityError:
        return False
    return True


def _score_user(session: Session, *, user_id: int, window_start: datetime) -> int:
    """Score one user's fresh clusters; create alerts on topic-match + threshold.

    Returns the number of alerts created this tick (0 when none cross/match).
    """
    topic_configs = _topic_configs(session, user_id=user_id)
    if not topic_configs:
        return 0

    alerts_created = 0
    for cluster in _recent_clusters(session, user_id=user_id, window_start=window_start):
        config = topic_configs.get(cluster.topic)
        if config is None:
            # Topic-mismatch (or unclassified topic) → no alert (AC5). No score.
            continue

        inputs = _build_score_inputs(
            session,
            user_id=user_id,
            channel_ids=config.channel_ids,
            watched_channels_count=len(config.channel_ids),
            window_start=window_start,
        )
        viral_score = _persist_score(session, user_id=user_id, cluster_id=cluster.id, inputs=inputs)
        if viral_score <= config.threshold:
            # Below (or at) threshold → no alert (AC3).
            continue
        if _create_alert_idempotent(
            session,
            user_id=user_id,
            cluster=cluster,
            score=viral_score,
            channels_count=inputs.unique_channels_count,
        ):
            alerts_created += 1
    return alerts_created


def score_recent_clusters() -> int:
    """Scorer tick body: score every active user's fresh clusters into alerts (AC3-AC6).

    Returns the total number of alerts created across all users this tick. The beat
    seam `pipeline.tasks.score_tick` delegates here (one scheduled scorer tick).
    """
    settings = get_settings()
    window_start = utcnow() - timedelta(seconds=settings.scorer_recent_window_seconds)
    total_alerts = 0
    with get_session() as session:
        user_ids = list_active_user_ids(session)
    for user_id in user_ids:
        with get_session() as session:
            total_alerts += _score_user(session, user_id=user_id, window_start=window_start)
    logger.info("score_recent_clusters alerts_created=%d users=%d", total_alerts, len(user_ids))
    return total_alerts
