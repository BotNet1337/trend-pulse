"""Value-validation harness — does the signal have PROVABLE value? (T8)

The product claim is "early + organic + relevant". This harness turns a labeled set of
live signals into the numbers that prove (or refute) it — the report the owner runs
after ~1 week of live data (product strategy: precision@k + lead-time are the sellable
metrics):

  • precision@k   — of the top-k signals by headline_score, what fraction were REAL
                    events (not noise/nothing). The core "is the ranking trustworthy".
  • median lead-time (minutes) — origin → mainstream, over REAL ORGANIC signals: "we
                    flagged it X minutes before it was everywhere".
  • kind split    — organic vs promo vs coordinated counts (how much noise the filter
                    is catching).
  • category breakdown — listing/hack/regulation/price_move/other counts.

Pure compute over `LabeledSignal`s; a `load_and_evaluate` helper reads a JSON fixture so
the owner can run it from a dump. No I/O in the metric functions (ADR-001).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from scorer.categorize import EventCategory
from scorer.noise_filter import SignalKind
from scorer.signal_payload import SignalPayload

# Default k cut-offs for precision@k (the operating points a desk cares about).
DEFAULT_KS: tuple[int, ...] = (5, 10, 20)
_SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True)
class LabeledSignal:
    """A live signal plus its ground-truth label for validation."""

    payload: SignalPayload
    was_real_event: bool  # a genuinely notable event (not noise / a non-event)
    mainstream_time: float | None  # epoch when it went mainstream; None if it never did


@dataclass(frozen=True)
class ValueReport:
    """The value metrics over a labeled signal set."""

    n: int
    precision_at_k: dict[int, float]
    median_lead_time_minutes: float | None
    kind_split: dict[str, int]
    category_breakdown: dict[str, int]


def precision_at_k(labeled: Sequence[LabeledSignal], k: int) -> float:
    """Fraction of the top-`k` signals (by headline_score, desc) that were real events.

    k is clamped to the number of signals; 0.0 for an empty set.
    """
    if not labeled or k < 1:
        return 0.0
    ranked = sorted(labeled, key=lambda s: s.payload.headline_score, reverse=True)
    top = ranked[:k]
    return sum(1 for s in top if s.was_real_event) / len(top)


def median_lead_time_minutes(labeled: Sequence[LabeledSignal]) -> float | None:
    """Median lead-time (minutes) origin → mainstream over REAL ORGANIC signals.

    Only real, organic signals that actually reached mainstream contribute. None if no
    such signal exists (cannot claim a lead-time yet).
    """
    leads = [
        (s.mainstream_time - s.payload.origin_at) / _SECONDS_PER_MINUTE
        for s in labeled
        if s.was_real_event
        and s.payload.signal_kind is SignalKind.ORGANIC
        and s.mainstream_time is not None
    ]
    return median(leads) if leads else None


def _count_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return counts


def evaluate(labeled: Sequence[LabeledSignal], ks: Sequence[int] = DEFAULT_KS) -> ValueReport:
    """Compute the full value report over `labeled`."""
    return ValueReport(
        n=len(labeled),
        precision_at_k={k: precision_at_k(labeled, k) for k in ks},
        median_lead_time_minutes=median_lead_time_minutes(labeled),
        kind_split=_count_by([s.payload.signal_kind.value for s in labeled]),
        category_breakdown=_count_by([s.payload.category.value for s in labeled]),
    )


def _payload_from_dict(d: dict[str, Any]) -> SignalPayload:
    return SignalPayload(
        headline_score=float(d["headline_score"]),
        signal_kind=SignalKind(d["signal_kind"]),
        category=EventCategory(d["category"]),
        origin_channel=int(d["origin_channel"]),
        origin_at=float(d["origin_at"]),
        total_channels=int(d["total_channels"]),
        independent_channels=float(d["independent_channels"]),
        lead_time_to_confirmation_seconds=(
            None
            if d.get("lead_time_to_confirmation_seconds") is None
            else float(d["lead_time_to_confirmation_seconds"])
        ),
        narrative=str(d.get("narrative", "")),
    )


def labeled_from_json(raw: str) -> list[LabeledSignal]:
    """Parse a JSON array of {payload fields..., was_real_event, mainstream_time}."""
    items: list[dict[str, Any]] = json.loads(raw)
    out: list[LabeledSignal] = []
    for item in items:
        mainstream = item.get("mainstream_time")
        out.append(
            LabeledSignal(
                payload=_payload_from_dict(item),
                was_real_event=bool(item["was_real_event"]),
                mainstream_time=None if mainstream is None else float(mainstream),
            )
        )
    return out


def load_and_evaluate(path: str | Path, ks: Sequence[int] = DEFAULT_KS) -> ValueReport:
    """Read a labeled-signals JSON fixture from `path` and return the value report."""
    return evaluate(labeled_from_json(Path(path).read_text()), ks)
