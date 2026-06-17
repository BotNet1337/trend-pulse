"""Per-watchlist live-signal aggregation (TASK-096, read-only, tenant-scoped).

A watchlist's "live signal" on the Signal Desk is an aggregate over the `Score`
and `Alert` rows of the CLUSTERS the watchlist's channel participates in. The
linkage is by **channel overlap** (TASK-084), NOT by `topic` string equality:
`Cluster.topic` is free text (a post snippet) while `Watchlist.topic` is a
category label — they can never be equal, so a topic-equality join would always
return nothing (the prod bug TASK-084 fixed). Instead:

    Watchlist.channel_id
      → Post.channel_id (+ Post.user_id, Post.posted_at >= now - 24h)
      → distinct Post.cluster_id
      → Score / Alert of those clusters

So the signal for a watchlist channel = the latest in-window `Score` (velocity +
viral_score), the hourly max-viral_score series over the last 24h, and the most
recent `Alert.first_seen`, restricted to clusters whose in-window posts appeared
on that channel, scoped to the user.

Efficiency (INV3, no N+1): the whole list's signal is built from a fixed number
of grouped queries keyed by `channel_id`, regardless of how many watchlists the
user owns. `aggregate_for_user(...)` returns `{channel_id: WatchlistSignalData}`;
the service maps it onto each row. Nothing here writes — pure read DTOs (INV4/5).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage.models.alerts import Alert
from storage.models.base import utcnow
from storage.models.posts import Post
from storage.models.scores import Score

# 24h live-signal window — matches the "Live signal (24h)" desk column and the
# sparkline span. Named, never a magic literal (CONVENTIONS).
_SIGNAL_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class WatchlistSignalData:
    """Aggregated live signal for one watchlist channel (graceful empties).

    `live_velocity` / `live_score` are `None` and `sparkline_24h` is empty when
    the channel has no in-window scores; `last_alert_at` is `None` when there is
    no alert (INV2 — never fabricated).
    """

    live_velocity: float | None = None
    live_score: float | None = None
    sparkline_24h: tuple[float, ...] = field(default_factory=tuple)
    last_alert_at: datetime | None = None
    # exp(source-entropy) of the latest in-window score (TASK-126): the effective
    # number of independent sources — an organic-spread / independence signal, NOT a
    # coordination verdict. `None` when there is no in-window score OR the score row
    # predates the migration (graceful NULL — INV2, never fabricated).
    effective_sources: float | None = None


# Empty signal reused for channels with no data (immutable, safe to share).
EMPTY_SIGNAL = WatchlistSignalData()


def _channel_clusters(
    session: Session,
    *,
    user_id: int,
    channel_ids: Sequence[int],
    window_start: datetime,
) -> dict[int, set[int]]:
    """Map each watched `channel_id` → the set of cluster ids it participated in.

    A cluster participates in a channel when it has ≥1 in-window post on that
    channel (channel-overlap join, TASK-084). One grouped query over the user's
    in-window posts on the watched channels; posts with no cluster are skipped.
    """
    if not channel_ids:
        return {}
    stmt = (
        select(Post.channel_id, Post.cluster_id)
        .where(Post.user_id == user_id)
        .where(Post.channel_id.in_(channel_ids))
        .where(Post.cluster_id.is_not(None))
        .where(Post.posted_at >= window_start)
        .distinct()
    )
    mapping: dict[int, set[int]] = {}
    for channel_id, cluster_id in session.execute(stmt).all():
        mapping.setdefault(channel_id, set()).add(cluster_id)
    return mapping


def _scores_by_cluster(
    session: Session,
    *,
    user_id: int,
    cluster_ids: Sequence[int],
    window_start: datetime,
) -> dict[int, list[tuple[datetime, float, float, float | None]]]:
    """Map `cluster_id` → in-window scores `(computed_at, viral_score, velocity, eff_sources)`.

    One query over all relevant clusters' scores; the caller buckets them per
    channel. Scores are upserted per `(user_id, cluster_id)`, so this is at most
    one row per cluster today, but the code treats it as a series so a future
    history table needs no change here. `effective_sources` (TASK-126) is selected on
    the SAME row (no extra query / no N+1) and is `None` for pre-migration rows.
    """
    if not cluster_ids:
        return {}
    stmt = (
        select(
            Score.cluster_id,
            Score.computed_at,
            Score.viral_score,
            Score.velocity,
            Score.effective_sources,
        )
        .where(Score.user_id == user_id)
        .where(Score.cluster_id.in_(cluster_ids))
        .where(Score.computed_at >= window_start)
    )
    mapping: dict[int, list[tuple[datetime, float, float, float | None]]] = {}
    for cluster_id, computed_at, viral_score, velocity, effective_sources in session.execute(
        stmt
    ).all():
        mapping.setdefault(cluster_id, []).append(
            (computed_at, viral_score, velocity, effective_sources)
        )
    return mapping


def _last_alert_by_cluster(
    session: Session,
    *,
    user_id: int,
    cluster_ids: Sequence[int],
) -> dict[int, datetime]:
    """Map `cluster_id` → its most recent `Alert.first_seen` (one grouped query)."""
    if not cluster_ids:
        return {}
    stmt = (
        select(Alert.cluster_id, func.max(Alert.first_seen))
        .where(Alert.user_id == user_id)
        .where(Alert.cluster_id.in_(cluster_ids))
        .group_by(Alert.cluster_id)
    )
    return {cluster_id: last_seen for cluster_id, last_seen in session.execute(stmt).all()}


def _hour_bucket(moment: datetime) -> datetime:
    """Truncate a timestamp to the start of its hour (sparkline bucket key)."""
    return moment.replace(minute=0, second=0, microsecond=0)


def _build_signal(
    cluster_ids: set[int],
    *,
    scores_by_cluster: dict[int, list[tuple[datetime, float, float, float | None]]],
    last_alert_by_cluster: dict[int, datetime],
) -> WatchlistSignalData:
    """Assemble one channel's signal from its clusters' scores + alerts."""
    # Flatten this channel's score points across its clusters.
    points: list[tuple[datetime, float, float, float | None]] = []
    for cluster_id in cluster_ids:
        points.extend(scores_by_cluster.get(cluster_id, ()))

    if not points:
        live_velocity: float | None = None
        live_score: float | None = None
        sparkline: tuple[float, ...] = ()
        effective_sources: float | None = None
    else:
        # Latest in-window score → live velocity + live score + independence (TASK-126).
        latest = max(points, key=lambda p: p[0])
        live_score = latest[1]
        live_velocity = latest[2]
        effective_sources = latest[3]
        # Hourly max viral_score, oldest → newest (max one bucket per hour).
        buckets: dict[datetime, float] = {}
        for computed_at, viral_score, _velocity, _effective_sources in points:
            key = _hour_bucket(computed_at)
            current = buckets.get(key)
            if current is None or viral_score > current:
                buckets[key] = viral_score
        sparkline = tuple(buckets[hour] for hour in sorted(buckets))

    # Most recent alert across this channel's clusters (None when none).
    last_alert_at: datetime | None = None
    for cluster_id in cluster_ids:
        candidate = last_alert_by_cluster.get(cluster_id)
        if candidate is not None and (last_alert_at is None or candidate > last_alert_at):
            last_alert_at = candidate

    return WatchlistSignalData(
        live_velocity=live_velocity,
        live_score=live_score,
        sparkline_24h=sparkline,
        last_alert_at=last_alert_at,
        effective_sources=effective_sources,
    )


def aggregate_for_user(
    session: Session, *, user_id: int, channel_ids: Sequence[int]
) -> dict[int, WatchlistSignalData]:
    """Live signal per watched `channel_id` for a user (TASK-096, no N+1).

    Returns `{channel_id: WatchlistSignalData}` covering every requested channel
    (channels with no in-window data map to `EMPTY_SIGNAL`). Built from a fixed
    set of grouped queries (posts → clusters, scores, alerts) regardless of how
    many channels are passed — INV3.
    """
    distinct_channel_ids = list(dict.fromkeys(channel_ids))  # de-dup, keep order
    if not distinct_channel_ids:
        return {}

    window_start = utcnow() - timedelta(seconds=_SIGNAL_WINDOW_SECONDS)

    channel_clusters = _channel_clusters(
        session,
        user_id=user_id,
        channel_ids=distinct_channel_ids,
        window_start=window_start,
    )
    all_cluster_ids = sorted({cid for ids in channel_clusters.values() for cid in ids})

    scores_by_cluster = _scores_by_cluster(
        session,
        user_id=user_id,
        cluster_ids=all_cluster_ids,
        window_start=window_start,
    )
    last_alert_by_cluster = _last_alert_by_cluster(
        session,
        user_id=user_id,
        cluster_ids=all_cluster_ids,
    )

    result: dict[int, WatchlistSignalData] = {}
    for channel_id in distinct_channel_ids:
        cluster_ids = channel_clusters.get(channel_id)
        if not cluster_ids:
            result[channel_id] = EMPTY_SIGNAL
            continue
        result[channel_id] = _build_signal(
            cluster_ids,
            scores_by_cluster=scores_by_cluster,
            last_alert_by_cluster=last_alert_by_cluster,
        )
    return result
