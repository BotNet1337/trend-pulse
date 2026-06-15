"""Unit tests for the C1 GBDT virality model interface + formula fallback (TASK-112).

A fake booster keeps these tests free of the optional `lightgbm` dependency, so CI
exercises the typed interface, the min-signal fallback policy, and the artifact
validation without the heavy lib.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from scorer.viral_model import (
    FEATURE_ORDER,
    EarlyFeatures,
    FormulaFallbackModel,
    GbdtViralModel,
    ModelChoice,
    ViralModel,
    ViralModelError,
    select_prediction,
)


def _feats(
    e_ch: float = 3.0, e_posts: float = 5.0, e_eng_log: float = 8.0, e_burst: float = 1.0
) -> EarlyFeatures:
    return EarlyFeatures(e_ch=e_ch, e_posts=e_posts, e_eng_log=e_eng_log, e_burst=e_burst)


@dataclass(frozen=True)
class _FakeBooster:
    """Returns a fixed probability, recording the row it was fed (order assertion)."""

    fixed: float

    def predict(self, data: list[list[float]]) -> list[float]:
        return [self.fixed for _ in data]


# --- EarlyFeatures validation --------------------------------------------------------


@pytest.mark.unit
def test_early_features_rejects_negative() -> None:
    with pytest.raises(ViralModelError):
        _feats(e_ch=-1.0)


@pytest.mark.unit
def test_early_features_vector_matches_feature_order() -> None:
    vec = _feats(e_ch=1.0, e_posts=2.0, e_eng_log=3.0, e_burst=4.0).as_vector()
    assert vec == [1.0, 2.0, 3.0, 4.0]
    assert len(vec) == len(FEATURE_ORDER)


@pytest.mark.unit
def test_min_signal_floor() -> None:
    assert _feats(e_ch=2.0, e_posts=2.0).has_minimum_signal() is True
    assert _feats(e_ch=1.0, e_posts=5.0).has_minimum_signal() is False  # single channel
    assert _feats(e_ch=3.0, e_posts=1.0).has_minimum_signal() is False  # one post


# --- FormulaFallbackModel ------------------------------------------------------------


@pytest.mark.unit
def test_fallback_returns_unit_interval() -> None:
    model = FormulaFallbackModel(watched_channels_count=10)
    p = model.predict_proba(_feats())
    assert 0.0 <= p <= 1.0


@pytest.mark.unit
def test_fallback_monotone_in_engagement() -> None:
    model = FormulaFallbackModel(watched_channels_count=10)
    low = model.predict_proba(_feats(e_eng_log=2.0))
    high = model.predict_proba(_feats(e_eng_log=12.0))
    assert high >= low


@pytest.mark.unit
def test_fallback_rejects_bad_watched() -> None:
    with pytest.raises(ViralModelError):
        FormulaFallbackModel(watched_channels_count=0)


@pytest.mark.unit
def test_fallback_is_a_viral_model() -> None:
    assert isinstance(FormulaFallbackModel(), ViralModel)


# --- GbdtViralModel ------------------------------------------------------------------


@pytest.mark.unit
def test_gbdt_predict_clamps_to_unit_interval() -> None:
    model = GbdtViralModel(booster=_FakeBooster(fixed=1.7), feature_order=FEATURE_ORDER)
    assert model.predict_proba(_feats()) == pytest.approx(1.0)
    model_lo = GbdtViralModel(booster=_FakeBooster(fixed=-0.3), feature_order=FEATURE_ORDER)
    assert model_lo.predict_proba(_feats()) == pytest.approx(0.0)


@pytest.mark.unit
def test_gbdt_rejects_wrong_feature_order() -> None:
    model = GbdtViralModel(booster=_FakeBooster(fixed=0.5), feature_order=("e_ch", "e_posts"))
    with pytest.raises(ViralModelError):
        model.predict_proba(_feats())


@pytest.mark.unit
def test_gbdt_load_missing_artifact_raises(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    with pytest.raises(ViralModelError):
        GbdtViralModel.load(tmp_path / "nope.txt", feature_order=FEATURE_ORDER)


# --- select_prediction policy --------------------------------------------------------


@pytest.mark.unit
def test_select_uses_gbdt_above_floor() -> None:
    gbdt = GbdtViralModel(booster=_FakeBooster(fixed=0.9), feature_order=FEATURE_ORDER)
    result = select_prediction(
        _feats(e_ch=3.0, e_posts=5.0), gbdt=gbdt, fallback=FormulaFallbackModel()
    )
    assert result.chosen is ModelChoice.GBDT
    assert result.probability == pytest.approx(0.9)


@pytest.mark.unit
def test_select_falls_back_below_floor() -> None:
    gbdt = GbdtViralModel(booster=_FakeBooster(fixed=0.9), feature_order=FEATURE_ORDER)
    result = select_prediction(
        _feats(e_ch=1.0, e_posts=1.0), gbdt=gbdt, fallback=FormulaFallbackModel()
    )
    assert result.chosen is ModelChoice.FALLBACK


@pytest.mark.unit
def test_select_falls_back_when_no_gbdt() -> None:
    result = select_prediction(_feats(), gbdt=None, fallback=FormulaFallbackModel())
    assert result.chosen is ModelChoice.FALLBACK
    assert 0.0 <= result.probability <= 1.0
