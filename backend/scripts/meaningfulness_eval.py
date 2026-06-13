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
    """Flag the residual single-channel coverage limit on the backfill-shaped corpus.

    BEFORE T15 the velocity term was `log1p(Δch)/Δhours`: on this corpus almost every
    cluster is a single post with `delta_hours → 0`, so velocity clamped to
    `log1p(1)/MIN_WINDOW_HOURS ≈ 41.6` and the scores PILED UP at one value -> AUC/
    Spearman collapsed toward chance (real ROC-AUC ≈ 0.564). That was a formula defect,
    not a corpus artifact, and T15 fixed it: velocity is now `log1p(Δch - 1)/Δhours`, so
    a single-channel cluster scores velocity 0 and the Δhours clamp can no longer
    manufacture a spurious value.

    The RESIDUAL limit is the corpus itself: most judged clusters are single-channel, so
    velocity contributes 0 for them and the ranking among them rests on engagement /
    cross_channel alone. This warning surfaces how many items get no velocity signal so
    the AUC is read with that coverage caveat — not as "the formula can't discriminate".
    """
    single_channel = sum(1 for s in scenarios if s.inputs.delta_channel_count <= 1)
    if single_channel:
        pct = single_channel / len(scenarios) * 100.0
        print(
            f"  [!] {single_channel}/{len(scenarios)} ({pct:.0f}%) items are single-channel "
            "(Δchannel_count ≤ 1) -> velocity 0 by design (no cross-channel spread, T15); "
            "their ranking rests on engagement/cross_channel alone, so AUC reflects the "
            "corpus's single-channel coverage, not a formula defect (see report "
            "'T15 velocity fix')."
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
