"""Unit tests for public_datasets — Higgs → B2 schema mapping (TASK-111, B3).

Run from eval_offline with the backend venv on the path:
    ../backend/.venv/bin/python -m pytest test_public_datasets.py -q
Hand-computed cases so the cascade grouping + early-window features are reproducible.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from public_datasets import (
    CascadeEvent,
    HiggsInteraction,
    PublicDatasetError,
    bootstrap_status,
    group_cascades,
    map_cascade,
    map_higgs_to_b2,
    parse_higgs_line,
)


def test_parse_higgs_line_ok() -> None:
    e = parse_higgs_line("100 200 1341100972 RT", line_num=1)
    assert e.source_id == 100
    assert e.target_id == 200
    assert e.epoch == 1341100972
    assert e.interaction is HiggsInteraction.RETWEET


def test_parse_rejects_bad_field_count() -> None:
    with pytest.raises(PublicDatasetError):
        parse_higgs_line("100 200 1341100972", line_num=1)


def test_parse_rejects_unknown_interaction() -> None:
    with pytest.raises(PublicDatasetError):
        parse_higgs_line("100 200 1341100972 XX", line_num=1)


def test_parse_rejects_nonint() -> None:
    with pytest.raises(PublicDatasetError):
        parse_higgs_line("a 200 1341100972 RT", line_num=1)


def test_event_rejects_negative_epoch() -> None:
    with pytest.raises(PublicDatasetError):
        CascadeEvent(source_id=1, target_id=2, epoch=-1, interaction=HiggsInteraction.MENTION)


def test_group_cascades_by_target_sorted() -> None:
    events = [
        CascadeEvent(1, 99, 30, HiggsInteraction.RETWEET),
        CascadeEvent(2, 99, 10, HiggsInteraction.REPLY),
        CascadeEvent(3, 88, 20, HiggsInteraction.MENTION),
    ]
    grouped = group_cascades(events)
    assert [e.epoch for e in grouped[99]] == [10, 30]  # sorted ascending by epoch
    assert len(grouped[88]) == 1


def test_map_cascade_early_window_and_outcome() -> None:
    # target 99: 3 RTs (weight 3 each) at t0, t0+60, t0+10000 (10000s > 1h window).
    t0 = 1000
    events = [
        CascadeEvent(1, 99, t0, HiggsInteraction.RETWEET),
        CascadeEvent(2, 99, t0 + 60, HiggsInteraction.RETWEET),
        CascadeEvent(3, 99, t0 + 10000, HiggsInteraction.RETWEET),
    ]
    mapped = map_cascade(99, events, obs_seconds=3600)
    assert mapped is not None
    # early = first two (within 1h); distinct sources = 2; early eng = 3+3 = 6
    assert mapped.features.e_ch == 2.0
    assert mapped.features.e_posts == 2.0
    assert mapped.features.e_eng_log == pytest.approx(math.log1p(6.0))
    # outcome = full cascade weighted engagement = 3+3+3 = 9
    assert mapped.outcome.final_outcome == pytest.approx(9.0)
    assert mapped.outcome.age_at_outcome_seconds == 10000


def test_map_cascade_empty_is_none() -> None:
    assert map_cascade(1, [], obs_seconds=3600) is None


def test_map_higgs_filters_min_size() -> None:
    events = [
        CascadeEvent(1, 99, 0, HiggsInteraction.RETWEET),
        CascadeEvent(2, 99, 10, HiggsInteraction.RETWEET),
        CascadeEvent(3, 88, 0, HiggsInteraction.RETWEET),  # singleton cascade → dropped
    ]
    mapped = map_higgs_to_b2(events, obs_seconds=3600, min_cascade_size=2)
    assert len(mapped) == 1
    assert mapped[0].outcome.final_outcome == pytest.approx(6.0)


def test_map_higgs_rejects_bad_min_size() -> None:
    with pytest.raises(PublicDatasetError):
        map_higgs_to_b2([], obs_seconds=3600, min_cascade_size=0)


def test_bootstrap_status_reports_higgs_available() -> None:
    statuses = {s.name: s for s in bootstrap_status()}
    assert statuses["Higgs Twitter"].available is True
    assert statuses["Weibo / DeepHawkes"].available is False
