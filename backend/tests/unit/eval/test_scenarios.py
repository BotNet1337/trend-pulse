"""Unit tests for eval.scenarios: synthetic discrimination + judged-real loader (TASK-085)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.metrics import roc_auc, separation
from eval.scenarios import (
    ScenarioParseError,
    load_real_judged,
    score_scenarios,
    synthetic_scenarios,
)

_FIXTURE = Path(__file__).resolve().parents[3] / "data" / "eval" / "real_judged.sample.csv"


@pytest.mark.unit
def test_synthetic_set_has_both_classes() -> None:
    scen = synthetic_scenarios()
    labels = [s.label for s in scen]
    assert 1 in labels and 0 in labels


@pytest.mark.unit
def test_synthetic_scores_separate_viral_from_noise() -> None:
    """The CORE proof: on controlled cases the score puts viral well above noise."""
    scen = synthetic_scenarios()
    scores = score_scenarios(scen)
    labels = [s.label for s in scen]
    sep = separation(scores, labels)
    # clear margin: every viral case scores far above the noise cases
    assert sep.mean_margin > 5.0
    assert sep.viral_mean > sep.noise_mean


@pytest.mark.unit
def test_synthetic_auc_is_perfect() -> None:
    scen = synthetic_scenarios()
    scores = score_scenarios(scen)
    labels = [s.label for s in scen]
    assert roc_auc(scores, labels) == pytest.approx(1.0)


@pytest.mark.unit
def test_synthetic_viral_outranks_every_noise_case() -> None:
    scen = synthetic_scenarios()
    scores = score_scenarios(scen)
    viral = [sc for sc, s in zip(scores, scen, strict=True) if s.label == 1]
    noise = [sc for sc, s in zip(scores, scen, strict=True) if s.label == 0]
    assert min(viral) > max(noise)


@pytest.mark.unit
def test_real_fixture_loads_and_scores() -> None:
    scen = load_real_judged(_FIXTURE)
    assert len(scen) >= 1
    scores = score_scenarios(scen)
    assert len(scores) == len(scen)
    # both classes present in the committed judged set
    labels = [s.label for s in scen]
    assert 1 in labels and 0 in labels


@pytest.mark.unit
def test_real_fixture_labels_are_binary() -> None:
    for s in load_real_judged(_FIXTURE):
        assert s.label in (0, 1)


@pytest.mark.unit
def test_loader_rejects_missing_columns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("cluster_id,topic\n1,foo\n", encoding="utf-8")
    with pytest.raises(ScenarioParseError):
        load_real_judged(bad)


@pytest.mark.unit
def test_loader_rejects_bad_label(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    header = (
        "cluster_id,topic,views,forwards,reactions,channel_avg,delta_channel_count,"
        "delta_hours,unique_channels_count,watched_channels_count,label,ordinal\n"
    )
    bad.write_text(header + "1,foo,100,1,1,100,1,0,1,10,5,3\n", encoding="utf-8")
    with pytest.raises(ScenarioParseError):
        load_real_judged(bad)


@pytest.mark.unit
def test_loader_rejects_empty_fixture(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    header = (
        "cluster_id,topic,views,forwards,reactions,channel_avg,delta_channel_count,"
        "delta_hours,unique_channels_count,watched_channels_count,label,ordinal\n"
    )
    empty.write_text(header, encoding="utf-8")
    with pytest.raises(ScenarioParseError):
        load_real_judged(empty)
