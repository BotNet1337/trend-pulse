"""Predictive early-detection harness — the honest test of scoring VALUE.

The descriptive harness (harness.py) showed cross_channel AUC=1.0 is CIRCULAR (the
term ~= the label). This harness removes the cheat by separating FEATURE TIME from
LABEL TIME:

  • cluster posts into stories (cosine 0.75) WITH A SPAN GUARD (a story may not exceed
    MAX_SPAN_H total — kills the recurring-boilerplate mega-clusters that chained
    "Доброе утро"/daily-market posts across all 9 months and inflated engagement).
  • EARLY window  = [t0, t0 + EARLY_H]; features use ONLY early posts.
  • LABELS (measured over the FULL story, i.e. the future):
       y_spread = story eventually reached >= MULTI_K distinct channels
       y_eng    = story's eventual total engagement >= P90 of all stories
  • time-split: first 70% of stories (by t0) = train, last 30% = test (no leakage).

Then it answers: can the EARLY signal predict eventual virality, and does the CURRENT
formula do it? It reports test-set ROC-AUC for:
  - the OLD prod viral_score computed on early features
  - each early feature alone (engagement, reach, #posts, burst)
  - a LEARNED logistic-regression score on early features (fitted on train)
and prints the fitted weights → a concrete, data-derived replacement formula.

It also reports the HARD task: among stories that are SINGLE-channel in the early
window, predict eventual spread (true "early mover" detection).

USAGE: uv run python harness2_predictive.py --early-hours 6 --max-span 72 --multi-k 3
"""

from __future__ import annotations

import argparse
import importlib.util as ilu
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

_score_path = Path(__file__).parent.parent / "backend" / "src" / "scorer" / "score.py"
_spec = ilu.spec_from_file_location("prod_score", _score_path)
_score = ilu.module_from_spec(_spec)
_spec.loader.exec_module(_score)
FORWARD_FACTOR, REACTION_FACTOR = _score.FORWARD_FACTOR, _score.REACTION_FACTOR
ScoreInputs, compute_components = _score.ScoreInputs, _score.compute_components

from score_v2 import ScoreInputsV2, compute_viral_score_v2  # noqa: E402

DB = Path(__file__).parent / "data" / "corpus.sqlite"
EMB_CACHE = Path(__file__).parent / "data" / "emb.npy"
EMB_MODEL = "all-MiniLM-L6-v2"
MIN_TEXT_LEN = 20


def eng(v, f, r):
    return float(v + f * FORWARD_FACTOR + r * REACTION_FACTOR)


def load():
    con = sqlite3.connect(DB)
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


def get_emb(texts):
    if EMB_CACHE.exists():
        arr = np.load(EMB_CACHE)
        if len(arr) == len(texts):
            return arr
    from sentence_transformers import SentenceTransformer

    m = SentenceTransformer(EMB_MODEL)
    arr = np.asarray(
        m.encode(texts, batch_size=256, show_progress_bar=True, normalize_embeddings=True),
        dtype=np.float32,
    )
    np.save(EMB_CACHE, arr)
    return arr


def cluster(posts, vecs, thr, win_s, max_span_s):
    """Greedy cosine clustering with BOTH a window gate (vs latest post) and a hard
    cap on total story span (vs first post) — the span cap kills boilerplate chains."""
    clusters, cent, last_ts, first_ts, active = [], [], [], [], []
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
            cent[best] = (cent[best] * len(m) + vecs[i]) / (len(m) + 1)
            n = np.linalg.norm(cent[best])
            if n:
                cent[best] /= n
            m.append(i)
            last_ts[best] = t
    return clusters


def roc_auc(y, s):
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    ss = s[order]
    i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    pos = y == 1
    npos, nneg = int(pos.sum()), int((~pos).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    return float((ranks[pos].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def patk(y, s, k):
    return float(y[np.argsort(-s, kind="mergesort")[:k]].mean()) if len(s) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--early-hours", type=float, default=6.0)
    ap.add_argument("--window-hours", type=float, default=48.0)
    ap.add_argument("--max-span", type=float, default=72.0)
    ap.add_argument("--cluster-threshold", type=float, default=0.75)
    ap.add_argument("--multi-k", type=int, default=3)
    a = ap.parse_args()

    posts = load()
    watched = len({p[0] for p in posts})
    print(f"== CORPUS == posts={len(posts)} channels={watched}")
    base = defaultdict(list)
    for p in posts:
        base[p[0]].append(eng(p[3], p[4], p[5]))
    chan_base = {h: float(np.mean(v)) for h, v in base.items()}

    vecs = get_emb([p[2] for p in posts])
    cl = cluster(posts, vecs, a.cluster_threshold, a.window_hours * 3600, a.max_span * 3600)
    print(f"== CLUSTERING (span<= {a.max_span}h) == clusters={len(cl)} "
          f"multi_post={sum(len(c)>1 for c in cl)}")
    for k in (2, 3, 5, 8):
        print(f"  >= {k} channels: {sum(len({posts[i][0] for i in c})>=k for c in cl)}")

    early_s = a.early_hours * 3600
    rows = []  # per story: features (early) + labels (full)
    for c in cl:
        t0 = posts[c[0]][1]
        early = [i for i in c if posts[i][1] - t0 <= early_s]
        e_ch = len({posts[i][0] for i in early})
        e_posts = len(early)
        e_eng = sum(eng(posts[i][3], posts[i][4], posts[i][5]) for i in early)
        e_span_h = max(1e-3, (max(posts[i][1] for i in early) - t0) / 3600.0)
        e_burst = e_ch / max(e_span_h, a.early_hours)  # channels per hour, early
        e_base = np.mean([chan_base[posts[i][0]] for i in early])
        # Compute the three RAW components LOCALLY (independent of prod score.py state,
        # which may already be edited to v2) so we can isolate each formula change:
        e_v, e_f, e_r = (sum(posts[i][k] for i in early) for k in (3, 4, 5))
        weighted = eng(e_v, e_f, e_r)
        vel_t15 = math.log1p(max(e_ch - 1, 0)) / max(e_span_h, 1.0 / 60.0)  # T15, 1-min clamp
        eng_norm = weighted / max(e_base, 1e-9)  # channel_avg-normalized (TASK-041), unbounded
        cc = min(e_ch / watched, 1.0)
        old = 0.40 * vel_t15 + 0.35 * eng_norm + 0.25 * cc          # current prod
        reweight = 0.15 * vel_t15 + 0.55 * eng_norm + 0.30 * cc     # ONLY weights changed
        v2 = compute_viral_score_v2(ScoreInputsV2(                  # full v2 (bounded, raw-log)
            views=e_v, forwards=e_f, reactions=e_r,
            delta_hours=e_span_h, unique_channels_count=e_ch, watched_channels_count=watched,
        ))
        full_ch = len({posts[i][0] for i in c})
        full_eng = sum(eng(posts[i][3], posts[i][4], posts[i][5]) for i in c)
        rows.append({
            "t0": t0, "e_ch": e_ch, "e_posts": e_posts,
            "e_eng_log": np.log1p(e_eng), "e_eng_norm": e_eng / max(e_base, 1.0),
            "e_burst": e_burst, "old": old, "reweight": reweight, "v2": v2,
            "full_ch": full_ch, "full_eng": full_eng,
        })

    rows.sort(key=lambda r: r["t0"])
    n = len(rows)
    split = int(n * 0.7)
    p90_eng = np.percentile([r["full_eng"] for r in rows], 90)
    y_spread = np.array([1 if r["full_ch"] >= a.multi_k else 0 for r in rows])
    y_eng = np.array([1 if r["full_eng"] >= p90_eng else 0 for r in rows])

    feats = ["e_ch", "e_posts", "e_eng_log", "e_eng_norm", "e_burst"]
    X = np.array([[r[f] for f in feats] for r in rows], dtype=np.float64)
    old_score = np.array([r["old"] for r in rows])
    reweight_score = np.array([r["reweight"] for r in rows])
    v2_score = np.array([r["v2"] for r in rows])

    def report(y, name):
        ytr, yte = y[:split], y[split:]
        print(f"\n== PREDICTIVE: {name} (train={split} test={n-split}, "
              f"test_pos={int(yte.sum())}) ==")
        print(f"  {'OLD (0.4/0.35/0.25)':28} test-AUC={roc_auc(yte, old_score[split:]):.3f}  "
              f"P@20={patk(yte, old_score[split:],20):.2f}")
        print(f"  {'REWEIGHT-ONLY (0.15/.55/.30)':28} test-AUC={roc_auc(yte, reweight_score[split:]):.3f}  "
              f"P@20={patk(yte, reweight_score[split:],20):.2f}")
        print(f"  {'>> FULL v2 (bounded+rawlog)':28} test-AUC={roc_auc(yte, v2_score[split:]):.3f}  "
              f"P@20={patk(yte, v2_score[split:],20):.2f}")
        for fi, f in enumerate(feats):
            print(f"  {f:24} test-AUC={roc_auc(yte, X[split:,fi]):.3f}  "
                  f"P@20={patk(yte, X[split:,fi],20):.2f}")
        # learned logistic regression on early features (standardized)
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        sc = StandardScaler().fit(X[:split])
        Xtr, Xte = sc.transform(X[:split]), sc.transform(X[split:])
        if len(set(ytr.tolist())) < 2:
            print("  (train has one class — skip learned model)")
            return
        lr = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xtr, ytr)
        ps = lr.predict_proba(Xte)[:, 1]
        print(f"  {'LEARNED score_v2':24} test-AUC={roc_auc(yte, ps):.3f}  "
              f"P@20={patk(yte, ps,20):.2f}")
        wt = " + ".join(f"{c:+.2f}·{f}" for c, f in zip(lr.coef_[0], feats))
        print(f"    weights (on standardized feats): {wt}")

    report(y_spread, f"eventual reach >= {a.multi_k} channels")
    report(y_eng, "eventual engagement >= P90 (decoupled from channel count)")

    # HARD task: stories single-channel in the early window — can we predict spread?
    mask = X[:, 0] == 1  # e_ch == 1
    if mask.sum() > 50:
        idx = np.where(mask)[0]
        sp = int(idx.searchsorted(split))
        tr, te = idx[:sp], idx[sp:]
        yte = y_spread[te]
        print(f"\n== HARD: early SINGLE-channel movers (n={len(idx)}, test={len(te)}, "
              f"test_pos={int(yte.sum())}) → predict eventual >= {a.multi_k}ch ==")
        if len(te) and 0 < yte.sum() < len(yte):
            for fi, f in enumerate(feats):
                if f == "e_ch":
                    continue
                print(f"  {f:24} test-AUC={roc_auc(yte, X[te,fi]):.3f}")
            print(f"  {'OLD viral_score':24} test-AUC={roc_auc(yte, old_score[te]):.3f}")
            print(f"  {'>> NEW score_v2':24} test-AUC={roc_auc(yte, v2_score[te]):.3f}")
        else:
            print("  not enough positives in test split for a stable AUC")


if __name__ == "__main__":
    raise SystemExit(main())
