"""Offline meaningfulness harness for the TrendPulse viral-score.

Pipeline (mirrors prod where it matters):
  load corpus.sqlite -> embed (all-MiniLM-L6-v2, == prod embedding_model_name)
  -> TIME-WINDOWED greedy cosine clustering (>= cluster_cosine_threshold, == prod 0.75,
     PLUS a time gate: a post only joins a cluster within WINDOW_HOURS of its latest post,
     because a "viral event" is a story across channels in a short window, not the same
     phrase reused months apart) -> score each cluster with the prod formula.

Then it answers the only question that matters: DOES THE SCORE HAVE SIGNAL on real
multi-channel data? It reports:
  1. corpus + clustering census (incl. multi-channel cluster counts — 0 in prod today)
  2. score + component distributions, and the velocity clamp-floor degeneracy rate
  3. meaningfulness: treat "story corroborated across >= MULTI_K distinct channels" as the
     positive class (a real cross-channel event) vs single-channel noise, and measure how
     well viral_score — and each term ALONE (ablation) — ranks positives: ROC-AUC,
     PR-AUC, precision@k, Spearman. Ablation shows WHICH term carries the signal.
  4. top clusters by score, with a text snippet, to eyeball "is this a real signal".

It imports the prod score formula directly (single source of truth) — no re-derivation.

USAGE:
  uv run python harness.py                      # uses data/corpus.sqlite
  uv run python harness.py --window-hours 48 --multi-k 3 --cluster-threshold 0.75
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

# ── prod score formula: single source of truth ───────────────────────────────
# Load score.py BY PATH (bypass scorer/__init__.py, which pulls sqlalchemy via tasks).
import importlib.util as _ilu  # noqa: E402

_score_path = Path(__file__).parent.parent / "backend" / "src" / "scorer" / "score.py"
_spec = _ilu.spec_from_file_location("prod_score", _score_path)
_score = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_score)
FORWARD_FACTOR = _score.FORWARD_FACTOR
REACTION_FACTOR = _score.REACTION_FACTOR
MIN_WINDOW_HOURS = _score.MIN_WINDOW_HOURS
ScoreInputs = _score.ScoreInputs
compute_components = _score.compute_components

DB_PATH = Path(__file__).parent / "data" / "corpus.sqlite"
EMBED_MODEL = "all-MiniLM-L6-v2"  # == prod _DEFAULT_EMBEDDING_MODEL_NAME
DEFAULT_CLUSTER_THRESHOLD = 0.75  # == prod _DEFAULT_CLUSTER_COSINE_THRESHOLD
DEFAULT_WINDOW_HOURS = 48.0
DEFAULT_MULTI_K = 3
MIN_TEXT_LEN = 20  # skip near-empty posts (stickers, single emoji) from clustering


@dataclass
class Post:
    handle: str
    posted_at: datetime
    text: str
    views: int
    forwards: int
    reactions: int


def _eng(views: int, forwards: int, reactions: int) -> float:
    return float(views + forwards * FORWARD_FACTOR + reactions * REACTION_FACTOR)


def load_posts(db: Path) -> list[Post]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT handle, posted_at, text, views, forwards, reactions FROM posts "
        "WHERE text IS NOT NULL AND length(text) >= ? ORDER BY posted_at",
        (MIN_TEXT_LEN,),
    ).fetchall()
    con.close()
    out: list[Post] = []
    for h, ts, text, v, f, r in rows:
        out.append(Post(h, datetime.fromisoformat(ts), text, v or 0, f or 0, r or 0))
    return out


def embed(posts: list[Post]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBED_MODEL)
    vecs = model.encode(
        [p.text for p in posts], batch_size=256, show_progress_bar=True, normalize_embeddings=True
    )
    return np.asarray(vecs, dtype=np.float32)


def cluster(posts: list[Post], vecs: np.ndarray, threshold: float, window_h: float) -> list[list[int]]:
    """Time-windowed greedy cosine clustering. Returns list of clusters (index lists).

    Posts are time-sorted. Each post joins the most-similar ACTIVE cluster (centroid
    cosine >= threshold AND within window_h of that cluster's latest post); else seeds
    a new cluster. Vectors are L2-normalized, so cosine == dot product.
    """
    clusters: list[list[int]] = []
    centroids: list[np.ndarray] = []
    last_ts: list[float] = []
    active: list[int] = []  # indices into clusters that are still within the window
    win_s = window_h * 3600.0

    for i, p in enumerate(posts):
        t = p.posted_at.timestamp()
        active = [c for c in active if t - last_ts[c] <= win_s]
        best, best_sim = -1, threshold
        for c in active:
            sim = float(np.dot(vecs[i], centroids[c]))
            if sim >= best_sim:
                best_sim, best = sim, c
        if best == -1:
            clusters.append([i])
            centroids.append(vecs[i].copy())
            last_ts.append(t)
            active.append(len(clusters) - 1)
        else:
            members = clusters[best]
            centroids[best] = (centroids[best] * len(members) + vecs[i]) / (len(members) + 1)
            n = np.linalg.norm(centroids[best])
            if n > 0:
                centroids[best] /= n
            members.append(i)
            last_ts[best] = t
    return clusters


def score_cluster(posts: list[Post], idxs: list[int], chan_baseline: dict[str, float], watched: int):
    views = sum(posts[i].views for i in idxs)
    forwards = sum(posts[i].forwards for i in idxs)
    reactions = sum(posts[i].reactions for i in idxs)
    chans = {posts[i].handle for i in idxs}
    times = [posts[i].posted_at.timestamp() for i in idxs]
    delta_hours = (max(times) - min(times)) / 3600.0
    # channel_avg = mean per-post engagement baseline across the cluster's channels
    base = np.mean([chan_baseline[h] for h in chans]) if chans else 0.0
    si = ScoreInputs(
        views=views,
        forwards=forwards,
        reactions=reactions,
        channel_avg=float(base),
        delta_channel_count=len(chans),
        delta_hours=delta_hours,
        unique_channels_count=len(chans),
        watched_channels_count=watched,
    )
    comp = compute_components(si)
    return comp, len(chans), delta_hours


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """ROC-AUC via the Mann-Whitney U statistic (no sklearn dependency needed)."""
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ranks for ties
    s_sorted = scores[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    pos = labels == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    auc = (ranks[pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def precision_at_k(labels: np.ndarray, scores: np.ndarray, k: int) -> float:
    if len(scores) == 0:
        return float("nan")
    top = np.argsort(-scores, kind="mergesort")[:k]
    return float(labels[top].mean())


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    def rank(x):
        order = np.argsort(x, kind="mergesort")
        r = np.empty(len(x), dtype=np.float64)
        r[order] = np.arange(len(x))
        return r

    ra, rb = rank(a), rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra**2).sum() * (rb**2).sum())
    return float((ra * rb).sum() / denom) if denom else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--cluster-threshold", type=float, default=DEFAULT_CLUSTER_THRESHOLD)
    ap.add_argument("--window-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    ap.add_argument("--multi-k", type=int, default=DEFAULT_MULTI_K)
    a = ap.parse_args()

    posts = load_posts(Path(a.db))
    if not posts:
        print("no posts with text in corpus — run backfill first", file=sys.stderr)
        return 2
    watched = len({p.handle for p in posts})
    print(f"== CORPUS ==\nposts_with_text={len(posts)} channels={watched} "
          f"span={posts[0].posted_at.date()}..{posts[-1].posted_at.date()}")

    # per-channel engagement baseline (mean per-post engagement numerator)
    by_chan: dict[str, list[float]] = defaultdict(list)
    for p in posts:
        by_chan[p.handle].append(_eng(p.views, p.forwards, p.reactions))
    chan_baseline = {h: float(np.mean(v)) for h, v in by_chan.items()}

    print("embedding…", flush=True)
    vecs = embed(posts)
    print(f"clustering (thr={a.cluster_threshold}, window={a.window_hours}h)…", flush=True)
    clusters = cluster(posts, vecs, a.cluster_threshold, a.window_hours)

    rows = []
    for idxs in clusters:
        comp, nch, dh = score_cluster(posts, idxs, chan_baseline, watched)
        rows.append((idxs, comp, nch, dh))

    sizes = np.array([len(r[0]) for r in rows])
    nchs = np.array([r[2] for r in rows])
    print("\n== CLUSTERING ==")
    print(f"clusters={len(rows)} singletons={(sizes==1).sum()} "
          f"multi_post={(sizes>1).sum()}")
    for k in (2, 3, 5, 8):
        print(f"  clusters with >= {k} distinct channels: {(nchs>=k).sum()}")

    vs = np.array([r[1].viral_score for r in rows])
    vel = np.array([r[1].velocity for r in rows])
    eng = np.array([r[1].engagement for r in rows])
    cc = np.array([r[1].cross_channel for r in rows])
    clamp_floor = float(np.mean(np.isclose(vel, np.log1p(1) / MIN_WINDOW_HOURS, rtol=1e-3)
                                | np.isclose(vel, 0.0)))
    print("\n== SCORE DISTRIBUTION ==")
    for name, arr in [("viral", vs), ("velocity", vel), ("engagement", eng), ("cross_ch", cc)]:
        print(f"  {name:10} min={arr.min():.3f} p50={np.percentile(arr,50):.3f} "
              f"p90={np.percentile(arr,90):.3f} max={arr.max():.3f} mean={arr.mean():.3f}")
    print(f"  velocity at clamp-floor / zero: {clamp_floor*100:.1f}% of clusters")

    # ── meaningfulness: cross-channel corroboration as positive class ─────────
    labels = (nchs >= a.multi_k).astype(int)
    print(f"\n== MEANINGFULNESS (positive = story in >= {a.multi_k} channels; "
          f"n_pos={int(labels.sum())}/{len(labels)}) ==")
    if labels.sum() == 0:
        print("  NO multi-channel clusters at this K — cannot judge. "
              "Need denser channels or longer backfill.")
    else:
        for name, arr in [("viral_score", vs), ("velocity_only", vel),
                          ("engagement_only", eng), ("cross_channel_only", cc),
                          ("size(#posts)", sizes.astype(float))]:
            auc = roc_auc(labels, arr)
            p10 = precision_at_k(labels, arr, 10)
            p50 = precision_at_k(labels, arr, 50)
            print(f"  {name:20} ROC-AUC={auc:.3f}  P@10={p10:.2f}  P@50={p50:.2f}")
        print(f"  Spearman(viral, #channels) = {spearman(vs, nchs.astype(float)):.3f}")
        tot_eng = np.array([sum(_eng(posts[i].views, posts[i].forwards, posts[i].reactions)
                                 for i in r[0]) for r in rows])
        print(f"  Spearman(viral, total_engagement) = {spearman(vs, tot_eng):.3f}")

    # ── eyeball top clusters ─────────────────────────────────────────────────
    print("\n== TOP 12 CLUSTERS BY viral_score ==")
    top = sorted(range(len(rows)), key=lambda i: -vs[i])[:12]
    for rank, i in enumerate(top, 1):
        idxs, comp, nch, dh = rows[i]
        chans = sorted({posts[j].handle for j in idxs})
        snippet = posts[idxs[0]].text.replace("\n", " ")[:90]
        print(f"  #{rank} vs={comp.viral_score:.2f} vel={comp.velocity:.1f} "
              f"eng={comp.engagement:.2f} cc={comp.cross_channel:.3f} | "
              f"{nch}ch {len(idxs)}posts Δ{dh:.1f}h | {','.join(c.lstrip('@') for c in chans[:5])}")
        print(f"       “{snippet}”")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
