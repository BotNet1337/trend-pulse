"""Unit tests for showcase/selection.py (AC1, AC5).

Tests candidate selection logic:
- AC1: score >= min, age >= delay, inside 24h window, not already posted,
       daily cap not exhausted → best candidate returned.
- AC5: M posts today (UTC day) → no candidates returned until tomorrow.

All cutoffs are tested individually to ensure each filter is exercised.
DB-free: uses plain Python objects / in-memory data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


class FakeCluster(NamedTuple):
    """Minimal cluster DTO for selection tests (mimics Cluster fields used)."""

    id: int
    topic: str
    viral_score: float
    first_seen: datetime


class FakeSettings(NamedTuple):
    """Minimal settings DTO for selection tests."""

    showcase_post_min_score: float
    showcase_post_delay_seconds: int
    trending_window_seconds: int
    showcase_posts_per_day_max: int


_DEFAULTS = FakeSettings(
    showcase_post_min_score=85.0,
    showcase_post_delay_seconds=2400,
    trending_window_seconds=86_400,
    showcase_posts_per_day_max=8,
)


def _now() -> datetime:
    return datetime(2026, 6, 10, 14, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Import helper — tested module not yet written (RED phase)
# ---------------------------------------------------------------------------


def _import() -> object:
    """Defer import until test body — so RED phase captures ImportError cleanly."""
    from showcase import selection  # type: ignore[import]

    return selection


# ---------------------------------------------------------------------------
# AC1 — each filter cutoff
# ---------------------------------------------------------------------------


class TestScoreCutoff:
    """Clusters below min_score must not be candidates."""

    def test_cluster_below_min_score_rejected(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=1,
            topic="crypto",
            viral_score=84.9,  # below 85.0
            first_seen=now - timedelta(seconds=3000),  # old enough
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None

    def test_cluster_at_min_score_accepted(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=2,
            topic="crypto",
            viral_score=85.0,  # exactly at threshold
            first_seen=now - timedelta(seconds=2400),
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 2


class TestAgeCutoff:
    """Clusters younger than delay must not be candidates."""

    def test_cluster_too_young_rejected(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=3,
            topic="crypto",
            viral_score=90.0,
            first_seen=now - timedelta(seconds=2399),  # 1s too young
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None

    def test_cluster_exactly_at_delay_accepted(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=4,
            topic="crypto",
            viral_score=90.0,
            first_seen=now - timedelta(seconds=2400),  # exactly at delay
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 4


class TestWindowCutoff:
    """Clusters older than 24h window must not be candidates."""

    def test_cluster_outside_window_rejected(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=5,
            topic="crypto",
            viral_score=95.0,
            first_seen=now - timedelta(seconds=86_401),  # 1s beyond 24h
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None

    def test_cluster_inside_window_accepted(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=6,
            topic="crypto",
            viral_score=95.0,
            first_seen=now - timedelta(seconds=86_399),  # 1s inside 24h
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 6


class TestAlreadyPostedCutoff:
    """Clusters already posted must not be re-posted."""

    def test_already_posted_cluster_rejected(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=7,
            topic="crypto",
            viral_score=92.0,
            first_seen=now - timedelta(seconds=3000),
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids={7},  # already posted
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None

    def test_not_yet_posted_cluster_accepted(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=8,
            topic="crypto",
            viral_score=92.0,
            first_seen=now - timedelta(seconds=3000),
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids={99},  # different id posted
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 8


class TestBestCandidatePicked:
    """When multiple candidates qualify, the one with the highest score is picked."""

    def test_best_score_picked_among_candidates(self) -> None:
        sel = _import()
        now = _now()
        low = FakeCluster(
            id=10, topic="crypto", viral_score=86.0, first_seen=now - timedelta(seconds=3000)
        )
        high = FakeCluster(
            id=11, topic="crypto", viral_score=98.0, first_seen=now - timedelta(seconds=3600)
        )
        mid = FakeCluster(
            id=12, topic="crypto", viral_score=91.0, first_seen=now - timedelta(seconds=4000)
        )

        result = sel.pick_best_candidate(
            clusters=[low, high, mid],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 11  # highest score

    def test_empty_cluster_list_returns_none(self) -> None:
        sel = _import()
        now = _now()
        result = sel.pick_best_candidate(
            clusters=[],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None


# ---------------------------------------------------------------------------
# AC5 — daily cap
# ---------------------------------------------------------------------------


class TestDailyCap:
    """After M posts today, no more candidates until tomorrow (UTC day)."""

    def test_daily_cap_exhausted_returns_none(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=20, topic="crypto", viral_score=99.0, first_seen=now - timedelta(seconds=3000)
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=8,  # cap = 8, exhausted
            now=now,
            settings=_DEFAULTS,
        )
        assert result is None

    def test_one_below_daily_cap_returns_candidate(self) -> None:
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=21, topic="crypto", viral_score=99.0, first_seen=now - timedelta(seconds=3000)
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=7,  # cap = 8, one slot remains
            now=now,
            settings=_DEFAULTS,
        )
        assert result is not None
        assert result.id == 21

    def test_zero_cap_always_returns_none(self) -> None:
        """If showcase_posts_per_day_max = 0, no posts ever."""
        sel = _import()
        now = _now()
        cluster = FakeCluster(
            id=22, topic="crypto", viral_score=99.0, first_seen=now - timedelta(seconds=3000)
        )
        zero_cap_settings = FakeSettings(
            showcase_post_min_score=85.0,
            showcase_post_delay_seconds=2400,
            trending_window_seconds=86_400,
            showcase_posts_per_day_max=0,
        )
        result = sel.pick_best_candidate(
            clusters=[cluster],
            posted_cluster_ids=set(),
            posts_today=0,
            now=now,
            settings=zero_cap_settings,
        )
        assert result is None
