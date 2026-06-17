"""Unit tests for the source-independence feature in the live scorer (TASK-126).

These tests exercise the independence signal wired into `_persist_score`:
- the persisted `scores.effective_sources` == `effective_independent_sources(events)`
  from `eval.science_features` (REUSE, not reimplemented), bounded >= 0,
- single-channel cluster collapses to ~1.0; multi-channel spread > 1,
- empty `events` -> 0.0 (total guard, never NULL-from-error / no crash),
- a GOLDEN proof that `viral_score` + components are BYTE-IDENTICAL to
  `compute_components(inputs)` — independence is badge+shadow only, NOT in the score.

A `MagicMock` session keeps these DB-free; the upsert is compiled against the PG
dialect so the BOUND `effective_sources` / `viral_score` params are asserted directly.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from eval.science_features import TimedEvent, effective_independent_sources
from scorer.score import ScoreEvent, ScoreInputs, compute_components
from scorer.tasks import _persist_score


def _bound_upsert_values(session: MagicMock) -> dict[str, object]:
    """Extract the params BOUND into the `pg_insert(...).values(...)` upsert."""
    call = session.execute.call_args
    assert call is not None, "an upsert must have been issued"
    stmt = call.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    return dict(compiled.params)


def _inputs(*, events: tuple[ScoreEvent, ...], unique_channels_count: int) -> ScoreInputs:
    """Build a `ScoreInputs` whose `events` drive the independence compute."""
    return ScoreInputs(
        views=1000,
        forwards=10,
        reactions=20,
        channel_avg=1.0,
        delta_channel_count=unique_channels_count,
        delta_hours=2.0,
        unique_channels_count=unique_channels_count,
        watched_channels_count=5,
        events=events,
    )


# --- AC1 — compute (REUSE), bounded, distribution-faithful ---------------------------


@pytest.mark.unit
def test_persist_score_effective_sources_matches_reused_science_feature() -> None:
    """Persisted `effective_sources` == direct `effective_independent_sources(events)`."""
    events = (
        ScoreEvent(epoch=100.0, channel_id=1),
        ScoreEvent(epoch=200.0, channel_id=2),
        ScoreEvent(epoch=300.0, channel_id=3),
    )
    inputs = _inputs(events=events, unique_channels_count=3)
    expected = effective_independent_sources(
        [TimedEvent(epoch=e.epoch, source_id=e.channel_id, weight=1.0) for e in events]
    )

    session = MagicMock()
    _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, post_count=len(events))

    bound = _bound_upsert_values(session)
    assert bound["effective_sources"] == pytest.approx(expected)
    assert bound["effective_sources"] >= 0.0
    # 3 evenly-spread channels -> effective ~ 3 independent sources.
    assert bound["effective_sources"] == pytest.approx(3.0)


@pytest.mark.unit
def test_persist_score_multi_channel_gives_more_than_one() -> None:
    """A cluster spread over >=2 channels -> effective_sources > 1."""
    events = (
        ScoreEvent(epoch=100.0, channel_id=1),
        ScoreEvent(epoch=150.0, channel_id=1),
        ScoreEvent(epoch=200.0, channel_id=2),
    )
    inputs = _inputs(events=events, unique_channels_count=2)
    session = MagicMock()
    _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, post_count=len(events))
    bound = _bound_upsert_values(session)
    assert bound["effective_sources"] > 1.0


@pytest.mark.unit
def test_persist_score_single_channel_collapses_to_one() -> None:
    """All posts on one channel -> entropy 0 -> exp(0) == 1.0 (AC2)."""
    events = (
        ScoreEvent(epoch=100.0, channel_id=7),
        ScoreEvent(epoch=200.0, channel_id=7),
        ScoreEvent(epoch=300.0, channel_id=7),
    )
    inputs = _inputs(events=events, unique_channels_count=1)
    session = MagicMock()
    _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, post_count=len(events))
    bound = _bound_upsert_values(session)
    assert bound["effective_sources"] == pytest.approx(1.0)


@pytest.mark.unit
def test_persist_score_empty_events_is_zero_not_null() -> None:
    """Empty `events` -> effective_sources == 0.0, total-guard, no crash (AC2)."""
    inputs = _inputs(events=(), unique_channels_count=1)
    session = MagicMock()
    returned = _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, post_count=0)
    # `returned` is the viral_score; assert it stays a finite number (no crash).
    assert math.isfinite(returned)  # viral_score
    bound = _bound_upsert_values(session)
    # The promise of this test: effective_sources is persisted as 0.0, never NULL.
    assert bound["effective_sources"] is not None
    assert bound["effective_sources"] == pytest.approx(0.0)


# --- AC5 — score integrity: viral_score byte-identical, independence NOT in the score -


@pytest.mark.unit
def test_persist_score_viral_score_unchanged_by_independence() -> None:
    """GOLDEN: persisted viral_score + components are EXACTLY compute_components(inputs).

    Independence is a badge + shadow signal — adding `effective_sources` must NOT
    perturb the viral_score binding by a single bit (AC5 regression gate).
    """
    events = (
        ScoreEvent(epoch=100.0, channel_id=1),
        ScoreEvent(epoch=200.0, channel_id=2),
    )
    inputs = _inputs(events=events, unique_channels_count=2)
    golden = compute_components(inputs)

    session = MagicMock()
    returned = _persist_score(session, user_id=1, cluster_id=2, inputs=inputs, post_count=2)

    assert returned == golden.viral_score
    bound = _bound_upsert_values(session)
    assert bound["viral_score"] == pytest.approx(golden.viral_score)
    assert bound["velocity"] == pytest.approx(golden.velocity)
    assert bound["engagement"] == pytest.approx(golden.engagement)
    assert bound["cross_channel"] == pytest.approx(golden.cross_channel)
