"""Score-meaningfulness eval CLI -- proves viral_score discriminates (TASK-085).

Answers the owner's question with concrete numbers: does a HIGH score mean
"spreading / worth an alert" and a LOW score mean "noise"? It does NOT reimplement
the formula -- it scores labeled scenarios via the real `scorer.score` and feeds
`(score, label)` pairs through the pure metrics in `eval.metrics`.

Three layers (increasing rigor):

  1. SYNTHETIC discrimination -- controlled viral/noise/borderline cases with
     unambiguous intended labels; reports separation, AUC, precision@k, Spearman.
  2. REAL judged set -- a committed fixture of read-only prod clusters labeled by a
     human from topic text + metrics; same metrics on REAL `viral_score`s.
  3. THRESHOLD calibration -- confusion (TP/FP/TN/FN, precision/recall) at a sweep of
     thresholds, on both sets, to locate where the alert bar should sit.

Usage (from backend/, via uv):
    uv run python scripts/meaningfulness_eval.py \
        --real-judged data/eval/real_judged.sample.csv
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# Allow running as `python scripts/meaningfulness_eval.py` from backend/ (src layout).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.metrics import (
    confusion_at_threshold,
    precision_at_k,
    roc_auc,
    separation,
    spearman_rho,
)
from eval.scenarios import (
    LabeledScenario,
    load_real_judged,
    score_scenarios,
    synthetic_scenarios,
)
from scorer.score import MIN_WINDOW_HOURS

# Thresholds to sweep for calibration. The watchlist default is 0.0 (alert on every
# scored cluster -- storage.models.watchlists._DEFAULT_THRESHOLD); packs ship 70;
# showcase uses 85 (post) / 90 (case). We sweep across that operational range.
_THRESHOLD_SWEEP = (0.0, 1.0, 5.0, 10.0, 50.0, 70.0, 85.0, 90.0)
# precision@k values to report (clamped to set size inside the metric).
_PRECISION_KS = (1, 3, 5)


def _report_set(name: str, scenarios: Sequence[LabeledScenario]) -> None:
    """Print separation + AUC + precision@k + Spearman for one labeled set."""
    scores = score_scenarios(scenarios)
    labels = [s.label for s in scenarios]
    ordinals = [s.ordinal for s in scenarios]
    print(f"\n===== {name} (n={len(scenarios)}) =====")
    for sc, score in sorted(zip(scenarios, scores, strict=True), key=lambda t: -t[1]):
        print(f"  score={score:9.4f} label={sc.label} ord={sc.ordinal} {sc.name}")

    sep = separation(scores, labels)
    print(
        f"\nseparation: viral n={sep.viral_count} mean={sep.viral_mean:.4f} "
        f"median={sep.viral_median:.4f} | noise n={sep.noise_count} "
        f"mean={sep.noise_mean:.4f} median={sep.noise_median:.4f}"
    )
    print(f"  mean_margin={sep.mean_margin:.4f} median_margin={sep.median_margin:.4f}")

    print(f"ROC-AUC(score vs binary label) = {roc_auc(scores, labels):.4f}")
    for k in _PRECISION_KS:
        print(f"precision@{k} = {precision_at_k(scores, labels, k):.4f}")
    print(f"Spearman(score vs ordinal judgement) = {spearman_rho(scores, ordinals):.4f}")
    _warn_velocity_clamp(scenarios)


def _warn_velocity_clamp(scenarios: Sequence[LabeledScenario]) -> None:
    """Flag when most items hit the velocity Δhours clamp (a known discrimination killer).

    On the backfill-shaped prod corpus almost every scoreable cluster is a single post
    with `delta_hours == 0` -> velocity is clamped to `log1p(Δch)/MIN_WINDOW_HOURS`, so
    the scores pile up at a single value and AUC/Spearman collapse toward chance. This
    warning makes that artifact VISIBLE next to the metrics so the AUC is never read
    naked as "the scorer can't discriminate".
    """
    at_clamp = sum(1 for s in scenarios if s.inputs.delta_hours < MIN_WINDOW_HOURS)
    if at_clamp:
        pct = at_clamp / len(scenarios) * 100.0
        print(
            f"  [!] {at_clamp}/{len(scenarios)} ({pct:.0f}%) items have delta_hours below "
            f"MIN_WINDOW_HOURS ({MIN_WINDOW_HOURS:.4f}h) -> velocity is CLAMPED for them; "
            "scores collapse toward a single value and AUC/Spearman understate the "
            "formula (see report 'Why real != synthetic')."
        )


def _report_thresholds(name: str, scenarios: Sequence[LabeledScenario]) -> None:
    """Print the confusion sweep for one labeled set."""
    scores = score_scenarios(scenarios)
    labels = [s.label for s in scenarios]
    print(f"\n----- threshold calibration: {name} -----")
    print("  thr      TP  FP  TN  FN  precision  recall  alerts")
    for thr in _THRESHOLD_SWEEP:
        c = confusion_at_threshold(scores, labels, thr)
        print(
            f"  {thr:6.1f}  {c.true_positive:3d} {c.false_positive:3d} "
            f"{c.true_negative:3d} {c.false_negative:3d}  "
            f"{c.precision:8.3f}  {c.recall:6.3f}  {c.alerts:5d}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score-meaningfulness eval (TASK-085)")
    parser.add_argument(
        "--real-judged",
        type=Path,
        default=None,
        help="committed judged-real fixture CSV (omit to run synthetic only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    synthetic = synthetic_scenarios()
    _report_set("SYNTHETIC controlled scenarios", synthetic)
    _report_thresholds("SYNTHETIC", synthetic)

    if args.real_judged is not None:
        real = load_real_judged(args.real_judged)
        _report_set("REAL judged prod clusters", real)
        _report_thresholds("REAL", real)
    else:
        print("\n(no --real-judged fixture given; ran synthetic layer only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
