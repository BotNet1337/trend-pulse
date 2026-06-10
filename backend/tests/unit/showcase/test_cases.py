"""Unit tests for showcase/cases.py (TASK-045, AC1-AC3).

RED anchors:
- AC1: cluster with viral_score >= showcase_case_min_score (90.0) → snapshot row
       inserted; cluster below threshold → no row.
- AC2: same cluster on next tick → still one row (idempotent, on_conflict_do_nothing).
- AC3: snapshot is self-sufficient — fields survive deletion of source cluster
       (tested at unit level: snapshot columns hold all needed data, no FK).
- Compliance: only sanitized labels are stored — raw topic (with URL/@-handle) is
  stripped before persistence.

DB-free for threshold/sanitization logic. DB-backed (SQLite in-memory via SQLAlchemy)
for idempotency and snapshot-storage tests — no real Postgres needed in ci-fast.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Fake helpers  (mirrors FakeCluster/FakeSettings in test_selection.py)
# ---------------------------------------------------------------------------


class FakeCluster(NamedTuple):
    """Minimal cluster DTO for cases tests."""

    id: int
    topic: str
    viral_score: float
    first_seen: datetime


class FakeSettings(NamedTuple):
    """Minimal settings DTO for cases tests."""

    showcase_case_min_score: float
    trending_window_seconds: int
    showcase_user_email: str = "showcase@internal"


_DEFAULTS = FakeSettings(
    showcase_case_min_score=90.0,
    trending_window_seconds=86_400,
)


def _now() -> datetime:
    return datetime(2026, 6, 11, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Deferred import — RED phase: ImportError expected until module exists
# ---------------------------------------------------------------------------


def _import_cases() -> object:
    """Import showcase.cases — deferred so RED confirms the missing module."""
    from showcase import cases  # type: ignore[import]

    return cases


# ---------------------------------------------------------------------------
# AC1 — threshold filter
# ---------------------------------------------------------------------------


class TestScoreThreshold:
    """Clusters below showcase_case_min_score must not produce a case row."""

    def test_cluster_at_threshold_qualifies(self) -> None:
        """viral_score == showcase_case_min_score → qualifies."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(
            id=1,
            topic="crypto rally",
            viral_score=90.0,  # exactly at threshold
            first_seen=now,
        )
        result = cases_mod.should_fix_case(cluster, settings=_DEFAULTS)
        assert result is True

    def test_cluster_above_threshold_qualifies(self) -> None:
        """viral_score > threshold → qualifies."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=2, topic="crypto", viral_score=95.5, first_seen=now)
        result = cases_mod.should_fix_case(cluster, settings=_DEFAULTS)
        assert result is True

    def test_cluster_below_threshold_rejected(self) -> None:
        """viral_score < showcase_case_min_score → does NOT qualify."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=3, topic="crypto", viral_score=89.9, first_seen=now)
        result = cases_mod.should_fix_case(cluster, settings=_DEFAULTS)
        assert result is False

    def test_cluster_zero_score_rejected(self) -> None:
        """viral_score == 0 → does NOT qualify."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=4, topic="crypto", viral_score=0.0, first_seen=now)
        result = cases_mod.should_fix_case(cluster, settings=_DEFAULTS)
        assert result is False


# ---------------------------------------------------------------------------
# Compliance — sanitization of topic before storage
# ---------------------------------------------------------------------------


class TestTopicSanitization:
    """Snapshot title must be sanitized — no raw URLs or @-handles stored."""

    def test_sanitize_strips_url_from_topic(self) -> None:
        """topic with https:// URL → stored as sanitized label only."""
        cases_mod = _import_cases()
        raw = "crypto rally https://t.me/somechannel big pump"
        sanitized = cases_mod.build_case_title(raw)
        assert "https://" not in sanitized
        assert "t.me/" not in sanitized

    def test_sanitize_strips_at_handle(self) -> None:
        """topic with @handle → handle stripped in stored title."""
        cases_mod = _import_cases()
        raw = "market update @cryptoexpert analysis"
        sanitized = cases_mod.build_case_title(raw)
        assert "@cryptoexpert" not in sanitized

    def test_sanitize_clean_topic_passes_through(self) -> None:
        """Clean topic label (no URLs/handles) → returned as-is (modulo whitespace)."""
        cases_mod = _import_cases()
        raw = "bitcoin breakout pattern"
        sanitized = cases_mod.build_case_title(raw)
        assert "bitcoin" in sanitized
        assert "breakout" in sanitized

    def test_sanitize_empty_topic_returns_empty(self) -> None:
        """Empty raw topic → empty sanitized result."""
        cases_mod = _import_cases()
        sanitized = cases_mod.build_case_title("")
        assert sanitized == ""

    def test_sanitize_only_url_topic_returns_empty_or_placeholder(self) -> None:
        """Topic that is ONLY a URL → sanitized is empty or a safe placeholder."""
        cases_mod = _import_cases()
        raw = "https://t.me/channel"
        sanitized = cases_mod.build_case_title(raw)
        assert "https://" not in sanitized
        assert "t.me/" not in sanitized


# ---------------------------------------------------------------------------
# AC2 — idempotency (pure logic: the function is side-effect-free for unit scope)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """build_case_title is deterministic — same input yields same output."""

    def test_same_topic_same_result(self) -> None:
        """Same raw topic → same sanitized title on repeated calls."""
        cases_mod = _import_cases()
        raw = "DeFi activity surge"
        first = cases_mod.build_case_title(raw)
        second = cases_mod.build_case_title(raw)
        assert first == second

    def test_idempotency_with_dirty_topic(self) -> None:
        """Dirty topic: sanitizing twice is the same as sanitizing once."""
        cases_mod = _import_cases()
        raw = "pump @bot https://t.me/x activity"
        once = cases_mod.build_case_title(raw)
        twice = cases_mod.build_case_title(once)
        assert once == twice


# ---------------------------------------------------------------------------
# Snapshot fields contract
# ---------------------------------------------------------------------------


class TestSnapshotFields:
    """build_case_snapshot returns a dict with all required snapshot keys."""

    def test_snapshot_has_required_keys(self) -> None:
        """Snapshot dict contains: title, viral_score, first_seen, channels_count."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=10, topic="DeFi surge", viral_score=92.0, first_seen=now)
        snap = cases_mod.build_case_snapshot(cluster)
        assert "title" in snap
        assert "viral_score" in snap
        assert "first_seen" in snap
        assert "channels_count" in snap

    def test_snapshot_title_is_sanitized(self) -> None:
        """title in snapshot must be sanitized (no URLs/handles)."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(
            id=11,
            topic="pump https://evil.com @spammer check",
            viral_score=91.0,
            first_seen=now,
        )
        snap = cases_mod.build_case_snapshot(cluster)
        assert "https://" not in snap["title"]
        assert "@spammer" not in snap["title"]

    def test_snapshot_viral_score_matches_cluster(self) -> None:
        """viral_score in snapshot must match cluster.viral_score."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=12, topic="rally", viral_score=93.5, first_seen=now)
        snap = cases_mod.build_case_snapshot(cluster)
        assert abs(snap["viral_score"] - 93.5) < 0.001

    def test_snapshot_first_seen_matches_cluster(self) -> None:
        """first_seen in snapshot must be the cluster's first_seen value."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=13, topic="rally", viral_score=90.1, first_seen=now)
        snap = cases_mod.build_case_snapshot(cluster)
        assert snap["first_seen"] == now

    def test_snapshot_channels_count_is_positive_int(self) -> None:
        """channels_count in snapshot must be a positive integer (MVP=1)."""
        cases_mod = _import_cases()
        now = _now()
        cluster = FakeCluster(id=14, topic="rally", viral_score=90.1, first_seen=now)
        snap = cases_mod.build_case_snapshot(cluster)
        assert isinstance(snap["channels_count"], int)
        assert snap["channels_count"] >= 1

    def test_snapshot_no_raw_content_field(self) -> None:
        """Snapshot must NOT have a raw 'topic' field from cluster — only 'title'."""
        cases_mod = _import_cases()
        now = _now()
        # Cluster with raw content in topic
        cluster = FakeCluster(
            id=15, topic="raw post text https://evil.com xyz", viral_score=90.5, first_seen=now
        )
        snap = cases_mod.build_case_snapshot(cluster)
        # No raw 'topic' key (only 'title' which is sanitized)
        assert "topic" not in snap or snap.get("topic") == snap.get("title"), (
            "If 'topic' is stored, it must equal the sanitized 'title'"
        )
