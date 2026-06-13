"""Offline scoring replay over the prod corpus "as if in time" (TASK-081).

Reuses the REAL scorer formula — `scorer.score.compute_components` /`ScoreInputs`
and the engagement weights (`FORWARD_FACTOR`, `REACTION_FACTOR`) — never
reimplementing it. What this module DOES reimplement, on snapshot records instead
of a live `Session`, is only the *input aggregation* that `scorer.tasks.
_build_score_inputs` does against the DB, applying the exact same rules:

  * per-cluster posts bounded to a recent rolling window
    (`posted_at >= anchor - score_window_seconds`, TASK-079);
  * views/forwards/reactions summed over in-window posts;
  * `delta_hours = (latest - earliest) / 3600` over in-window posts;
  * `delta_channel_count = unique_channels_count = #distinct channels in window`;
  * a cluster with NO in-window posts is SKIPPED (no score), mirroring the
    production `return None` → `continue`.

The "as if in time" anchor is each cluster's own `updated_at` — the timestamp at
which the production scorer last touched it — so the rolling window is evaluated
relative to that instant rather than wall-clock now (the corpus is a static export).

`channel_avg` CANNOT be replayed faithfully offline: the production value is a
per-channel 7-day historical AVG that excludes the cluster being scored and depends
on the live clock and on `engagement_baseline_min_posts` cold-channel fallback. We
reproduce the documented FALLBACK path (`channel_avg = sum(views)/len(posts)`,
`scorer.tasks._build_score_inputs`) and label engagement as a PROXY in the report —
this is the same value the live scorer uses for cold channels, which dominate a
0-alert corpus. `watched_channels_count` likewise has no corpus source (no live
watchlists), so cross_channel is reported under an explicit assumption.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from eval.corpus import ClusterRecord, PostRecord
from scorer.score import ScoreComponents, ScoreInputs, compute_components

# Seconds → hours for the velocity delta — mirrors scorer.tasks._SECONDS_PER_HOUR
# (kept local so the replay has no import-time dependency on the task module's
# private constant; value is the same named quantum).
_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class ClusterScore:
    """A replayed score for one cluster, with the components + provenance fields."""

    cluster_id: int
    user_id: int
    topic: str
    posts_in_window: int
    components: ScoreComponents


def _build_inputs_from_posts(
    posts: Sequence[PostRecord],
    *,
    watched_channels_count: int,
) -> ScoreInputs:
    """Aggregate in-window posts into `ScoreInputs` — same rules as `_build_score_inputs`.

    Uses the documented cold-channel fallback for `channel_avg`
    (``sum(views)/len(posts)``) since the live 7-day per-channel baseline is not
    reconstructable offline (see module docstring). `posts` is assumed non-empty
    (callers skip empty windows, mirroring production's ``return None``).
    """
    views = sum(p.views for p in posts)
    forwards = sum(p.forwards for p in posts)
    reactions = sum(p.reactions for p in posts)
    unique_channels = {p.channel_id for p in posts}
    earliest = min(p.posted_at for p in posts)
    latest = max(p.posted_at for p in posts)
    delta_hours = (latest - earliest).total_seconds() / _SECONDS_PER_HOUR
    channel_avg = views / len(posts)  # documented fallback (proxy) — see docstring
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


def _posts_by_cluster(posts: Sequence[PostRecord]) -> dict[int, list[PostRecord]]:
    """Group posts by their (non-null) `cluster_id`."""
    grouped: dict[int, list[PostRecord]] = defaultdict(list)
    for post in posts:
        if post.cluster_id is not None:
            grouped[post.cluster_id].append(post)
    return dict(grouped)


def replay_scores(
    clusters: Sequence[ClusterRecord],
    posts: Sequence[PostRecord],
    *,
    score_window_seconds: int,
    watched_channels_count: int,
) -> list[ClusterScore]:
    """Replay the production viral score for every cluster "as if in time".

    For each cluster, the rolling window is anchored at the cluster's `updated_at`
    (the moment the live scorer last evaluated it) and includes only posts with
    ``posted_at >= updated_at - score_window_seconds``. Clusters with no in-window
    posts are skipped (no `ClusterScore`), exactly as production returns `None`.
    """
    by_cluster = _posts_by_cluster(posts)
    window = timedelta(seconds=score_window_seconds)
    results: list[ClusterScore] = []
    for cluster in clusters:
        cluster_posts = by_cluster.get(cluster.id, [])
        window_start = cluster.updated_at - window
        in_window = [p for p in cluster_posts if p.posted_at >= window_start]
        if not in_window:
            continue
        inputs = _build_inputs_from_posts(in_window, watched_channels_count=watched_channels_count)
        results.append(
            ClusterScore(
                cluster_id=cluster.id,
                user_id=cluster.user_id,
                topic=cluster.topic,
                posts_in_window=len(in_window),
                components=compute_components(inputs),
            )
        )
    return results


def lead_time_proxy_hours(posts: Sequence[PostRecord]) -> float | None:
    """Median per-cluster spread time (hours) from first to peak-engagement post.

    A PROXY for "lead time": for each multi-post cluster, measure the hours between
    the cluster's first post and its highest-engagement post (views + forwards·F +
    reactions·R). It is NOT a true mainstream-vs-detection lead time (no external
    mainstream-date labels exist in the corpus) — it approximates how long a story
    takes to peak inside the watched channels. Returns None if no qualifying cluster.
    """
    from scorer.score import engagement_numerator

    spreads: list[float] = []
    for cluster_posts in _posts_by_cluster(posts).values():
        if len(cluster_posts) < 2:
            continue
        first = min(cluster_posts, key=lambda p: p.posted_at)
        peak = max(
            cluster_posts,
            key=lambda p: engagement_numerator(
                views=p.views, forwards=p.forwards, reactions=p.reactions
            ),
        )
        delta = (peak.posted_at - first.posted_at).total_seconds() / _SECONDS_PER_HOUR
        if delta > 0:
            spreads.append(delta)
    if not spreads:
        return None
    from eval.distribution import percentile

    return percentile(spreads, 50)
