"""Showcase candidate selection — pure filter functions (TASK-044).

`pick_best_candidate(clusters, posted_cluster_ids, posts_today, now, settings)`
applies all cutoffs in order and returns the best qualifying cluster or None.

Cutoffs (all must pass):
1. viral_score >= showcase_post_min_score
2. age (now - first_seen) >= showcase_post_delay_seconds
3. first_seen within trending_window_seconds (not too old)
4. cluster_id NOT in posted_cluster_ids (not already posted / pending-fresh)
5. posts_today < showcase_posts_per_day_max (daily anti-spam cap)

After filtering, the cluster with the highest viral_score is returned.

Design:
- Pure functions (no I/O, no ORM imports): safe for unit tests without a DB.
- Callers (tasks.py) are responsible for querying clusters + posted_cluster_ids
  + posts_today from the DB and passing them here.
- `now` is injected (not datetime.now()) so tests can control time precisely.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Minimal protocols — selection is DB-agnostic
# ---------------------------------------------------------------------------


@runtime_checkable
class ClusterLike(Protocol):
    """Duck-typed cluster shape required by the selector.

    Attributes are read-only (declared as properties) so that both mutable
    ORM objects and immutable NamedTuples satisfy the Protocol in strict mypy.
    """

    @property
    def id(self) -> int: ...

    @property
    def topic(self) -> str: ...

    @property
    def viral_score(self) -> float: ...

    @property
    def first_seen(self) -> datetime: ...


@runtime_checkable
class SelectionSettings(Protocol):
    """Duck-typed settings shape required by the selector."""

    showcase_post_min_score: float
    showcase_post_delay_seconds: int
    trending_window_seconds: int
    showcase_posts_per_day_max: int


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def pick_best_candidate(
    *,
    clusters: Sequence[ClusterLike],
    posted_cluster_ids: set[int],
    posts_today: int,
    now: datetime,
    settings: SelectionSettings,
) -> ClusterLike | None:
    """Return the best showcase candidate or None if no cluster qualifies.

    Applies all five cutoffs (see module docstring) and picks the highest
    viral_score among the survivors.

    Args:
        clusters:           All showcase-tenant clusters in the 24h window
                            (caller queries from DB). Accepts any Sequence of
                            ClusterLike objects (list, tuple, etc.).
        posted_cluster_ids: Set of cluster_ids already in showcase_posts
                            (status=posted OR pending-fresh). Caller queries
                            from DB to fill this.
        posts_today:        Count of showcase_posts rows with status=posted
                            whose posted_at falls in the current UTC day.
                            Caller queries from DB.
        now:                Current UTC datetime (injected for testability).
        settings:           Settings instance (or duck-typed stub for tests).

    Returns:
        The qualifying cluster with the highest viral_score, or None.
    """
    # AC5: daily cap check first — if exhausted, reject everything immediately.
    if posts_today >= settings.showcase_posts_per_day_max:
        return None

    # Precompute time bounds.
    min_age = timedelta(seconds=settings.showcase_post_delay_seconds)
    max_age = timedelta(seconds=settings.trending_window_seconds)

    best: ClusterLike | None = None

    for cluster in clusters:
        # Ensure first_seen is timezone-aware for comparison with `now` (UTC).
        first_seen = cluster.first_seen
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=UTC)

        age = now - first_seen

        # Cutoff 1: score threshold.
        if cluster.viral_score < settings.showcase_post_min_score:
            continue

        # Cutoff 2: minimum age (cluster must be "proven" before posting).
        if age < min_age:
            continue

        # Cutoff 3: maximum age (must be inside the 24h window).
        if age > max_age:
            continue

        # Cutoff 4: not already posted (or pending-fresh).
        if cluster.id in posted_cluster_ids:
            continue

        # Survived all cutoffs → candidate.
        if best is None or cluster.viral_score > best.viral_score:
            best = cluster

    return best
