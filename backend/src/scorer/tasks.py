"""Scorer task body (task-008): per-user fresh-cluster scoring + alert trigger.

`score_recent_clusters()` is the plain function the beat-scheduled Celery seam
`pipeline.tasks.score_tick` (task-006) delegates to — there is exactly ONE
scheduled scorer tick, registered in `pipeline.tasks` (kept there so the existing
`include`/route/queue wiring is untouched), whose body is this module. For each
active user it walks their FRESH clusters (recent by `Cluster.updated_at`, within
`scorer_recent_window_seconds`), derives a platform-independent `ScoreInputs` from
that cluster's own `Post` rows, computes the viral score (`scorer.score`), upserts
a `Score` row, and — when the cluster's topic matches a watched topic AND
`viral_score > that watchlist's threshold` — creates exactly one `Alert`.

Input sourcing (task-022, per-cluster): each `Post` carries a `cluster_id` FK
(set at batch-persist time, `pipeline.batch_processor`), so score inputs are
aggregated from the posts of THAT cluster (`Post.cluster_id == cluster.id`), not
from all posts on the topic's channels — one cluster, one real engagement signal
(removes the duplicate-alerts-per-topic problem of the old per-topic approximation).
The `cross_channel` denominator (`watched_channels_count`) still comes from the
user's watchlist config for the topic. Cluster freshness (`_recent_clusters`) bounds
recency, so the per-cluster post query needs no separate `posted_at` window.

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
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billing.limits import effective_plan
from billing.plans import Plan
from config import get_settings
from scorer.score import ScoreInputs, compute_components
from storage.database import get_session
from storage.models.alerts import Alert
from storage.models.base import utcnow
from storage.models.clusters import Cluster
from storage.models.posts import Post
from storage.models.scores import Score
from storage.models.users import User
from storage.models.watchlists import Watchlist

if TYPE_CHECKING:
    from config import Settings

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
    cluster_id: int,
    watched_channels_count: int,
) -> ScoreInputs:
    """Aggregate a cluster's posts into ScoreInputs (per-cluster, not per-topic).

    Reads posts scoped by `(user_id, cluster_id)` — the FK added in migration 0007.
    This gives each cluster its own engagement signal, eliminating the per-topic
    duplicate-score problem. Degenerate aggregates (no posts) yield zeroed inputs
    the formula guards handle.
    """
    stmt = select(Post).where(Post.user_id == user_id).where(Post.cluster_id == cluster_id)
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
    """Compute score components, upsert a `Score` row, return the viral score.

    Uses PostgreSQL `ON CONFLICT DO UPDATE` on `uq_scores_user_cluster` so repeated
    scorer ticks for the same `(user_id, cluster_id)` update `computed_at` and
    score values in place — the `scores` table does not grow unboundedly (AC3).
    """
    components = compute_components(inputs)
    now = utcnow()
    stmt = (
        pg_insert(Score)
        .values(
            user_id=user_id,
            cluster_id=cluster_id,
            velocity=components.velocity,
            engagement=components.engagement,
            cross_channel=components.cross_channel,
            viral_score=components.viral_score,
            computed_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_scores_user_cluster",
            set_=dict(
                velocity=components.velocity,
                engagement=components.engagement,
                cross_channel=components.cross_channel,
                viral_score=components.viral_score,
                computed_at=now,
            ),
        )
    )
    session.execute(stmt)
    session.flush()
    return components.viral_score


def _create_alert_idempotent(
    session: Session,
    *,
    user_id: int,
    cluster: Cluster,
    score: float,
    channels_count: int,
    deliver_after: datetime | None = None,
) -> int | None:
    """Insert an `Alert` for `(user_id, cluster_id)`; skip if it already exists.

    A pre-check `SELECT` short-circuits the common already-alerted case, and the
    insert itself is wrapped in a SAVEPOINT (`begin_nested`) guarded by the
    `uq_alerts_user_cluster` unique constraint (migration 0003): a concurrent tick
    that inserted first raises `IntegrityError`, which rolls back ONLY this savepoint
    (not the surrounding transaction's earlier work) and is treated as a no-op
    (AC6 — idempotent, race-safe). Returns the NEW alert id iff one was created,
    else `None` (so the caller can enqueue delivery only for newly-created alerts).

    `deliver_after` (TASK-040): for Free-plan users this is set to
    `now + free_alert_delay_seconds`; for Pro/Team it is `None` (immediate delivery).
    """
    existing = session.scalar(
        select(Alert.id).where(Alert.user_id == user_id).where(Alert.cluster_id == cluster.id)
    )
    if existing is not None:
        return None
    alert = Alert(
        user_id=user_id,
        cluster_id=cluster.id,
        score=score,
        channels_count=channels_count,
        first_seen=cluster.first_seen,
        deliver_after=deliver_after,
    )
    try:
        with session.begin_nested():
            session.add(alert)
    except IntegrityError:
        return None
    session.flush()
    return alert.id


def _resolve_deliver_after(
    session: Session, *, user_id: int, settings: "Settings"
) -> datetime | None:
    """Compute deliver_after for a user given their effective plan (TASK-040).

    Returns ``now + free_alert_delay_seconds`` for Free users (including those with
    an expired paid subscription), ``None`` for Pro/Team (immediate delivery).
    """
    user = session.get(User, user_id)
    if user is None:
        # Defensive: unknown user → no delay (safe default).
        return None
    plan = effective_plan(session, user)
    if plan is Plan.FREE:
        return utcnow() + timedelta(seconds=settings.free_alert_delay_seconds)
    return None


def _score_user(
    session: Session, *, user_id: int, window_start: datetime
) -> list[tuple[int, int | None]]:
    """Score one user's fresh clusters; create alerts on topic-match + threshold.

    Returns a list of ``(alert_id, countdown_seconds)`` pairs for newly-created alerts
    (empty when none cross/match).  ``countdown_seconds`` is the Free-plan delay
    in seconds (TASK-040), or ``None`` for Pro/Team (immediate delivery).
    """
    settings = get_settings()
    topic_configs = _topic_configs(session, user_id=user_id)
    if not topic_configs:
        return []

    # Resolve the Free-plan delay once per user tick (same for all clusters).
    deliver_after = _resolve_deliver_after(session, user_id=user_id, settings=settings)
    countdown: int | None = settings.free_alert_delay_seconds if deliver_after is not None else None

    created: list[tuple[int, int | None]] = []
    for cluster in _recent_clusters(session, user_id=user_id, window_start=window_start):
        config = topic_configs.get(cluster.topic)
        if config is None:
            # Topic-mismatch (or unclassified topic) → no alert (AC5). No score.
            continue

        inputs = _build_score_inputs(
            session,
            user_id=user_id,
            cluster_id=cluster.id,
            watched_channels_count=len(config.channel_ids),
        )
        viral_score = _persist_score(session, user_id=user_id, cluster_id=cluster.id, inputs=inputs)
        if viral_score <= config.threshold:
            # Below (or at) threshold → no alert (AC3).
            continue
        alert_id = _create_alert_idempotent(
            session,
            user_id=user_id,
            cluster=cluster,
            score=viral_score,
            channels_count=inputs.unique_channels_count,
            deliver_after=deliver_after,
        )
        if alert_id is not None:
            created.append((alert_id, countdown))
    return created


def _enqueue_delivery(alert_id: int, *, countdown: int | None = None) -> None:
    """Enqueue alert delivery (task-009). Lazy import avoids a scorer↔alerts cycle.

    This is the sanctioned cross-task touch: the scorer hands a NEW alert id to the
    `alerts` domain via its public `dispatch_alert` task (CONVENTIONS: cross-module
    via service interfaces; JSON-serializable id, not an ORM object).

    `countdown` (TASK-040): if provided (Free-plan delay), Celery defers execution
    by that many seconds — an optimisation on top of the `deliver_after` field which
    is the authoritative source of truth (resweep + restarts read the field, not eta).
    """
    from alerts.tasks import dispatch_alert

    try:
        if countdown is not None:
            dispatch_alert.apply_async(args=(alert_id,), countdown=countdown)
        else:
            dispatch_alert.apply_async(args=(alert_id,))
    except Exception:
        # Broker unreachable / enqueue failure must NOT abort scoring (the alert row
        # is already committed). Logged, not swallowed. NOTE: the scorer is
        # idempotent (won't recreate the alert), so nothing currently re-enqueues a
        # 'pending' alert whose enqueue failed — a pending-alert re-dispatch sweep is
        # tracked for the ops/retention work (task-011).
        logger.warning("delivery enqueue failed for alert_id=%s (stays pending)", alert_id)


def score_recent_clusters() -> int:
    """Scorer tick body: score every active user's fresh clusters into alerts (AC3-AC6).

    Returns the total number of alerts created across all users this tick. The beat
    seam `pipeline.tasks.score_tick` delegates here (one scheduled scorer tick).
    Each newly-created alert is enqueued for delivery (task-009) AFTER its session
    commits, so the row is visible when `dispatch_alert` loads it; only newly-created
    alerts are enqueued (the scorer's idempotency is preserved).

    Free-plan alerts (TASK-040) are enqueued with a countdown equal to
    `free_alert_delay_seconds`; Pro/Team alerts are enqueued immediately (no countdown).
    """
    settings = get_settings()
    window_start = utcnow() - timedelta(seconds=settings.scorer_recent_window_seconds)
    created: list[tuple[int, int | None]] = []
    with get_session() as session:
        user_ids = list_active_user_ids(session)
    for user_id in user_ids:
        with get_session() as session:
            created.extend(_score_user(session, user_id=user_id, window_start=window_start))
    for alert_id, countdown in created:
        _enqueue_delivery(alert_id, countdown=countdown)
    logger.info(
        "score_recent_clusters alerts_created=%d users=%d",
        len(created),
        len(user_ids),
    )
    return len(created)
