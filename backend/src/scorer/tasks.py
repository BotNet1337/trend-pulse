"""Scorer task body (task-008): per-user fresh-cluster scoring + alert trigger.

`score_recent_clusters()` is the plain function the beat-scheduled Celery seam
`pipeline.tasks.score_tick` (task-006) delegates to — there is exactly ONE
scheduled scorer tick, registered in `pipeline.tasks` (kept there so the existing
`include`/route/queue wiring is untouched), whose body is this module. For each
active user it walks their FRESH clusters (recent by `Cluster.updated_at`, within
`scorer_recent_window_seconds`), derives a platform-independent `ScoreInputs` from
that cluster's own `Post` rows, computes the viral score (`scorer.score`), upserts
a `Score` row, and — when the cluster matches a watched topic AND
`viral_score > that watchlist's threshold` — creates exactly one `Alert`.

Topic matching (TASK-084, prod-verified root cause): a cluster is matched to a
watched topic by **CHANNEL OVERLAP**, NOT by topic-string equality. `Cluster.topic`
is free text (the first post's `text[:255]`, e.g. «Паоло Ардоино: …»), while
`Watchlist.topic` is a CATEGORY label (e.g. "crypto"/"tech"); they can NEVER be
equal, so the old `topic_configs.get(cluster.topic)` lookup was always `None` and
the scorer persisted ZERO `Score` rows in prod (9,400+ clusters, 0 scores). Instead
we compute the cluster's channel set (the distinct `channel_id` of its in-window
posts) and pick the watched topic whose `_TopicConfig.channel_ids` has the LARGEST
intersection with that set — ties broken deterministically by topic name. A cluster
with no watched-channel overlap is skipped (no score, no alert). Best-overlap (not
per-topic) preserves the "one cluster → one Score / one Alert" invariant below.

Input sourcing (task-022, per-cluster): each `Post` carries a `cluster_id` FK
(set at batch-persist time, `pipeline.batch_processor`), so score inputs are
aggregated from the posts of THAT cluster (`Post.cluster_id == cluster.id`), not
from all posts on the topic's channels — one cluster, one real engagement signal
(removes the duplicate-alerts-per-topic problem of the old per-topic approximation).
The `cross_channel` denominator (`watched_channels_count`) still comes from the
user's watchlist config for the topic. Cluster freshness (`_recent_clusters`) bounds
which clusters are scored, but a fresh cluster can still carry posts spanning days,
so the per-cluster post query is ALSO bounded to a recent rolling window
(`score_window_seconds`, TASK-079): velocity/engagement measure a recent burst, not
the cluster's whole lifetime. A cluster with no posts inside that window is skipped.

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

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billing.limits import effective_plan
from billing.plans import Plan
from config import get_settings
from observability.logging import log_event
from scorer.score import FORWARD_FACTOR, REACTION_FACTOR, ScoreInputs, compute_components
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

# Rate-guard sliding window (seconds): matches the alerts_per_hour_limit semantics.
# Always 1 hour — a named constant so there is no magic literal at the call site.
_RATE_GUARD_WINDOW_SECONDS: int = 3600


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


def _cluster_channel_ids(
    session: Session, *, user_id: int, cluster_id: int, window_start: datetime
) -> frozenset[int]:
    """Distinct `channel_id` of the cluster's posts inside the score window (TASK-084).

    The cluster's channel set is the basis for channel-overlap topic matching. It is
    bounded to the SAME recent rolling window (`score_window_seconds`) that
    `_build_score_inputs` uses, so matching and scoring see a consistent post set: a
    long-lived cluster's stale posts on a since-unwatched channel must not change the
    match. Returns an empty set when the cluster has no in-window posts (caller skips).
    """
    stmt = (
        select(Post.channel_id)
        .where(Post.user_id == user_id)
        .where(Post.cluster_id == cluster_id)
        .where(Post.posted_at >= window_start)
        .distinct()
    )
    return frozenset(session.scalars(stmt).all())


def _match_topic_by_channels(
    topic_configs: dict[str, _TopicConfig], cluster_channels: frozenset[int]
) -> tuple[str, _TopicConfig] | None:
    """Pick the watched topic with the LARGEST channel overlap (TASK-084).

    A cluster's posts span one or more channels; a user watches each topic across a
    set of channels (`_TopicConfig.channel_ids`). The cluster is matched to the topic
    whose watched-channel set intersects the cluster's channels the most. Ties are
    broken deterministically by topic name (ascending) so a given cluster always maps
    to the same topic across ticks — preserving the idempotent one-cluster→one-alert
    invariant. Returns ``None`` when NO watched topic shares a channel with the
    cluster (the caller skips: no score, no alert — AC5).
    """
    best: tuple[int, str, _TopicConfig] | None = None
    for topic, config in topic_configs.items():
        overlap = len(config.channel_ids & cluster_channels)
        if overlap == 0:
            continue
        # Maximize overlap; tie-break on the SMALLEST topic name for determinism.
        if best is None or overlap > best[0] or (overlap == best[0] and topic < best[1]):
            best = (overlap, topic, config)
    if best is None:
        return None
    return best[1], best[2]


def _channel_historical_avg(
    session: Session,
    *,
    user_id: int,
    channel_id: int,
    exclude_cluster_id: int,
    window_start: datetime,
    min_posts: int,
) -> float | None:
    """Return the historical weighted-numerator average for a channel, or None on fallback.

    Computes AVG(views + forwards·F + reactions·R) over all posts of this
    (user_id, channel_id) pair with `posted_at >= window_start` (sliding window),
    excluding posts that belong to the cluster currently being scored. This prevents
    the current batch's signal from contaminating its own baseline — a spike would
    inflate the avg it is measured against, masking itself.

    Uses the `ix_posts_user_channel_posted` index on (user_id, channel_id, posted_at).

    Returns `None` when:
    - fewer than `min_posts` posts exist in the window (cold-channel fallback), OR
    - the computed avg is ≤ 0 (zero-engagement guard).
    The caller is responsible for emitting ``log_event("baseline_fallback")`` on None.
    """
    # NB: must mirror scorer.score.engagement_numerator() — same weighted formula in SQL.
    weighted_expr = Post.views + Post.forwards * FORWARD_FACTOR + Post.reactions * REACTION_FACTOR
    stmt = (
        select(
            func.count().label("post_count"),
            func.avg(weighted_expr).label("avg_numerator"),
        )
        .where(Post.user_id == user_id)
        .where(Post.channel_id == channel_id)
        .where(Post.posted_at >= window_start)
        .where(
            (Post.cluster_id == None)  # noqa: E711 — SQLAlchemy IS NULL comparison
            | (Post.cluster_id != exclude_cluster_id)
        )
    )
    row = session.execute(stmt).one()
    post_count: int = row.post_count or 0
    avg_numerator: float | None = row.avg_numerator

    if post_count < min_posts or avg_numerator is None or avg_numerator <= 0:
        return None
    return float(avg_numerator)


def _build_score_inputs(
    session: Session,
    *,
    user_id: int,
    cluster_id: int,
    watched_channels_count: int,
) -> ScoreInputs | None:
    """Aggregate a cluster's RECENT posts into ScoreInputs (per-cluster, not per-topic).

    Reads posts scoped by `(user_id, cluster_id)` — the FK added in migration 0007 —
    AND bounded to a recent rolling window (`posted_at >= now - score_window_seconds`,
    TASK-079). The score must measure a recent burst, not a cluster's whole lifetime:
    a long-lived cluster keeps accruing posts across days, which would stretch
    `delta_hours` (collapsing velocity) and dilute engagement with stale posts. Only
    posts inside the window feed views/forwards/reactions, the `delta_hours` span and
    the unique-channel counts.

    Returns ``None`` when the cluster has NO posts inside the score window — the
    caller skips it cleanly (no Score row, no alert), instead of emitting a polluting
    0-score row. This window is DISTINCT from the `channel_avg` historical baseline
    (`engagement_baseline_window_seconds`, TASK-041), which is a separate per-channel
    denominator and is intentionally left unchanged.

    `channel_avg` is the historical weighted-numerator average over the per-channel
    sliding window (`engagement_baseline_window_seconds`). When fewer than
    `engagement_baseline_min_posts` posts exist in that baseline window, or the avg is
    zero/null (cold channel), the scorer falls back to the batch-avg of the in-window
    cluster posts (legacy behaviour) and emits a ``baseline_fallback`` log event so the
    fraction of cold channels is visible in observability.
    """
    settings = get_settings()
    score_window_start = utcnow() - timedelta(seconds=settings.score_window_seconds)
    stmt = (
        select(Post)
        .where(Post.user_id == user_id)
        .where(Post.cluster_id == cluster_id)
        .where(Post.posted_at >= score_window_start)
    )
    posts = list(session.scalars(stmt).all())
    if not posts:
        # No posts inside the recent window → skip cleanly (no score / no alert).
        # (A cluster may still be "fresh" by updated_at yet carry only stale posts.)
        return None

    views = sum(p.views for p in posts)
    forwards = sum(p.forwards for p in posts)
    reactions = sum(p.reactions for p in posts)
    unique_channels = {p.channel_id for p in posts}
    earliest = min(p.posted_at for p in posts)
    latest = max(p.posted_at for p in posts)
    delta_hours = (latest - earliest).total_seconds() / _SECONDS_PER_HOUR

    # Historical channel_avg: use the channel of the first post as the reference
    # (per-cluster scoring; a cluster spans one or more channels — use the primary
    # channel, i.e. the first post's channel, for the baseline query).
    window_start = utcnow() - timedelta(seconds=settings.engagement_baseline_window_seconds)
    # Pick the most-represented channel in the cluster (most posts) as the baseline
    # reference — consistent with the "one engagement signal per cluster" design.
    primary_channel_id: int = max(
        unique_channels,
        key=lambda cid: sum(1 for p in posts if p.channel_id == cid),
    )
    channel_avg = _channel_historical_avg(
        session,
        user_id=user_id,
        channel_id=primary_channel_id,
        exclude_cluster_id=cluster_id,
        window_start=window_start,
        min_posts=settings.engagement_baseline_min_posts,
    )
    if channel_avg is None:
        # Cold channel (< min_posts in window) or zero avg → fallback to batch-avg.
        log_event("baseline_fallback", channel_id=primary_channel_id)
        # Legacy batch-avg: sum(views) / len(posts) — unchanged behaviour.
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
            channels_count=inputs.unique_channels_count,
            viral_score=components.viral_score,
            computed_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_scores_user_cluster",
            set_=dict(
                velocity=components.velocity,
                engagement=components.engagement,
                cross_channel=components.cross_channel,
                channels_count=inputs.unique_channels_count,
                viral_score=components.viral_score,
                computed_at=now,
            ),
        )
    )
    session.execute(stmt)
    session.flush()
    return components.viral_score


def check_rate_guard(
    session: Session,
    *,
    user_id: int,
    settings: "Settings",
) -> bool:
    """Rate-guard: True = skip (at/over hourly limit), False = allow creation.

    Counts the user's Alert rows with first_seen >= now - 1h (sliding window).
    If count >= alerts_per_hour_limit → skip + log_event("alert_rate_limited").

    The 1h window is a named constant (_RATE_GUARD_WINDOW_SECONDS), never a
    magic literal (CONVENTIONS). Only gates CREATION; idempotency / deliver_after
    semantics (TASK-040) are unaffected (guard fires before _create_alert_idempotent).
    """
    window_start = utcnow() - timedelta(seconds=_RATE_GUARD_WINDOW_SECONDS)
    count = session.scalar(
        select(func.count(Alert.id))
        .where(Alert.user_id == user_id)
        .where(Alert.first_seen >= window_start)
    )
    count = int(count) if count is not None else 0
    limit = settings.alerts_per_hour_limit
    if count >= limit:
        log_event(
            "alert_rate_limited",
            user_id=user_id,
            count=count,
            limit=limit,
        )
        return True
    return False


def check_group_guard(
    session: Session,
    *,
    user_id: int,
    cluster: Cluster,
    settings: "Settings",
) -> bool:
    """Group-guard: True = skip (duplicate topic in window), False = allow creation.

    Checks if the user already has an alert for the same topic (via alerts JOIN clusters)
    within alert_group_window_seconds.  Topic match via clusters.topic — MVP approach
    (no vector similarity; clusters already deduplicate semantics — Discussion).

    On skip: log_event("alert_group_limited") with user_id + cluster_id (NOT topic
    string — raw content invariant, TASK-039 learnings: topic may be raw user text).
    """
    window_start = utcnow() - timedelta(seconds=settings.alert_group_window_seconds)
    existing_alert_id = session.scalar(
        select(Alert.id)
        .join(Cluster, Alert.cluster_id == Cluster.id)
        .where(Alert.user_id == user_id)
        .where(Cluster.topic == cluster.topic)
        .where(Alert.first_seen >= window_start)
        .limit(1)
    )
    if existing_alert_id is not None:
        log_event(
            "alert_group_limited",
            user_id=user_id,
            cluster_id=cluster.id,
        )
        return True
    return False


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

    # Score window for channel-overlap matching — MUST mirror `_build_score_inputs`
    # so matching and scoring see the same in-window post set (TASK-084 / TASK-079).
    score_window_start = utcnow() - timedelta(seconds=settings.score_window_seconds)

    created: list[tuple[int, int | None]] = []
    for cluster in _recent_clusters(session, user_id=user_id, window_start=window_start):
        # Match by CHANNEL OVERLAP, not topic-string equality (TASK-084 root cause):
        # cluster.topic is free text, watchlist.topic is a category — never equal.
        cluster_channels = _cluster_channel_ids(
            session,
            user_id=user_id,
            cluster_id=cluster.id,
            window_start=score_window_start,
        )
        match = _match_topic_by_channels(topic_configs, cluster_channels)
        if match is None:
            # No watched-channel overlap (or no in-window posts) → no score, no alert (AC5).
            continue
        _topic, config = match

        inputs = _build_score_inputs(
            session,
            user_id=user_id,
            cluster_id=cluster.id,
            watched_channels_count=len(config.channel_ids),
        )
        if inputs is None:
            # No posts inside the score window (TASK-079) → no score, no alert.
            continue

        viral_score = _persist_score(session, user_id=user_id, cluster_id=cluster.id, inputs=inputs)
        if viral_score <= config.threshold:
            # Below (or at) threshold → no alert (AC3).
            continue

        # --- Anti-fatigue guards (TASK-043): both must pass before creation. ---
        # Rate-guard: max N new alerts per user per sliding 1h window.
        if check_rate_guard(session, user_id=user_id, settings=settings):
            continue
        # Group-guard: no duplicate (user, topic) alerts within group-window.
        if check_group_guard(session, user_id=user_id, cluster=cluster, settings=settings):
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
