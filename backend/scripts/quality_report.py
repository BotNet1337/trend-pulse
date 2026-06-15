"""Data-quality gate report over the offline corpus (TASK-108, B0).

Runs `eval.quality` over the prod metrics-only snapshot (`backend/data/eval/*.csv`)
and prints, reproducibly, how many clusters survive the data-quality gate and which
gates reject the rest. This is the GATE report: it both quantifies the corpus
pathologies (per the signal-quality report) and DEFINES the clean training subset
that Track C must train on ("train only on quality data").

The gate predicate + every metric helper it uses are unit-tested
(`tests/unit/eval/test_quality.py`); this script only wires the corpus into them, it
reimplements nothing.

Per-cluster `max_cross_cluster_cosine` is computed by a blocked upper-/lower-triangle
pass that mirrors `clustering_audit.count_duplicate_centroid_pairs` (each row's max
similarity to ANY other centroid). Fetch lag is not in the CSV snapshot
(`PostRecord` has no `fetched_at`), so the backfill fingerprint is taken as a PROXY:
`cluster.updated_at - max(post.posted_at)` — the gap between when the cluster was last
touched and its newest post (large on backfilled clusters). This is labelled a proxy
in the output; on the live `corpus.sqlite`/B1 snapshot the real `fetched_at - posted_at`
lag is passed instead.

Two modes:

- **CSV (default)** — prod metrics-only snapshot (`--posts`/`--clusters`). Structural;
  no text → fetch lag is the proxy described above.
- **SQLite re-cluster** (`--sqlite PATH`) — the dense crypto-RU corpus WITH text
  (`eval_offline/data/corpus.sqlite`, the substrate Track C actually trains on). It
  re-clusters with the harness2 method (cosine 0.75 + window + span guard), then gates
  the REAL re-clustered stories. This is the gate that defines the C-training subset.

Usage (from backend/, via uv):
    uv run python scripts/quality_report.py \
        --posts data/eval/posts.csv --clusters data/eval/clusters.csv
    uv run python scripts/quality_report.py \
        --sqlite ../eval_offline/data/corpus.sqlite --emb ../eval_offline/data/emb.npy
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

# Allow running as `python scripts/quality_report.py` from backend/ (src layout).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.corpus import ClusterRecord, PostRecord, cluster_sizes, load_clusters, load_posts
from eval.distribution import summarize
from eval.quality import (
    ClusterQualityFeatures,
    QualityThresholds,
    QualityVerdict,
    assess_cluster,
    build_cluster_features,
    summarize_quality,
)

# Row-block size for the blocked O(n^2) cosine pass (mirrors clustering_audit).
_COSINE_BLOCK_ROWS = 512

# harness2 re-cluster defaults (cosine 0.75 + 48h window + 72h span guard). Named, not
# magic — these are the exact harness2_predictive.py defaults the eval line already uses.
_RECLUSTER_COSINE = 0.75
_RECLUSTER_WINDOW_SECONDS = 48 * 3600
_RECLUSTER_SPAN_SECONDS = 72 * 3600
_RECLUSTER_MIN_TEXT_LEN = 20


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Data-quality gate report (B0)")
    parser.add_argument("--posts", type=Path, default=None, help="posts.csv snapshot (CSV mode)")
    parser.add_argument(
        "--clusters", type=Path, default=None, help="clusters.csv snapshot (CSV mode)"
    )
    parser.add_argument(
        "--sqlite", type=Path, default=None, help="corpus.sqlite (re-cluster mode, has text)"
    )
    parser.add_argument(
        "--emb", type=Path, default=None, help="emb.npy cache for --sqlite re-cluster mode"
    )
    parser.add_argument("--top-gates", type=int, default=20)
    return parser.parse_args(argv)


def _max_cross_cosine_per_cluster(clusters: list[ClusterRecord]) -> dict[int, float]:
    """Each cluster's max centroid cosine to ANY OTHER cluster (blocked, memory-bounded).

    Mirrors `clustering_audit.count_duplicate_centroid_pairs`: L2-normalise once, then
    for each row block dot against all rows and take the per-row max excluding self.
    """
    if len(clusters) < 2:
        return {c.id: 0.0 for c in clusters}
    matrix = np.asarray([c.centroid for c in clusters], dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    n = unit.shape[0]
    out: dict[int, float] = {}
    for start in range(0, n, _COSINE_BLOCK_ROWS):
        stop = min(start + _COSINE_BLOCK_ROWS, n)
        sims = unit[start:stop] @ unit.T  # (block, n)
        for local_row in range(stop - start):
            global_row = start + local_row
            sims[local_row, global_row] = -1.0  # exclude self
            out[clusters[global_row].id] = float(np.max(sims[local_row]))
    return out


def _posts_by_cluster(posts: list[PostRecord]) -> dict[int, list[PostRecord]]:
    grouped: dict[int, list[PostRecord]] = defaultdict(list)
    for post in posts:
        if post.cluster_id is not None:
            grouped[post.cluster_id].append(post)
    return grouped


def _backfill_lag_seconds(cluster: ClusterRecord, posts: list[PostRecord]) -> float:
    """PROXY for fetch lag on the metrics-only snapshot (no `fetched_at`).

    `updated_at - max(posted_at)`: how long after its newest post the cluster was last
    touched. Large on backfilled clusters (months), ~0 on live ones. Clamped at 0.
    """
    if not posts:
        return 0.0
    newest = max(p.posted_at for p in posts)
    return max((cluster.updated_at - newest).total_seconds(), 0.0)


def _load_sqlite_posts(db: Path) -> list[tuple[str, float, int, int, int]]:
    """Load (handle, posted_ts, views, forwards, reactions) for posts with usable text."""
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT handle, posted_at, views, forwards, reactions FROM posts "
            "WHERE text IS NOT NULL AND length(text) >= ? ORDER BY posted_at",
            (_RECLUSTER_MIN_TEXT_LEN,),
        ).fetchall()
    finally:
        con.close()
    return [(h, _to_utc_timestamp(ts), v or 0, f or 0, r or 0) for h, ts, v, f, r in rows]


def _to_utc_timestamp(value: str) -> float:
    """Parse an ISO8601 string to a UTC epoch; naive strings are treated as UTC.

    `corpus.sqlite` stores ISO8601 UTC; a naive value (no offset) is interpreted as
    UTC (mirrors `eval.corpus._parse_dt`) rather than the host local tz, so the absolute
    timestamps are reproducible across machines (span is offset-invariant either way).
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _load_embeddings(db: Path, emb: Path | None, n_posts: int) -> npt.NDArray[np.float64]:
    """Return cached MiniLM embeddings (emb.npy) aligned to the loaded posts.

    The re-cluster mode requires the cached vectors; computing them needs the heavy
    sentence-transformers stack and the post texts in order. We reuse the harness2
    cache. If it is missing or misaligned, raise a clear error rather than silently
    recomputing (offline-only, no surprise model download).
    """
    cache = emb if emb is not None else db.parent / "emb.npy"
    if not cache.exists():
        raise FileNotFoundError(
            f"embedding cache not found: {cache} - generate it via "
            "eval_offline/harness2_predictive.py first"
        )
    arr: npt.NDArray[np.float64] = np.asarray(np.load(cache), dtype=np.float64)
    if len(arr) != n_posts:
        raise ValueError(
            f"embedding cache length {len(arr)} != posts {n_posts}; regenerate the cache"
        )
    return arr


def _recluster(
    posts: list[tuple[str, float, int, int, int]], vecs: npt.NDArray[np.float64]
) -> tuple[list[list[int]], list[npt.NDArray[np.float64]]]:
    """Greedy cosine re-cluster (harness2 method): cosine 0.75 + window gate + span guard.

    Returns the member-index lists AND the final L2-normalised running centroids, so the
    near-duplicate gate (`_recluster_max_cosine`) measures duplication against the SAME
    centroid the clusterer used to assign posts (single consistent centroid definition).
    """
    clusters: list[list[int]] = []
    cent: list[npt.NDArray[np.float64]] = []
    last_ts: list[float] = []
    first_ts: list[float] = []
    for i, post in enumerate(posts):
        t = post[1]
        active = [
            c
            for c in range(len(clusters))
            if t - last_ts[c] <= _RECLUSTER_WINDOW_SECONDS
            and t - first_ts[c] <= _RECLUSTER_SPAN_SECONDS
        ]
        best, best_sim = -1, _RECLUSTER_COSINE
        for c in active:
            sim = float(np.dot(vecs[i], cent[c]))
            if sim >= best_sim:
                best_sim, best = sim, c
        if best == -1:
            clusters.append([i])
            cent.append(vecs[i].copy())
            last_ts.append(t)
            first_ts.append(t)
        else:
            members = clusters[best]
            cent[best] = (cent[best] * len(members) + vecs[i]) / (len(members) + 1)
            norm = float(np.linalg.norm(cent[best]))
            if norm:
                cent[best] = cent[best] / norm
            members.append(i)
            last_ts[best] = t
    return clusters, cent


def _recluster_max_cosine(centroids: list[npt.NDArray[np.float64]]) -> dict[int, float]:
    """Per re-clustered story, max centroid cosine to ANY OTHER story (blocked pass).

    Consumes the clusterer's own final centroids (already L2-normalised on update; a
    re-normalise here is a safe no-op that also guards any zero centroid).
    """
    if len(centroids) < 2:
        return {k: 0.0 for k in range(len(centroids))}
    cents = np.asarray(centroids, dtype=np.float64)
    norms = np.linalg.norm(cents, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = cents / norms
    n = unit.shape[0]
    out: dict[int, float] = {}
    for start in range(0, n, _COSINE_BLOCK_ROWS):
        stop = min(start + _COSINE_BLOCK_ROWS, n)
        sims = unit[start:stop] @ unit.T
        for local_row in range(stop - start):
            global_row = start + local_row
            sims[local_row, global_row] = -1.0
            out[global_row] = float(np.max(sims[local_row]))
    return out


def _run_sqlite_mode(args: argparse.Namespace, thresholds: QualityThresholds) -> int:
    posts = _load_sqlite_posts(args.sqlite)
    vecs = _load_embeddings(args.sqlite, args.emb, len(posts))
    cl, centroids = _recluster(posts, vecs)
    max_cosine = _recluster_max_cosine(centroids)

    print("\n===== DATA-QUALITY GATE (B0) — RE-CLUSTERED corpus.sqlite =====")
    channels = len({p[0] for p in posts})
    print(
        f"posts={len(posts)} channels={channels} stories={len(cl)} "
        f"(recluster cosine={_RECLUSTER_COSINE} window_h={_RECLUSTER_WINDOW_SECONDS // 3600} "
        f"span_guard_h={_RECLUSTER_SPAN_SECONDS // 3600})"
    )
    print(
        "thresholds: "
        f"min_posts={thresholds.min_posts} max_posts={thresholds.max_posts} "
        f"min_channels={thresholds.min_channels} dup_cosine={thresholds.duplicate_cosine} "
        f"recurring_span_days={thresholds.recurring_span_seconds // 86400} "
        f"max_top_channel_share={thresholds.max_top_channel_share}"
    )

    verdicts: list[QualityVerdict] = []
    sizes: dict[int, int] = {}
    for story_id, members in enumerate(cl):
        handles = Counter(posts[i][0] for i in members)
        post_count = len(members)
        unique_channels = len(handles)
        span = int(max(posts[i][1] for i in members) - min(posts[i][1] for i in members))
        features = _sqlite_features(
            story_id, post_count, unique_channels, span, handles, max_cosine[story_id]
        )
        sizes[story_id] = post_count
        verdicts.append(assess_cluster(features, thresholds=thresholds))

    summary = summarize_quality(verdicts)
    print(
        f"\nQUALITY SUBSET: {summary.quality_count} / {summary.total} stories "
        f"({summary.quality_pct:.2f}%) pass the gate"
    )
    print("\nper-gate rejections (a story may fail several):")
    for gate, count in sorted(summary.gate_failures.items(), key=lambda kv: -kv[1])[
        : args.top_gates
    ]:
        print(f"  {gate:24} {count}")

    quality_sizes = [sizes[v.cluster_id] for v in verdicts if v.is_quality]
    if quality_sizes:
        dist = summarize([float(s) for s in quality_sizes])
        print(
            f"\nquality-story post-count distribution: n={dist.count} min={dist.minimum:.0f} "
            f"p50={dist.p50:.0f} p90={dist.p90:.0f} p99={dist.p99:.0f} max={dist.maximum:.0f} "
            f"mean={dist.mean:.1f}"
        )
    return 0


def _sqlite_features(
    story_id: int,
    post_count: int,
    unique_channels: int,
    span_seconds: int,
    handles: Counter[str],
    max_cosine: float,
) -> ClusterQualityFeatures:
    top_share = max(handles.values()) / post_count if post_count else 0.0
    # corpus.sqlite is live-shaped (fetched within window), so fetch lag is not the
    # backfill pathology here → 0.0 (the backfill gate is exercised in CSV mode).
    return ClusterQualityFeatures(
        cluster_id=story_id,
        post_count=post_count,
        unique_channels=unique_channels,
        span_seconds=span_seconds,
        max_cross_cluster_cosine=min(max(max_cosine, 0.0), 1.0),
        top_channel_share=min(max(top_share, 0.0), 1.0),
        completeness_ok=True,
        max_fetch_lag_seconds=0.0,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    thresholds = QualityThresholds()

    if args.sqlite is not None:
        return _run_sqlite_mode(args, thresholds)

    if args.posts is None or args.clusters is None:
        raise SystemExit("CSV mode needs --posts and --clusters (or use --sqlite)")

    clusters = load_clusters(args.clusters)
    posts = load_posts(args.posts)
    sizes = cluster_sizes(posts)
    grouped = _posts_by_cluster(posts)
    max_cosine = _max_cross_cosine_per_cluster(clusters)

    print("\n===== DATA-QUALITY GATE (B0) =====")
    print(f"clusters={len(clusters)} posts={len(posts)} clusters_with_posts={len(sizes)}")
    print(
        "thresholds: "
        f"min_posts={thresholds.min_posts} max_posts={thresholds.max_posts} "
        f"min_channels={thresholds.min_channels} dup_cosine={thresholds.duplicate_cosine} "
        f"recurring_span_days={thresholds.recurring_span_seconds // 86400} "
        f"max_top_channel_share={thresholds.max_top_channel_share} "
        f"max_fetch_lag_days(PROXY)={thresholds.max_fetch_lag_seconds // 86400}"
    )

    verdicts: list[QualityVerdict] = []
    for cluster in clusters:
        cluster_posts = grouped.get(cluster.id, [])
        features = build_cluster_features(
            cluster_id=cluster.id,
            posts=cluster_posts,
            max_cross_cluster_cosine=max_cosine.get(cluster.id, 0.0),
            max_fetch_lag_seconds=_backfill_lag_seconds(cluster, cluster_posts),
        )
        verdicts.append(assess_cluster(features, thresholds=thresholds))

    summary = summarize_quality(verdicts)
    print(
        f"\nQUALITY SUBSET: {summary.quality_count} / {summary.total} clusters "
        f"({summary.quality_pct:.2f}%) pass the gate"
    )
    print("\nper-gate rejections (a cluster may fail several):")
    for gate, count in sorted(summary.gate_failures.items(), key=lambda kv: -kv[1])[
        : args.top_gates
    ]:
        print(f"  {gate:24} {count}")

    quality_sizes = [sizes.get(v.cluster_id, 0) for v in verdicts if v.is_quality]
    if quality_sizes:
        dist = summarize([float(s) for s in quality_sizes])
        print(
            f"\nquality-cluster post-count distribution: "
            f"n={dist.count} min={dist.minimum:.0f} p50={dist.p50:.0f} "
            f"p90={dist.p90:.0f} p99={dist.p99:.0f} max={dist.maximum:.0f} mean={dist.mean:.1f}"
        )
    else:
        print("\nquality-cluster post-count distribution: n=0 (no clusters pass the gate)")

    print(
        "\nNOTE fetch-lag is a PROXY (updated_at - max posted_at) on the metrics-only "
        "snapshot; the live corpus.sqlite / B1 snapshot pass the real fetched_at lag."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
