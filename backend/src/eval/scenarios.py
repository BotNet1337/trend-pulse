"""Labeled scenario sets for the score-meaningfulness eval (TASK-085).

Two sources of `(ScoreInputs, label)` pairs feed the ranking metrics in
`eval.metrics`:

1. `synthetic_scenarios()` -- hand-built, controlled cases ("breaking news across 15
   channels in 20 min" vs "single channel, normal engagement") each with an intended
   binary label (1 = viral, 0 = noise) and an ordinal severity (for Spearman). These
   prove discrimination *by construction* on cases where ground truth is unambiguous.

2. `load_real_judged(path)` -- a committed fixture of REAL prod clusters (read-only
   export, judged by a human from topic text + metrics). Each row carries the same
   aggregates the live scorer consumes plus the recorded label/ordinal, so the harness
   recomputes the *real* `viral_score` via `scorer.score.compute_components` and scores
   it against the human judgement -- reproducibly, from a committed file.

Neither source reimplements the formula: both build `ScoreInputs` and call the real
`compute_components`. The fixture's `watched_channels_count` column makes the
cross_channel assumption explicit and per-row rather than a global guess.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scorer.score import ScoreInputs


class ScenarioParseError(ValueError):
    """A judged-real fixture row could not be parsed into a typed scenario."""


@dataclass(frozen=True)
class LabeledScenario:
    """One labeled case: the scorer inputs + a human/intended judgement.

    `label` is the binary ground truth (1 = viral / worth an alert, 0 = noise).
    `ordinal` is a finer severity rank (higher = more clearly viral) used for the
    Spearman rank-correlation; `name` identifies the case in the report.
    """

    name: str
    inputs: ScoreInputs
    label: int
    ordinal: int


def synthetic_scenarios() -> list[LabeledScenario]:
    """Controlled viral/noise/borderline cases with unambiguous intended labels.

    Engagement is expressed against a fixed `channel_avg` baseline of 1000 weighted
    units so the cases are comparable; `watched_channels_count` is held at 20 (a
    plausible watchlist size) so cross_channel reflects breadth of spread. The cases
    span the spectrum from "breaking news everywhere, fast, high engagement" (clearly
    viral) down to "one quiet channel, below-average engagement" (clearly noise).
    """
    baseline = 1000.0
    watched = 20
    cases: list[tuple[str, ScoreInputs, int, int]] = [
        # --- clearly VIRAL (label 1) ---
        (
            "breaking_news_15ch_20min_high_engagement",
            ScoreInputs(
                views=80_000,
                forwards=4_000,
                reactions=6_000,
                channel_avg=baseline,
                delta_channel_count=15,
                delta_hours=20 / 60,
                unique_channels_count=15,
                watched_channels_count=watched,
            ),
            1,
            5,
        ),
        (
            "fast_spread_10ch_30min_strong_engagement",
            ScoreInputs(
                views=40_000,
                forwards=2_000,
                reactions=3_000,
                channel_avg=baseline,
                delta_channel_count=10,
                delta_hours=30 / 60,
                unique_channels_count=10,
                watched_channels_count=watched,
            ),
            1,
            4,
        ),
        (
            "moderate_spread_6ch_2h_aboveavg_engagement",
            ScoreInputs(
                views=12_000,
                forwards=400,
                reactions=600,
                channel_avg=baseline,
                delta_channel_count=6,
                delta_hours=2.0,
                unique_channels_count=6,
                watched_channels_count=watched,
            ),
            1,
            3,
        ),
        # --- BORDERLINE (label 0: not clearly worth an alert) ---
        (
            "borderline_3ch_6h_avg_engagement",
            ScoreInputs(
                views=3_000,
                forwards=80,
                reactions=120,
                channel_avg=baseline,
                delta_channel_count=3,
                delta_hours=6.0,
                unique_channels_count=3,
                watched_channels_count=watched,
            ),
            0,
            2,
        ),
        (
            "borderline_2ch_8h_slightly_belowavg",
            ScoreInputs(
                views=1_500,
                forwards=20,
                reactions=40,
                channel_avg=baseline,
                delta_channel_count=2,
                delta_hours=8.0,
                unique_channels_count=2,
                watched_channels_count=watched,
            ),
            0,
            1,
        ),
        # --- clearly NOISE (label 0) ---
        (
            "noise_single_channel_normal_engagement",
            ScoreInputs(
                views=900,
                forwards=10,
                reactions=20,
                channel_avg=baseline,
                delta_channel_count=1,
                delta_hours=12.0,
                unique_channels_count=1,
                watched_channels_count=watched,
            ),
            0,
            0,
        ),
        (
            "noise_single_channel_belowavg_slow",
            ScoreInputs(
                views=200,
                forwards=1,
                reactions=3,
                channel_avg=baseline,
                delta_channel_count=1,
                delta_hours=24.0,
                unique_channels_count=1,
                watched_channels_count=watched,
            ),
            0,
            0,
        ),
        (
            "noise_dead_post_no_engagement",
            ScoreInputs(
                views=10,
                forwards=0,
                reactions=0,
                channel_avg=baseline,
                delta_channel_count=1,
                delta_hours=24.0,
                unique_channels_count=1,
                watched_channels_count=watched,
            ),
            0,
            0,
        ),
    ]
    return [
        LabeledScenario(name=name, inputs=inputs, label=label, ordinal=ordinal)
        for name, inputs, label, ordinal in cases
    ]


_REQUIRED_COLUMNS = (
    "cluster_id",
    "topic",
    "views",
    "forwards",
    "reactions",
    "channel_avg",
    "delta_channel_count",
    "delta_hours",
    "unique_channels_count",
    "watched_channels_count",
    "label",
    "ordinal",
)


def _int(row: dict[str, str], key: str, *, row_num: int) -> int:
    try:
        return int(row[key])
    except (KeyError, ValueError) as exc:
        raise ScenarioParseError(f"row {row_num}: bad int in {key!r}: {row.get(key)!r}") from exc


def _float(row: dict[str, str], key: str, *, row_num: int) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError) as exc:
        raise ScenarioParseError(f"row {row_num}: bad float in {key!r}: {row.get(key)!r}") from exc


def load_real_judged(path: Path) -> list[LabeledScenario]:
    """Load the committed judged-real fixture into `LabeledScenario`s (header required).

    The fixture is produced read-only from prod (see `scripts/export_real_judged.sh`),
    one row per scoreable cluster, with the score inputs PLUS a human `label` (1/0) and
    `ordinal` severity judged from the `topic` text and metrics. Validates types at the
    boundary (`ScenarioParseError` with the 1-based row number) -- never trusts the CSV.

    PROXY CAVEAT (mirrors `eval.scoring_replay`): the fixture's `channel_avg` is the
    cold-channel fallback ``views / posts_in_window`` (raw-views per-post average), NOT
    the live scorer's historical 7-day WEIGHTED per-channel baseline -- that value is
    not reconstructable from a static export. `watched_channels_count` is an ASSUMPTION
    (no live watchlists in the corpus). So the replayed `viral_score` here is the
    cold-channel value the live scorer uses for cold channels, which is honest for a
    0-alert corpus but is not necessarily the exact score computed at alert time.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ScenarioParseError(f"fixture missing columns: {missing}")
        scenarios: list[LabeledScenario] = []
        for n, row in enumerate(reader, start=1):
            label = _int(row, "label", row_num=n)
            if label not in (0, 1):
                raise ScenarioParseError(f"row {n}: label must be 0 or 1, got {label}")
            inputs = ScoreInputs(
                views=_int(row, "views", row_num=n),
                forwards=_int(row, "forwards", row_num=n),
                reactions=_int(row, "reactions", row_num=n),
                channel_avg=_float(row, "channel_avg", row_num=n),
                delta_channel_count=_int(row, "delta_channel_count", row_num=n),
                delta_hours=_float(row, "delta_hours", row_num=n),
                unique_channels_count=_int(row, "unique_channels_count", row_num=n),
                watched_channels_count=_int(row, "watched_channels_count", row_num=n),
            )
            scenarios.append(
                LabeledScenario(
                    name=f"cluster_{row['cluster_id']}",
                    inputs=inputs,
                    label=label,
                    ordinal=_int(row, "ordinal", row_num=n),
                )
            )
    if not scenarios:
        raise ScenarioParseError("judged-real fixture has no rows")
    return scenarios


def score_scenarios(scenarios: Sequence[LabeledScenario]) -> list[float]:
    """Compute the REAL `viral_score` for each scenario (reuses `scorer.score`)."""
    from scorer.score import compute_viral_score

    return [compute_viral_score(s.inputs) for s in scenarios]
