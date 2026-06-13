"""Calibrate the v2 alert threshold on the real corpus.

Scores FULL clusters (what the live scorer sees as a story matures) with the prod v2
formula and reports, for a sweep of 0–100 thresholds, how well it separates real
cross-channel stories (>= MULTI_K channels) from single-channel noise — precision,
recall, F1 — so we can pick a defensible default (packs / watchlist).
"""

from __future__ import annotations

import argparse
import importlib.util as ilu
from pathlib import Path

import numpy as np

from harness2_predictive import cluster, eng, get_emb, load

_p = Path(__file__).parent.parent / "backend" / "src" / "scorer" / "score.py"
_s = ilu.spec_from_file_location("prod_score", _p)
_score = ilu.module_from_spec(_s)
_s.loader.exec_module(_score)
ScoreInputs, compute_viral_score = _score.ScoreInputs, _score.compute_viral_score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster-threshold", type=float, default=0.75)
    ap.add_argument("--window-hours", type=float, default=48.0)
    ap.add_argument("--max-span", type=float, default=72.0)
    ap.add_argument("--multi-k", type=int, default=3)
    a = ap.parse_args()

    posts = load()
    watched = len({p[0] for p in posts})
    vecs = get_emb([p[2] for p in posts])
    cl = cluster(posts, vecs, a.cluster_threshold, a.window_hours * 3600, a.max_span * 3600)

    scores, labels = [], []
    for c in cl:
        chans = {posts[i][0] for i in c}
        times = [posts[i][1] for i in c]
        vs = compute_viral_score(ScoreInputs(
            views=sum(posts[i][3] for i in c),
            forwards=sum(posts[i][4] for i in c),
            reactions=sum(posts[i][5] for i in c),
            channel_avg=1.0,  # unused by v2
            delta_channel_count=len(chans),
            delta_hours=(max(times) - min(times)) / 3600.0,
            unique_channels_count=len(chans),
            watched_channels_count=watched,
        ))
        scores.append(vs)
        labels.append(1 if len(chans) >= a.multi_k else 0)
    scores = np.array(scores)
    labels = np.array(labels)

    print(f"clusters={len(scores)} positives(>= {a.multi_k}ch)={int(labels.sum())} watched={watched}")
    print(f"v2 score: min={scores.min():.1f} p50={np.percentile(scores,50):.1f} "
          f"p90={np.percentile(scores,90):.1f} p99={np.percentile(scores,99):.1f} max={scores.max():.1f}")
    print(f"score on POSITIVES: p10={np.percentile(scores[labels==1],10):.1f} "
          f"p50={np.percentile(scores[labels==1],50):.1f} p90={np.percentile(scores[labels==1],90):.1f}")
    print(f"score on NEGATIVES: p50={np.percentile(scores[labels==0],50):.1f} "
          f"p90={np.percentile(scores[labels==0],90):.1f} p99={np.percentile(scores[labels==0],99):.1f}")
    print("\n thr | fires | precision | recall | F1")
    best = (0.0, -1.0)
    for thr in range(10, 95, 5):
        fire = scores >= thr
        tp = int((fire & (labels == 1)).sum())
        fp = int((fire & (labels == 0)).sum())
        fn = int((~fire & (labels == 1)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best[1]:
            best = (float(thr), f1)
        print(f" {thr:3d} | {int(fire.sum()):5d} | {prec:.3f}     | {rec:.3f}  | {f1:.3f}")
    print(f"\nbest-F1 threshold ≈ {best[0]:.0f} (F1={best[1]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
