"""C2 lift harness — does each science feature ADD predictive signal? (TASK-113)

For each C2 feature (eval.science_features), measure on the leak-free B2 test split of
the Higgs cascades:
  - the feature's STANDALONE test PR-AUC / ROC-AUC (is it predictive at all?), and
  - the MARGINAL lift: base-feature GBDT PR-AUC vs base+this-feature GBDT PR-AUC.
Only features that pay (positive marginal lift) are worth wiring into C1's vector.

USAGE:
  uv run python harness_c2_lift.py --higgs data/higgs-activity_time.txt --obs 3600
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
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
from eval.science_features import TimedEvent, compute_science_features  # noqa: E402

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from public_datasets import (  # noqa: E402
    _INTERACTION_WEIGHT,
    CascadeEvent,
    group_cascades,
    load_higgs,
)

# base C1 features (the GBDT vector today) + the C2 candidates appended one at a time.
_BASE = ("e_ch", "e_posts", "e_eng_log", "e_burst")
_C2 = (
    "ewma_velocity",
    "ewma_acceleration",
    "breadth_velocity",
    "hawkes_branching",
    "time_of_day_phase",
    "effective_independent_sources",
    "channel_authority",
)


def _early_events(cascade: list[CascadeEvent], obs_seconds: int) -> list[TimedEvent]:
    t0 = cascade[0].epoch
    return [
        TimedEvent(
            epoch=float(e.epoch), source_id=e.source_id, weight=_INTERACTION_WEIGHT[e.interaction]
        )
        for e in cascade
        if e.epoch - t0 <= obs_seconds
    ]


def main() -> int:
    import math

    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("--higgs", type=Path, default=Path("data/higgs-activity_time.txt"))
    ap.add_argument("--obs", type=int, default=3600)
    ap.add_argument("--gap-hours", type=float, default=6.0)
    ap.add_argument("--cohort-hours", type=float, default=1.0)
    a = ap.parse_args()
    if not a.higgs.exists():
        print(f"Higgs not found: {a.higgs}")
        return 1
    try:
        import lightgbm as lgb
    except ImportError:
        print("lightgbm not installed")
        return 1

    events = load_higgs(a.higgs)
    grouped = group_cascades(events)
    from eval.forward_split import ClusterOutcome

    outcomes: list[ClusterOutcome] = []
    feats: dict[int, dict[str, float]] = {}
    for cid, target in enumerate(sorted(grouped)):
        cascade = grouped[target]
        if len(cascade) < 2:
            continue
        early = _early_events(cascade, a.obs)
        if not early:
            continue
        t0 = cascade[0].epoch
        full_eng = sum(_INTERACTION_WEIGHT[e.interaction] for e in cascade)
        outcomes.append(
            ClusterOutcome(
                cluster_id=cid,
                t0_epoch=float(t0),
                final_outcome=full_eng,
                age_at_outcome_seconds=cascade[-1].epoch - t0,
            )
        )
        distinct = len({e.source_id for e in early})
        early_eng = sum(e.weight for e in early)  # early are TimedEvents (weight set)
        span_h = max((early[-1].epoch - t0) / 3600.0, 1.0 / 60.0)
        sci = compute_science_features(
            early, birth_epoch=float(t0), ewma_half_life_seconds=900.0, hawkes_decay_seconds=600.0
        )
        feats[cid] = {
            "e_ch": float(distinct),
            "e_posts": float(len(early)),
            "e_eng_log": math.log1p(early_eng),
            "e_burst": distinct / max(span_h, a.obs / 3600.0),
            "ewma_velocity": sci.ewma_velocity,
            "ewma_acceleration": sci.ewma_acceleration,
            "breadth_velocity": sci.breadth_velocity,
            "hawkes_branching": sci.hawkes_branching,
            "time_of_day_phase": sci.time_of_day_phase,
            "effective_independent_sources": sci.effective_independent_sources,
            "channel_authority": sci.channel_authority,
        }

    ratios = SplitRatios(0.6, 0.2, 0.2, gap_seconds=int(a.gap_hours * 3600))
    split = split_by_time(outcomes, ratios=ratios)
    labeled = label_partitions(
        split,
        kind=LabelKind.DOUBLING,
        cohort=CohortPolicy(bucket_seconds=int(a.cohort_hours * 3600)),
    )
    ytr = [int(v) for v in labeled.train]
    yte = [int(v) for v in labeled.test]
    print(
        f"== C2 LIFT (Higgs obs={a.obs}s) train={len(ytr)} test={len(yte)} test_pos={sum(yte)} =="
    )
    if sum(ytr) in (0, len(ytr)) or sum(yte) in (0, len(yte)) or len(yte) < 20:
        print("degenerate split")
        return 1

    def cols(part: tuple, names: tuple[str, ...]) -> np.ndarray:
        return np.asarray([[feats[o.cluster_id][n] for n in names] for o in part], dtype=np.float64)

    def gbdt_pr(names: tuple[str, ...]) -> float:
        ds = lgb.Dataset(cols(split.train, names), label=np.asarray(ytr, dtype=np.int32))
        params = {
            "objective": "binary",
            "num_leaves": 15,
            "learning_rate": 0.05,
            "min_data_in_leaf": 50,
            "verbose": -1,
        }
        b = lgb.train(params, ds, num_boost_round=200)
        return average_precision([float(p) for p in b.predict(cols(split.test, names))], yte)

    print("\n-- standalone (single-feature test AUC) --")
    for name in _C2:
        scores = [feats[o.cluster_id][name] for o in split.test]
        try:
            pr = average_precision(scores, yte)
            rc = roc_auc(scores, yte)
            print(f"  {name:32} PR-AUC={pr:.3f}  ROC-AUC={rc:.3f}")
        except Exception as exc:
            print(f"  {name:32} (skip: {exc})")

    base_pr = gbdt_pr(_BASE)
    print(f"\n-- marginal lift over base GBDT (base PR-AUC={base_pr:.3f}) --")
    lifts: dict[str, float] = defaultdict(float)
    for name in _C2:
        pr = gbdt_pr((*_BASE, name))
        lifts[name] = pr - base_pr
        print(f"  +{name:32} PR-AUC={pr:.3f}  Δ={pr - base_pr:+.3f}")
    all_pr = gbdt_pr((*_BASE, *_C2))
    print(f"\n  base + ALL C2 features  PR-AUC={all_pr:.3f}  Δ={all_pr - base_pr:+.3f}")
    best = max(lifts, key=lambda k: lifts[k])
    print(f"  best single C2 feature: {best} (Δ={lifts[best]:+.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
