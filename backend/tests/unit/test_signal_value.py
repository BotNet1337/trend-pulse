"""Unit tests for the value-validation harness (T8)."""

import json

import pytest

from eval.signal_value import (
    LabeledSignal,
    evaluate,
    labeled_from_json,
    load_and_evaluate,
    median_lead_time_minutes,
    precision_at_k,
)
from scorer.categorize import EventCategory
from scorer.noise_filter import SignalKind
from scorer.signal_payload import SignalPayload

_T0 = 1_700_000_000.0


def _sig(
    score: float,
    *,
    real: bool,
    kind: SignalKind = SignalKind.ORGANIC,
    category: EventCategory = EventCategory.PRICE_MOVE,
    mainstream_after_min: float | None = None,
) -> LabeledSignal:
    mainstream = None if mainstream_after_min is None else _T0 + mainstream_after_min * 60.0
    return LabeledSignal(
        payload=SignalPayload(
            headline_score=score,
            signal_kind=kind,
            category=category,
            origin_channel=1,
            origin_at=_T0,
            total_channels=4,
            independent_channels=4.0,
            lead_time_to_confirmation_seconds=600.0,
            narrative="n",
        ),
        was_real_event=real,
        mainstream_time=mainstream,
    )


@pytest.mark.unit
def test_precision_at_k_ranks_by_score() -> None:
    # Top-2 by score are both real → precision@2 = 1.0; the low-score noise is real=False.
    signals = [
        _sig(90, real=True),
        _sig(80, real=True),
        _sig(10, real=False),
        _sig(5, real=False),
    ]
    assert precision_at_k(signals, 2) == pytest.approx(1.0)
    assert precision_at_k(signals, 4) == pytest.approx(0.5)


@pytest.mark.unit
def test_precision_at_k_clamps_and_guards() -> None:
    assert precision_at_k([_sig(50, real=True)], 10) == pytest.approx(1.0)
    assert precision_at_k([], 5) == 0.0
    assert precision_at_k([_sig(50, real=True)], 0) == 0.0


@pytest.mark.unit
def test_median_lead_time_over_real_organic() -> None:
    signals = [
        _sig(90, real=True, mainstream_after_min=120),  # 120 min lead
        _sig(80, real=True, mainstream_after_min=60),  # 60 min lead
        _sig(70, real=True, mainstream_after_min=180),  # 180 min lead → median 120
        _sig(10, real=False, mainstream_after_min=5),  # not real → excluded
        _sig(95, real=True, kind=SignalKind.PROMO, mainstream_after_min=1),  # promo → excluded
        _sig(85, real=True, mainstream_after_min=None),  # never mainstream → excluded
    ]
    assert median_lead_time_minutes(signals) == pytest.approx(120.0)


@pytest.mark.unit
def test_median_lead_time_none_when_no_real_organic() -> None:
    assert median_lead_time_minutes([_sig(50, real=False, mainstream_after_min=10)]) is None


@pytest.mark.unit
def test_evaluate_full_report() -> None:
    signals = [
        _sig(90, real=True, category=EventCategory.HACK, mainstream_after_min=30),
        _sig(80, real=True, category=EventCategory.LISTING, mainstream_after_min=90),
        _sig(40, real=False, kind=SignalKind.PROMO),
        _sig(20, real=False, kind=SignalKind.COORDINATED),
    ]
    report = evaluate(signals, ks=(2, 4))
    assert report.n == 4
    assert report.precision_at_k[2] == pytest.approx(1.0)
    assert report.precision_at_k[4] == pytest.approx(0.5)
    assert report.median_lead_time_minutes == pytest.approx(60.0)
    assert report.kind_split == {"organic": 2, "promo": 1, "coordinated": 1}
    assert report.category_breakdown["hack"] == 1
    assert report.category_breakdown["listing"] == 1


@pytest.mark.unit
def test_load_from_json_roundtrip(tmp_path: object) -> None:
    items = [
        {
            "headline_score": 88.0,
            "signal_kind": "organic",
            "category": "regulation",
            "origin_channel": 5,
            "origin_at": _T0,
            "total_channels": 6,
            "independent_channels": 4.0,
            "lead_time_to_confirmation_seconds": 1800.0,
            "narrative": "x",
            "was_real_event": True,
            "mainstream_time": _T0 + 3600,
        }
    ]
    labeled = labeled_from_json(json.dumps(items))
    assert labeled[0].payload.headline_score == 88.0
    assert labeled[0].payload.signal_kind is SignalKind.ORGANIC
    assert labeled[0].mainstream_time == _T0 + 3600

    from pathlib import Path

    p = Path(str(tmp_path)) / "signals.json"
    p.write_text(json.dumps(items))
    report = load_and_evaluate(p, ks=(1,))
    assert report.n == 1
    assert report.median_lead_time_minutes == pytest.approx(60.0)
