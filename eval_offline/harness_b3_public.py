"""B3 validation harness — run the B2 forward-time-split on public cascade data.

TASK-111 (Track B→C / B3). Loads the Higgs Twitter activity stream, maps it into the
shared B2 contract (`public_datasets.map_higgs_to_b2`), and runs the SAME leak-free
chronological split + Cheng doubling/top-quartile label + PR-AUC sweep the TG harness
(`harness3_forward_split`) uses — proving the methodology transfers and supplies the
training VOLUME the N-limited TG corpus lacks (B0: only ~315 quality TG stories).

USAGE (full file gitignored under data/; sample committed under data_public/):
  uv run python harness_b3_public.py --higgs data/higgs-activity_time.txt
  uv run python harness_b3_public.py --higgs data_public/higgs_activity_sample.txt
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
from eval.metrics import average_precision, precision_at_k, roc_auc  # noqa: E402

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from public_datasets import (  # noqa: E402
    MappedCascade,
    bootstrap_status,
    load_higgs,
    map_higgs_to_b2,
)

WINDOWS_SECONDS: dict[str, int] = {
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 3600,
    "3h": 3 * 3600,
    "6h": 6 * 3600,
}
FEATS = ("e_ch", "e_posts", "e_eng_log", "e_burst")


def _feature(cascade: MappedCascade, key: str) -> float:
    return float(getattr(cascade.features, key))


def evaluate_window(
    cascades: list[MappedCascade],
    label_kind: LabelKind,
    cohort: CohortPolicy,
    ratios: SplitRatios,
) -> None:
    by_id = {c.outcome.cluster_id: c for c in cascades}
    outcomes = [c.outcome for c in cascades]
    split = split_by_time(outcomes, ratios=ratios)
    labeled = label_partitions(split, kind=label_kind, cohort=cohort)
    yte = [int(v) for v in labeled.test]
    n_pos = sum(yte)
    print(
        f"  split train={len(split.train)} test={len(split.test)} "
        f"dropped_gap={len(split.dropped_in_gap)} test_pos={n_pos}/{len(yte)}"
    )
    if len(split.test) < 10 or n_pos == 0 or n_pos == len(yte):
        print("    (degenerate test split — too few / one class)")
        return
    for key in FEATS:
        scores = [_feature(by_id[c.cluster_id], key) for c in split.test]
        try:
            print(
                f"    {key:12} PR-AUC={average_precision(scores, yte):.3f}  "
                f"ROC-AUC={roc_auc(scores, yte):.3f}  P@20={precision_at_k(scores, yte, 20):.2f}"
            )
        except Exception as exc:
            print(f"    {key:12} (skip: {exc})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--higgs", type=Path, default=Path("data_public/higgs_activity_sample.txt"))
    ap.add_argument("--gap-hours", type=float, default=6.0)
    ap.add_argument("--cohort-hours", type=float, default=1.0)
    ap.add_argument("--min-cascade", type=int, default=2)
    a = ap.parse_args()

    print("== B3 PUBLIC-DATASET BOOTSTRAP STATUS ==")
    for status in bootstrap_status():
        mark = "OK " if status.available else "SKIP"
        print(f"  [{mark}] {status.name}: {status.note}")

    if not a.higgs.exists():
        print(f"\nHiggs file not found: {a.higgs} — download from snap.stanford.edu")
        return 1

    events = load_higgs(a.higgs)
    print(f"\n== HIGGS == events={len(events)} from {a.higgs.name}")

    ratios = SplitRatios(0.6, 0.2, 0.2, gap_seconds=int(a.gap_hours * 3600))
    cohort = CohortPolicy(bucket_seconds=int(a.cohort_hours * 3600))

    for label_kind in (LabelKind.DOUBLING, LabelKind.TOP_QUARTILE):
        print(f"\n#### LABEL = {label_kind.value} (cohort {a.cohort_hours}h) ####")
        for label, obs_s in WINDOWS_SECONDS.items():
            cascades = map_higgs_to_b2(
                events, obs_seconds=obs_s, min_cascade_size=a.min_cascade
            )
            print(f"\n== T_obs = {label} (cascades={len(cascades)}) ==")
            evaluate_window(cascades, label_kind, cohort, ratios)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
