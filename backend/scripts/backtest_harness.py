"""Offline accuracy/quality harness CLI over the prod corpus snapshot (TASK-081).

Runs the two measurements the corpus can support and prints a reproducible report:

  1. Scoring replay  — replays the REAL scorer formula (`eval.scoring_replay`,
     reusing `scorer.score.compute_components`) "as if in time" and reports the
     viral-score distribution + threshold crossings + per-topic breakdown.
  2. Clustering audit — size histogram, singleton %, mega buckets, duplicate topics,
     duplicate centroids (cosine >= 0.9) via `eval.clustering_audit`.

Usage (from backend/, via uv):
    uv run python scripts/backtest_harness.py \
        --posts data/eval/posts.csv \
        --clusters data/eval/clusters.csv \
        --score-window-seconds 86400 \
        --watched-channels-count 10

`--watched-channels-count` is an ASSUMPTION (there are no live watchlists in the
corpus) used only for the cross_channel component; the report labels it as such.
Defaults to the prod scorer's `score_window_seconds` (24h) when omitted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/backtest_harness.py` from backend/ (src layout).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.clustering_audit import (
    DUPLICATE_CENTROID_COSINE,
    audit_duplicate_topics,
    audit_sizes,
    count_duplicate_centroid_pairs,
)
from eval.corpus import cluster_sizes, load_clusters, load_posts
from eval.distribution import count_at_or_above, histogram, summarize
from eval.scoring_replay import lead_time_proxy_hours, replay_scores

# Default score window — mirrors config._DEFAULT_SCORE_WINDOW_SECONDS (24h, TASK-079).
_DEFAULT_SCORE_WINDOW_SECONDS = 86_400
# Alert-threshold bars to count crossings for (typical watchlist thresholds).
_THRESHOLD_BARS = (85.0, 90.0)
# Score-distribution histogram edges (viral_score is unbounded above; 0..100+ bins).
_SCORE_EDGES = (0.0, 1.0, 10.0, 50.0, 85.0, 90.0, 100.0)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline scoring + clustering harness")
    parser.add_argument("--posts", type=Path, required=True, help="posts.csv snapshot")
    parser.add_argument("--clusters", type=Path, required=True, help="clusters.csv snapshot")
    parser.add_argument("--score-window-seconds", type=int, default=_DEFAULT_SCORE_WINDOW_SECONDS)
    parser.add_argument(
        "--watched-channels-count",
        type=int,
        default=10,
        help="ASSUMED watched-channel count for cross_channel (no live watchlists in corpus)",
    )
    parser.add_argument("--top-topics", type=int, default=10)
    return parser.parse_args(argv)


def _report_scoring(args: argparse.Namespace) -> None:
    clusters = load_clusters(args.clusters)
    posts = load_posts(args.posts)
    print("\n===== SCORING REPLAY =====")
    print(f"clusters={len(clusters)} posts={len(posts)}")

    scores = replay_scores(
        clusters,
        posts,
        score_window_seconds=args.score_window_seconds,
        watched_channels_count=args.watched_channels_count,
    )
    scored = len(scores)
    skipped = len(clusters) - scored
    print(f"scored_clusters={scored} skipped_no_in_window_posts={skipped}")

    viral = [s.components.viral_score for s in scores]
    summary = summarize(viral)
    print(
        "viral_score: "
        f"n={summary.count} min={summary.minimum:.4f} p50={summary.p50:.4f} "
        f"p90={summary.p90:.4f} p95={summary.p95:.4f} p99={summary.p99:.4f} "
        f"max={summary.maximum:.4f} mean={summary.mean:.4f}"
    )
    counts = histogram(viral, edges=list(_SCORE_EDGES))
    print(f"histogram_edges={_SCORE_EDGES}")
    print(f"histogram_counts={counts}  (last bin = >= {_SCORE_EDGES[-1]})")
    for bar in _THRESHOLD_BARS:
        print(f"clusters_at_or_above_{bar:g}={count_at_or_above(viral, bar)}")

    # component distributions (so the report can explain WHY scores look the way they do)
    for name in ("velocity", "engagement", "cross_channel"):
        comp = [getattr(s.components, name) for s in scores]
        cs = summarize(comp)
        print(
            f"{name}: p50={cs.p50:.4f} p90={cs.p90:.4f} p99={cs.p99:.4f} "
            f"max={cs.maximum:.4f} mean={cs.mean:.4f}"
        )

    # per-topic mean viral score (top N by mean), helps see which topics score high
    by_topic: dict[str, list[float]] = {}
    for s in scores:
        by_topic.setdefault(s.topic, []).append(s.components.viral_score)
    ranked = sorted(by_topic.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)[
        : args.top_topics
    ]
    print(f"\ntop_{args.top_topics}_topics_by_mean_viral_score:")
    for topic, vals in ranked:
        mean = sum(vals) / len(vals)
        print(f"  mean={mean:.3f} n={len(vals)} topic={topic[:70]!r}")

    proxy = lead_time_proxy_hours(posts)
    if proxy is not None:
        print(f"\nmedian_lead_time_PROXY_hours={proxy:.3f} (first->peak-engagement spread, PROXY)")
    else:
        print("\nmedian_lead_time_PROXY_hours=N/A (no multi-post clusters)")


def _report_clustering(args: argparse.Namespace) -> None:
    clusters = load_clusters(args.clusters)
    posts = load_posts(args.posts)
    print("\n===== CLUSTERING STRUCTURE AUDIT =====")

    sizes = cluster_sizes(posts)
    size_audit = audit_sizes(sizes, total_clusters=len(clusters), top_n=5)
    print(
        f"total_clusters={size_audit.total_clusters} "
        f"clusters_with_posts={size_audit.clusters_with_posts} "
        f"empty_clusters={size_audit.total_clusters - size_audit.clusters_with_posts}"
    )
    print(
        f"singletons={size_audit.singleton_count} "
        f"({size_audit.singleton_pct:.2f}% of total_clusters)"
    )
    print(f"top_mega_buckets={size_audit.top_sizes}")
    print(f"size_histogram_edges={size_audit.histogram_edges}")
    print(f"size_histogram_counts={size_audit.histogram_counts}")

    topic_audit = audit_duplicate_topics(clusters)
    print(
        f"distinct_topics={topic_audit.distinct_topics} "
        f"duplicate_topic_groups={topic_audit.duplicate_topic_groups} "
        f"clusters_in_duplicate_topics={topic_audit.clusters_in_duplicate_topics} "
        f"({topic_audit.clusters_in_duplicate_topics / topic_audit.total_clusters * 100:.1f}%)"
    )

    centroids = [c.centroid for c in clusters]
    dup_pairs = count_duplicate_centroid_pairs(
        centroids, cosine_threshold=DUPLICATE_CENTROID_COSINE
    )
    print(f"duplicate_centroid_pairs(cosine>={DUPLICATE_CENTROID_COSINE})={dup_pairs}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    _report_scoring(args)
    _report_clustering(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
