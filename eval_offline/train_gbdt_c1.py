"""C1 — train the LightGBM virality GBDT (offline), report PR-AUC + calibration.

TASK-112 (Track B→C / C1). Trains the GBDT the production scorer loads via
`scorer.viral_model.GbdtViralModel`, on the B0-gated / B1-schema early-window features
with the B2 forward-time-split doubling label. The prod B1 `cluster_feature_snapshots`
table is still filling and the gated TG corpus is thin (B0: ~315-964 stories), so the
TRAINING VOLUME comes from the B3 Higgs cascades (36k) — the harness proves the
methodology and produces a real, loadable artifact.

Reports, on the chronological TEST split (no leakage):
  - PR-AUC + ROC-AUC of the GBDT vs each observation window (the early-signal curve)
  - the v2 FORMULA fallback PR-AUC on the same split (the baseline it must beat)
  - CALIBRATION: Brier score + a reliability table (predicted-prob bucket vs observed
    positive rate) — the honest test of "is the probability meaningful", recalling the
    <50% variance ceiling (aim for a calibrated probability, not an inflated AUC).

The saved model is LightGBM's native TEXT dump (no pickle) so the artifact is
reviewable and `GbdtViralModel.load` needs no unpickling.

USAGE:
  uv run python train_gbdt_c1.py --higgs data/higgs-activity_time.txt \
      --obs 3600 --out models/viral_gbdt_higgs_1h.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from eval.forward_split import (  # noqa: E402
    CohortPolicy,
    LabelKind,
    SplitRatios,
    label_partitions,
    split_by_time,
)
from eval.metrics import average_precision, roc_auc  # noqa: E402

# scorer/__init__ is lazy (PEP 562) so this stays config-free (no DB/secrets needed).
from scorer.viral_model import (  # noqa: E402
    FEATURE_ORDER,
    EarlyFeatures,
    FormulaFallbackModel,
)

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from public_datasets import MappedCascade, load_higgs, map_higgs_to_b2  # noqa: E402


def _early_features(cascade: MappedCascade) -> EarlyFeatures:
    f = cascade.features
    return EarlyFeatures(e_ch=f.e_ch, e_posts=f.e_posts, e_eng_log=f.e_eng_log, e_burst=f.e_burst)


def _brier(probs: list[float], labels: list[int]) -> float:
    """Mean squared error of probability vs outcome — the calibration loss (lower=better)."""
    if not probs:
        raise ValueError("Brier score needs at least one (prob, label) pair")
    return sum((p - y) ** 2 for p, y in zip(probs, labels, strict=True)) / len(probs)


def _reliability_table(probs: list[float], labels: list[int], bins: int = 5) -> list[str]:
    """Predicted-prob bucket vs observed positive rate (the reliability diagram, text)."""
    buckets: list[list[int]] = [[] for _ in range(bins)]
    for p, y in zip(probs, labels, strict=True):
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append(y)
    rows: list[str] = []
    for i, bucket in enumerate(buckets):
        lo, hi = i / bins, (i + 1) / bins
        if bucket:
            observed = sum(bucket) / len(bucket)
            rows.append(
                f"    [{lo:.1f},{hi:.1f})  n={len(bucket):5d}  observed_pos_rate={observed:.3f}"
            )
        else:
            rows.append(f"    [{lo:.1f},{hi:.1f})  n=    0  (empty)")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--higgs", type=Path, default=Path("data/higgs-activity_time.txt"))
    ap.add_argument("--obs", type=int, default=3600, help="observation window seconds")
    ap.add_argument("--gap-hours", type=float, default=6.0)
    ap.add_argument("--cohort-hours", type=float, default=1.0)
    ap.add_argument("--min-cascade", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None, help="save the LightGBM text model here")
    a = ap.parse_args()

    if not a.higgs.exists():
        print(f"Higgs file not found: {a.higgs}")
        return 1
    try:
        import lightgbm as lgb
    except ImportError:
        print("lightgbm not installed: uv pip install lightgbm")
        return 1

    events = load_higgs(a.higgs)
    cascades = map_higgs_to_b2(events, obs_seconds=a.obs, min_cascade_size=a.min_cascade)
    by_id = {c.outcome.cluster_id: c for c in cascades}
    outcomes = [c.outcome for c in cascades]
    ratios = SplitRatios(0.6, 0.2, 0.2, gap_seconds=int(a.gap_hours * 3600))
    split = split_by_time(outcomes, ratios=ratios)
    cohort = CohortPolicy(bucket_seconds=int(a.cohort_hours * 3600))
    labeled = label_partitions(split, kind=LabelKind.DOUBLING, cohort=cohort)

    def mat(part: tuple, lbls: tuple) -> tuple[list[list[float]], list[int]]:
        x = [_early_features(by_id[o.cluster_id]).as_vector() for o in part]
        y = [int(v) for v in lbls]
        return x, y

    xtr, ytr = mat(split.train, labeled.train)
    xte, yte = mat(split.test, labeled.test)
    print(f"== C1 TRAIN (Higgs, obs={a.obs}s) ==")
    print(f"  features = {FEATURE_ORDER}")
    print(f"  train n={len(ytr)} pos={sum(ytr)}  test n={len(yte)} pos={sum(yte)}")
    if (
        sum(ytr) == 0
        or sum(ytr) == len(ytr)
        or len(yte) < 20
        or sum(yte) == 0
        or sum(yte) == len(yte)
    ):
        print("  degenerate split (single-class train/test or tiny) — abort")
        return 1

    import numpy as np

    train_set = lgb.Dataset(
        np.asarray(xtr, dtype=np.float64),
        label=np.asarray(ytr, dtype=np.int32),
        feature_name=list(FEATURE_ORDER),
    )
    params = {
        "objective": "binary",
        "metric": "average_precision",
        "num_leaves": 15,
        "learning_rate": 0.05,
        "min_data_in_leaf": 50,
        "verbose": -1,
    }
    booster = lgb.train(params, train_set, num_boost_round=200)
    probs = [float(p) for p in booster.predict(np.asarray(xte, dtype=np.float64))]

    print("\n== TEST PERFORMANCE ==")
    print(
        f"  GBDT      PR-AUC={average_precision(probs, yte):.3f}  ROC-AUC={roc_auc(probs, yte):.3f}"
    )
    # v2 formula fallback baseline on the SAME test split. watched_channels_count is the
    # size of the watched set, NOT engagement — use the count of distinct early sources
    # observed across the test cascades (final_outcome is weighted engagement, wrong unit).
    watched = max((int(c.features.e_ch) for c in cascades), default=1)
    fb = FormulaFallbackModel(watched_channels_count=max(watched, 1))
    # split.test and labeled.test are 1:1 by construction (label_partitions preserves
    # order); zip strict-asserts that alignment so a future refactor can't silently skew.
    fb_scores = [fb.predict_proba(_early_features(by_id[o.cluster_id])) for o in split.test]
    assert len(fb_scores) == len(yte), "fallback scores misaligned with test labels"
    fb_pr = average_precision(fb_scores, yte)
    fb_roc = roc_auc(fb_scores, yte)
    print(f"  v2 formula PR-AUC={fb_pr:.3f}  ROC-AUC={fb_roc:.3f}")

    print(f"\n== CALIBRATION ==\n  Brier (GBDT) = {_brier(probs, yte):.4f}  (lower is better)")
    for row in _reliability_table(probs, yte):
        print(row)

    if a.out is not None:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(a.out))
        print(f"\nsaved model → {a.out} (native LightGBM text; load via GbdtViralModel.load)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
