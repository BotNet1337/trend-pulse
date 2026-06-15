"""Forward-time-split early-detection harness — the no-leakage PR-AUC-vs-window test.

TASK-110 (Track B→C / B2). Where harness2 used a single fixed early window + a
hand-picked label, this harness sweeps the OBSERVATION WINDOW (15m/30m/1h/3h/6h) and,
for each window, measures how well early features predict eventual virality under the
Cheng et al. (WWW'14) *balanced doubling* label — plus a top-quartile and a
log-regression variant — on a leak-free chronological split with a boundary gap.

Pipeline (reuses B0/B1/B2 primitives, nothing reimplemented):

  1. cluster posts into stories (harness2 method: cosine 0.75 + 48h window + 72h span
     guard — kills boilerplate chains).
  2. gate every story through the B0 quality gate (`eval.quality.is_quality_cluster`)
     so we train/eval on the clean subset only.
  3. for each T_obs window: build EARLY features over [t0, t0+T_obs] only (the B1
     snapshot metric shape) + the cluster's FUTURE outcome over its full life.
  4. chronological split (B2 `split_by_time`) older→train / newer→test with a GAP.
  5. label each partition from its OWN cohort (B2 `label_partitions`) — no leakage.
  6. report test-set PR-AUC (`eval.metrics.average_precision`) + ROC-AUC for: the v2
     formula, each early feature alone, and a learned logistic blend.

USAGE (corpus.sqlite + emb.npy live in the shared trendPulse worktree):
  uv run python harness3_forward_split.py \
      --db ../../trendPulse/eval_offline/data/corpus.sqlite \
      --emb ../../trendPulse/eval_offline/data/emb.npy
"""

from __future__ import annotations

import argparse
import importlib.util as ilu
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

_BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src"
sys.path.insert(0, str(_BACKEND_SRC))

from eval.forward_split import (  # noqa: E402
    CohortPolicy,
    ClusterOutcome,
    LabelKind,
    Partition,
    SplitRatios,
    label_partitions,
    split_by_time,
)
from eval.metrics import average_precision, precision_at_k, roc_auc  # noqa: E402
from eval.quality import (  # noqa: E402
    ClusterQualityFeatures,
    QualityThresholds,
    is_quality_cluster,
)

_score_path = _BACKEND_SRC / "scorer" / "score.py"
_spec = ilu.spec_from_file_location("prod_score", _score_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load prod scorer module from {_score_path}")
_score = ilu.module_from_spec(_spec)
_spec.loader.exec_module(_score)
FORWARD_FACTOR, REACTION_FACTOR = _score.FORWARD_FACTOR, _score.REACTION_FACTOR

sys.path.insert(0, str(Path(__file__).parent))
from score_v2 import ScoreInputsV2, compute_viral_score_v2  # noqa: E402

MIN_TEXT_LEN = 20
EMB_MODEL = "all-MiniLM-L6-v2"
WINDOWS_SECONDS: dict[str, int] = {
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 3600,
    "3h": 3 * 3600,
    "6h": 6 * 3600,
}


def eng(views: int, forwards: int, reactions: int) -> float:
    return float(views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR)


def load(db: Path) -> list[tuple[str, float, str, int, int, int]]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT handle, posted_at, text, views, forwards, reactions FROM posts "
        "WHERE text IS NOT NULL AND length(text)>=? ORDER BY posted_at",
        (MIN_TEXT_LEN,),
    ).fetchall()
    con.close()
    return [
        (h, datetime.fromisoformat(ts).timestamp(), txt, v or 0, f or 0, r or 0)
        for h, ts, txt, v, f, r in rows
    ]


def get_emb(texts: list[str], cache: Path) -> np.ndarray:
    if cache.exists():
        arr = np.load(cache)
        if len(arr) == len(texts):
            return arr
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMB_MODEL)
    arr = np.asarray(
        model.encode(texts, batch_size=256, show_progress_bar=True, normalize_embeddings=True),
        dtype=np.float32,
    )
    np.save(cache, arr)
    return arr


def cluster(
    posts: list[tuple[str, float, str, int, int, int]],
    vecs: np.ndarray,
    thr: float,
    win_s: float,
    max_span_s: float,
) -> list[list[int]]:
    clusters: list[list[int]] = []
    cent: list[np.ndarray] = []
    last_ts: list[float] = []
    first_ts: list[float] = []
    active: list[int] = []
    for i, p in enumerate(posts):
        t = p[1]
        active = [c for c in active if t - last_ts[c] <= win_s and t - first_ts[c] <= max_span_s]
        best, best_sim = -1, thr
        for c in active:
            s = float(np.dot(vecs[i], cent[c]))
            if s >= best_sim:
                best_sim, best = s, c
        if best == -1:
            clusters.append([i])
            cent.append(vecs[i].copy())
            last_ts.append(t)
            first_ts.append(t)
            active.append(len(clusters) - 1)
        else:
            m = clusters[best]
            updated = (cent[best] * len(m) + vecs[i]) / (len(m) + 1)
            norm = np.linalg.norm(updated)
            cent[best] = updated / norm if norm else updated  # new array, no in-place mutation
            m.append(i)
            last_ts[best] = t
    return clusters


def quality_filter(
    clusters: list[list[int]], posts: list[tuple[str, float, str, int, int, int]]
) -> list[list[int]]:
    """Keep only stories passing the B0 quality gate (clean training subset)."""
    thresholds = QualityThresholds()
    kept: list[list[int]] = []
    for cid, c in enumerate(clusters):
        handles = [posts[i][0] for i in c]
        channel_counts: dict[str, int] = defaultdict(int)
        for h in handles:
            channel_counts[h] += 1
        timestamps = [posts[i][1] for i in c]
        span = int(max(timestamps) - min(timestamps)) if c else 0
        top_share = (max(channel_counts.values()) / len(c)) if c else 0.0
        features = ClusterQualityFeatures(
            cluster_id=cid,
            post_count=len(c),
            unique_channels=len(channel_counts),
            span_seconds=span,
            # offline corpus has no cross-cluster cosine pass here (harness2 clustered
            # it greedily); 0.0 = "not a near-duplicate" → defer that gate to the
            # corpus-wide audit (quality_report.py). Fetch-lag unknown offline → 0.
            max_cross_cluster_cosine=0.0,
            top_channel_share=top_share,
            completeness_ok=True,
            max_fetch_lag_seconds=0.0,
        )
        if is_quality_cluster(features, thresholds=thresholds):
            kept.append(c)
    return kept


def build_window_rows(
    clusters: list[list[int]],
    posts: list[tuple[str, float, str, int, int, int]],
    watched: int,
    chan_base: dict[str, float],
    obs_seconds: int,
) -> tuple[list[ClusterOutcome], dict[int, dict[str, float]]]:
    """Per story: early features in [t0, t0+obs] + the future outcome. Skip empty-window."""
    outcomes: list[ClusterOutcome] = []
    feats_by_id: dict[int, dict[str, float]] = {}
    for cid, c in enumerate(clusters):
        t0 = min(posts[i][1] for i in c)  # earliest birth (explicit, not sort-dependent)
        early = [i for i in c if posts[i][1] - t0 <= obs_seconds]
        if not early:
            continue
        e_ch = len({posts[i][0] for i in early})
        e_v = sum(posts[i][3] for i in early)
        e_f = sum(posts[i][4] for i in early)
        e_r = sum(posts[i][5] for i in early)
        e_eng = eng(e_v, e_f, e_r)
        e_span_h = max(1e-3, (max(posts[i][1] for i in early) - t0) / 3600.0)
        e_base = float(np.mean([chan_base[posts[i][0]] for i in early]))
        v2 = compute_viral_score_v2(
            ScoreInputsV2(
                views=e_v,
                forwards=e_f,
                reactions=e_r,
                delta_hours=e_span_h,
                unique_channels_count=e_ch,
                watched_channels_count=watched,
            )
        )
        full_eng = eng(
            sum(posts[i][3] for i in c),
            sum(posts[i][4] for i in c),
            sum(posts[i][5] for i in c),
        )
        age = int(max(posts[i][1] for i in c) - t0)
        outcomes.append(
            ClusterOutcome(
                cluster_id=cid, t0_epoch=t0, final_outcome=full_eng, age_at_outcome_seconds=age
            )
        )
        feats_by_id[cid] = {
            "e_ch": float(e_ch),
            "e_posts": float(len(early)),
            "e_eng_log": float(np.log1p(e_eng)),
            "e_eng_norm": float(e_eng / max(e_base, 1.0)),
            "e_burst": float(e_ch / max(e_span_h, obs_seconds / 3600.0)),
            "v2": float(v2),
        }
    return outcomes, feats_by_id


FEATS = ("e_ch", "e_posts", "e_eng_log", "e_eng_norm", "e_burst")


def evaluate_window(
    outcomes: list[ClusterOutcome],
    feats_by_id: dict[int, dict[str, float]],
    label_kind: LabelKind,
    cohort: CohortPolicy,
    ratios: SplitRatios,
) -> None:
    split = split_by_time(outcomes, ratios=ratios)
    labeled = label_partitions(split, kind=label_kind, cohort=cohort)
    train, test = split.train, split.test
    ytr = [int(v) for v in labeled.train]
    yte = [int(v) for v in labeled.test]
    n_pos = sum(yte)
    print(
        f"  split train={len(train)} test={len(test)} dropped_gap={len(split.dropped_in_gap)} "
        f"test_pos={n_pos}/{len(yte)}"
    )
    if len(test) < 10 or n_pos == 0 or n_pos == len(yte):
        print("    (degenerate test split — too few stories / one class; N-limited)")
        return

    def col(part: tuple[ClusterOutcome, ...], key: str) -> list[float]:
        return [feats_by_id[c.cluster_id][key] for c in part]

    for name, key in (("v2", "v2"), *((f, f) for f in FEATS)):
        s = col(test, key)
        try:
            pr = average_precision(s, yte)
            rc = roc_auc(s, yte)
            pk = precision_at_k(s, yte, 20)
            print(f"    {name:12} PR-AUC={pr:.3f}  ROC-AUC={rc:.3f}  P@20={pk:.2f}")
        except Exception as exc:  # noqa: BLE001 - report, don't crash the sweep
            print(f"    {name:12} (skip: {exc})")

    # learned logistic blend on early features (standardized), fit on train only
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        xtr = np.array([[feats_by_id[c.cluster_id][f] for f in FEATS] for c in train])
        xte = np.array([[feats_by_id[c.cluster_id][f] for f in FEATS] for c in test])
        if len(set(ytr)) == 2:
            sc = StandardScaler().fit(xtr)
            lr = LogisticRegression(max_iter=1000, class_weight="balanced").fit(
                sc.transform(xtr), ytr
            )
            ps = lr.predict_proba(sc.transform(xte))[:, 1].tolist()
            print(
                f"    {'LEARNED':12} PR-AUC={average_precision(ps, yte):.3f}  "
                f"ROC-AUC={roc_auc(ps, yte):.3f}  P@20={precision_at_k(ps, yte, 20):.2f}"
            )
    except ImportError:
        print("    (sklearn not installed — skipping learned blend)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("data/corpus.sqlite"))
    ap.add_argument("--emb", type=Path, default=Path("data/emb.npy"))
    ap.add_argument("--window-hours", type=float, default=48.0)
    ap.add_argument("--max-span", type=float, default=72.0)
    ap.add_argument("--cluster-threshold", type=float, default=0.75)
    ap.add_argument("--gap-hours", type=float, default=24.0)
    ap.add_argument("--cohort-hours", type=float, default=6.0)
    a = ap.parse_args()

    if not a.db.exists():
        print(f"corpus not found: {a.db} — pass --db to the shared trendPulse worktree")
        return 1

    posts = load(a.db)
    watched = len({p[0] for p in posts})
    print(f"== CORPUS == posts={len(posts)} channels={watched}")
    base: dict[str, list[float]] = defaultdict(list)
    for p in posts:
        base[p[0]].append(eng(p[3], p[4], p[5]))
    chan_base = {h: float(np.mean(v)) for h, v in base.items()}

    vecs = get_emb([p[2] for p in posts], a.emb)
    cl = cluster(
        posts, vecs, a.cluster_threshold, a.window_hours * 3600, a.max_span * 3600
    )
    print(f"== CLUSTERING == stories={len(cl)} multi_post={sum(len(c) > 1 for c in cl)}")
    gated = quality_filter(cl, posts)
    print(f"== B0 QUALITY GATE == {len(gated)}/{len(cl)} stories pass")

    ratios = SplitRatios(0.6, 0.2, 0.2, gap_seconds=int(a.gap_hours * 3600))
    cohort = CohortPolicy(bucket_seconds=int(a.cohort_hours * 3600))

    for label_kind in (LabelKind.DOUBLING, LabelKind.TOP_QUARTILE):
        print(f"\n#### LABEL = {label_kind.value} (cohort buckets {a.cohort_hours}h) ####")
        for label, obs_s in WINDOWS_SECONDS.items():
            outcomes, feats = build_window_rows(gated, posts, watched, chan_base, obs_s)
            print(f"\n== T_obs = {label} (n_stories={len(outcomes)}) ==")
            evaluate_window(outcomes, feats, label_kind, cohort, ratios)

    # also report on the UNGATED set (for the N-limitation contrast)
    print("\n#### (contrast) UNGATED, label=doubling, T_obs=1h ####")
    outcomes, feats = build_window_rows(cl, posts, watched, chan_base, 3600)
    print(f"== n_stories={len(outcomes)} ==")
    evaluate_window(outcomes, feats, LabelKind.DOUBLING, cohort, ratios)

    _ = Partition  # exported for typed callers / future use
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
