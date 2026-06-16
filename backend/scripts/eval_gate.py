"""Online eval-gate runner — read-only quality of v2 on the live TG B1 stream (TASK-122).

Thin DB-facing wrapper around the pure `eval.online_gate` module: opens a read-only
session, SELECTs the B1 feature snapshots + each cluster's eventual cumulative weighted
engagement + the cluster birth time + alert 👍/👎 feedback, feeds them into the pure
gate per observation window, and writes a JSON report (+ a stdout summary). It makes NO
writes — only SELECTs — and reimplements nothing (the formula stays `scorer/score.py`,
the metrics `eval/metrics.py`, the leak-free split/label `eval/forward_split.py`).

Usage (from backend/, via uv):
    uv run --directory backend python scripts/eval_gate.py --out report.json
    uv run --directory backend python scripts/eval_gate.py \
        --out report.json --watched-channels 1 \
        --split-gap-seconds 3600 --cohort-bucket-seconds 3600
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python scripts/eval_gate.py` from backend/ (src layout).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eval.online_gate import (
    DEFAULT_WATCHED_CHANNELS_COUNT,
    GateReport,
    OnlineEvalConfig,
    ScoredOutcome,
    SnapshotRow,
    WindowReport,
    alert_precision,
    compute_window_report,
    snapshot_to_score_inputs,
)
from scorer.score import (
    FORWARD_FACTOR,
    REACTION_FACTOR,
    compute_components,
)
from storage.database import get_session
from storage.models.alert_feedback import AlertFeedback
from storage.models.alerts import Alert
from storage.models.cluster_feature_snapshots import ClusterFeatureSnapshot
from storage.models.clusters import Cluster
from storage.models.posts import Post

# The v2 Brier is the UNCALIBRATED baseline (score÷100 as a pseudo-probability), flagged
# in the report so it is never mistaken for a calibrated probability (S0/D5).
_BRIER_CAVEAT = "uncalibrated baseline (v2 ranking score ÷ 100, not a calibrated probability)"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Online eval-gate (S0, TASK-122)")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    parser.add_argument(
        "--watched-channels",
        type=int,
        default=DEFAULT_WATCHED_CHANNELS_COUNT,
        help="cross-channel denominator assumption (no live watchlist offline)",
    )
    parser.add_argument(
        "--split-gap-seconds",
        type=int,
        default=0,
        help="forward-split boundary no-overlap guard (seconds)",
    )
    parser.add_argument(
        "--cohort-bucket-seconds",
        type=int,
        default=0,
        help="comparable-age cohort width for the DOUBLING median (0 = single cohort)",
    )
    return parser.parse_args(argv)


def _epoch(value: datetime) -> float:
    """UTC epoch seconds of a (tz-aware) timestamp — the split's birth-time key."""
    return value.timestamp()


def _load_snapshots(session: Session, windows: tuple[str, ...]) -> list[SnapshotRow]:
    """Read the B1 early feature snapshots for the configured windows (read-only)."""
    rows = session.execute(
        select(
            ClusterFeatureSnapshot.cluster_id,
            ClusterFeatureSnapshot.user_id,
            ClusterFeatureSnapshot.window_label,
            ClusterFeatureSnapshot.age_seconds,
            ClusterFeatureSnapshot.post_count,
            ClusterFeatureSnapshot.views,
            ClusterFeatureSnapshot.forwards,
            ClusterFeatureSnapshot.reactions,
            ClusterFeatureSnapshot.distinct_channels,
        ).where(ClusterFeatureSnapshot.window_label.in_(windows))
    ).all()
    return [
        SnapshotRow(
            cluster_id=row.cluster_id,
            user_id=row.user_id,
            window_label=row.window_label,
            age_seconds=row.age_seconds,
            post_count=row.post_count,
            views=row.views,
            forwards=row.forwards,
            reactions=row.reactions,
            distinct_channels=row.distinct_channels,
        )
        for row in rows
    ]


def _load_cluster_engagement(session: Session) -> dict[int, float]:
    """Per-cluster cumulative weighted engagement (views + forwards·F + reactions·R).

    Computed in SQL with the SAME weights as `scorer.score.engagement_numerator`
    (F=FORWARD_FACTOR, R=REACTION_FACTOR), summed over ALL of the cluster's posts —
    the eventual outcome, strictly later than the early window (leak-free). Read-only.
    """
    weighted = (
        func.coalesce(func.sum(Post.views), 0)
        + func.coalesce(func.sum(Post.forwards), 0) * FORWARD_FACTOR
        + func.coalesce(func.sum(Post.reactions), 0) * REACTION_FACTOR
    )
    rows = session.execute(
        select(Post.cluster_id, weighted)
        .where(Post.cluster_id.is_not(None))
        .group_by(Post.cluster_id)
    ).all()
    return {row[0]: float(row[1]) for row in rows}


def _load_cluster_birth_and_age(session: Session) -> dict[int, tuple[float, int]]:
    """Per-cluster (first_seen epoch, age-at-outcome seconds) — the label-time keys.

    ``age_at_outcome = updated_at - first_seen`` (the cohort key for the comparable-age
    DOUBLING median). Read-only.
    """
    rows = session.execute(select(Cluster.id, Cluster.first_seen, Cluster.updated_at)).all()
    out: dict[int, tuple[float, int]] = {}
    for cluster_id, first_seen, updated_at in rows:
        age = max(int((updated_at - first_seen).total_seconds()), 0)
        out[cluster_id] = (_epoch(first_seen), age)
    return out


def _load_alert_verdicts(session: Session) -> list[int]:
    """All alert 👍/👎 verdicts joined through their alert (read-only)."""
    rows = session.execute(
        select(AlertFeedback.verdict).join(Alert, AlertFeedback.alert_id == Alert.id)
    ).all()
    return [int(row[0]) for row in rows]


def _build_scored_for_window(
    window: str,
    snapshots: list[SnapshotRow],
    engagement: dict[int, float],
    birth_age: dict[int, tuple[float, int]],
    *,
    watched_channels_count: int,
) -> list[ScoredOutcome]:
    """Pair each window snapshot with its early score + eventual engagement outcome.

    A snapshot is dropped only when its cluster has no birth row (cannot be split) — its
    eventual engagement defaults to 0.0 when the cluster has no posts (a real, non-leaky
    zero outcome). The early score is the REAL `compute_components` over the projected
    `ScoreInputs` — the formula is never reimplemented here.
    """
    scored: list[ScoredOutcome] = []
    for snapshot in snapshots:
        if snapshot.window_label != window:
            continue
        birth = birth_age.get(snapshot.cluster_id)
        if birth is None:
            continue
        first_seen_epoch, age_at_outcome_seconds = birth
        inputs = snapshot_to_score_inputs(snapshot, watched_channels_count=watched_channels_count)
        early_score = compute_components(inputs).viral_score
        scored.append(
            ScoredOutcome(
                cluster_id=snapshot.cluster_id,
                first_seen_epoch=first_seen_epoch,
                early_score=early_score,
                final_engagement=engagement.get(snapshot.cluster_id, 0.0),
                age_at_outcome_seconds=age_at_outcome_seconds,
            )
        )
    return scored


def run_gate(session: Session, config: OnlineEvalConfig) -> GateReport:
    """Assemble the read-only inputs and run the pure gate per window."""
    snapshots = _load_snapshots(session, config.windows)
    engagement = _load_cluster_engagement(session)
    birth_age = _load_cluster_birth_and_age(session)
    verdicts = _load_alert_verdicts(session)

    window_reports: list[WindowReport] = []
    for window in config.windows:
        scored = _build_scored_for_window(
            window,
            snapshots,
            engagement,
            birth_age,
            watched_channels_count=config.watched_channels_count,
        )
        window_reports.append(compute_window_report(window, scored, config=config))

    precision, feedback_n = alert_precision(verdicts)
    return GateReport(
        windows=tuple(window_reports),
        alert_precision=precision,
        alert_feedback_n=feedback_n,
    )


def _report_to_dict(report: GateReport, config: OnlineEvalConfig) -> dict[str, object]:
    """Serialise the gate report into a plain, JSON-safe dict with honest caveats."""
    return {
        "config": {
            "watched_channels_count": config.watched_channels_count,
            "train_fraction": config.train_fraction,
            "val_fraction": config.val_fraction,
            "test_fraction": config.test_fraction,
            "split_gap_seconds": config.split_gap_seconds,
            "cohort_bucket_seconds": config.cohort_bucket_seconds,
            "windows": list(config.windows),
        },
        "brier_caveat": _BRIER_CAVEAT,
        "windows": [
            {
                "window": w.window,
                "n": w.n,
                "n_pos": w.n_pos,
                "pr_auc": w.pr_auc,
                "roc_auc": w.roc_auc,
                "brier": w.brier,
                "skipped": w.skipped,
            }
            for w in report.windows
        ],
        "alert_precision": report.alert_precision,
        "alert_feedback_n": report.alert_feedback_n,
    }


def _print_summary(report: GateReport) -> None:
    print("\n===== ONLINE EVAL-GATE (S0, TASK-122) — v2 on TG B1 =====")
    print(f"Brier note: {_BRIER_CAVEAT}")
    for w in report.windows:
        if w.skipped is not None:
            print(f"  {w.window:4} n={w.n:<5} n_pos={w.n_pos:<5} SKIPPED: {w.skipped}")
            continue
        print(
            f"  {w.window:4} n={w.n:<5} n_pos={w.n_pos:<5} "
            f"pr_auc={_fmt(w.pr_auc)} roc_auc={_fmt(w.roc_auc)} brier={_fmt(w.brier)}"
        )
    if report.alert_precision is None:
        print(f"  alert_precision: n/a (feedback n={report.alert_feedback_n})")
    else:
        print(f"  alert_precision={report.alert_precision:.4f} (n={report.alert_feedback_n})")


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = OnlineEvalConfig(
        watched_channels_count=args.watched_channels,
        split_gap_seconds=args.split_gap_seconds,
        cohort_bucket_seconds=args.cohort_bucket_seconds,
    )
    with get_session() as session:
        report = run_gate(session, config)

    _print_summary(report)
    if args.out is not None:
        args.out.write_text(
            json.dumps(_report_to_dict(report, config), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
