# Track B (data) → C (ML) — results & numbers

Worktree `apps/trendPulse-data` (branch `track-b-data`, off `origin/main` @ `6f576fb`). Offline-only.

---

## B0 — Data-quality gate (TASK-108)

**What it is.** A reusable, unit-tested gate (`backend/src/eval/quality.py`) that scores corpus clusters on EARLY/STRUCTURAL (leak-free) features and defines the clean training subset. Track C training (C1) and the forward-time-split harness (B2) MUST pass clusters through `is_quality_cluster()`. Eight named gates (tunable `QualityThresholds`, no magic literals):

| Gate | Rejects | Default |
|---|---|---|
| `too_small` | singletons / near-singletons (68% of corpus) | post_count < 3 |
| `mega_bucket` | catch-all centroids | post_count > 1000 |
| `single_channel` | no cross-channel spread (the product's target signal; leakage-prone) | unique_channels < 2 |
| `near_duplicate` | over-split same story | max cross-cluster cosine ≥ 0.9 |
| `recurring_boilerplate` | daily-market / "Доброе утро" chains | span > 14d AND channels ≤ 3 |
| `co_channel_dominated` | self-amplified / coordinated (one channel dominates) | top-channel post-share > 0.9 |
| `incomplete` | missing required fields | completeness flag |
| `temporally_insane` | backfill fingerprint | fetch lag > 7d |

Substrate-agnostic: `ClusterQualityFeatures` is a frozen, runtime-validated record both the prod CSV snapshot and the re-clustered `corpus.sqlite` stories project into.

**Results — RE-CLUSTERED `corpus.sqlite` (the real C-training substrate, 49,157 posts w/ text, 28 channels).**
Re-clustered with the harness2 method (cosine 0.75 + 48h window + 72h span guard) → **18,971 stories**.

```
QUALITY SUBSET: 315 / 18,971 stories (1.66%) pass the gate
per-gate rejections (a story may fail several):
  single_channel        17,309   ← dominant pathology (single-channel-heavy corpus, confirmed)
  too_small             16,800   ← singletons/pairs
  near_duplicate         3,949   ← over-split stories (cosine ≥ 0.9, vs clusterer's own centroid)
  co_channel_dominated      20
quality-story post-count distribution: n=315 min=3 p50=3 p90=6 p99=10 max=13 mean=3.9
```

**Finding (concrete, honest).** Only **~1.7% (315 stories)** of the corpus is genuine multi-channel, non-duplicate, non-boilerplate spreading content worth training on. The two killers are `single_channel` (17,309) and `too_small` (16,800) — quantitatively confirming the signal-quality report's "single-channel-heavy, 68% singletons" diagnosis on the ACTUAL re-clustered substrate (not just the prod cluster table). The 319 quality stories are small (median 3 posts, max 13) — a real but **thin** clean subset. **Implication for Track C:** the GBDT will train on a small N; this is the data-ceiling the transformation plan flagged ("real quality lifts only with genuine multi-channel live data") — B1 forward-capture is what grows this subset over time. The gate is the prerequisite that prevents C1 from learning singleton/boilerplate artefacts.

**CSV snapshot mode** (prod metrics-only, no text → fetch-lag is a proxy `updated_at − max(posted_at)`): runs offline over `backend/data/eval/*.csv`. On the committed sample (20 clusters) → 0 pass (all single-channel/too-small), as expected. The full prod snapshot (`posts.csv`/`clusters.csv`, gitignored ~47MB) is not present in this worktree; regenerate via `backend/scripts/export_corpus.sh` to run the full-corpus CSV pass.

**Reproduce.**
```bash
cd backend
# real C-training substrate (re-cluster):
uv run python scripts/quality_report.py \
  --sqlite ../../trendPulse/eval_offline/data/corpus.sqlite \
  --emb    ../../trendPulse/eval_offline/data/emb.npy
# prod metrics-only snapshot (structural):
uv run python scripts/quality_report.py \
  --posts data/eval/posts.csv --clusters data/eval/clusters.csv
```

**Tests / checks.** 21 new unit tests (`tests/unit/eval/test_quality.py`), full eval suite 101 passed, full backend unit suite **1001 passed**, `ruff format/check` + `mypy --strict` (182 files) green. No `Any`, no `# type: ignore`. PR: _pending_.

---

## B1 — Forward feature-snapshot capture (TASK-109)

**What.** New `cluster_feature_snapshots` table (Alembic migration 0023) + a hook in the 5-min scorer tick (`scorer.tasks._capture_feature_snapshots`) that, for EVERY fresh cluster, writes a **metrics-only** snapshot at fixed early observation windows (15m/30m/1h after `first_seen`): cumulative-over-`[first_seen, now]` views/forwards/reactions, post_count, distinct_channels, breadth_velocity (channels/hr), age_seconds. Idempotent (`UNIQUE(user_id,cluster_id,window_label)` + ON CONFLICT DO NOTHING). NO raw text (compliance: text purged at 48h). The future label is NOT stored — it is a B2 join (leak-free).

This is the lever that grows the thin quality subset B0 revealed: TrendPulse builds its OWN forward-labeled dataset from the live stream going forward (self-supervised), instead of being capped by the backfill-shaped historical corpus.

**Design highlights.**
- Pure logic (`scorer/feature_snapshots.py`) is DB-free + unit-tested (window-due crossing, breadth-velocity clamp, aggregation, validation).
- The snapshot write is SAVEPOINT-isolated + try/except-guarded → a capture failure can NEVER abort the user's score/alert transaction (data capture is best-effort; alerts are revenue-critical).
- KNOWN LIMITATION (documented + tested): capture is coupled to scoring freshness (`scorer_recent_window_seconds`, default 1h). A cluster that goes quiet before ~1h ages out of the freshness window before its `1h` snapshot is written → the `1h` feature is missing-not-at-random for short-lived stories. B2 must treat a missing window as missing (not impute). The 15m/30m windows are reliably captured for active clusters.

**Verification (real pgvector:pg16).** 12 unit + 5 integration (crossed-windows-only, backfill+idempotent, young→none, stale-freshness→none, per-user isolation) + 3 migration (upgrade head, 0023 up/down round-trip). Full backend unit suite **1019 passed**; ruff + mypy --strict (184 files) clean; no `Any`/`# type: ignore`. Adversarial code + database reviews (opus, fresh ctx) PASS; all HIGH/MEDIUM findings folded into the PR. PR: _pending_.

## B2–C2 — pending (see loop doc for queue)
Next: B2 forward-time-split harness (Cheng "doubling" label) — features from `[birth, T_obs]` only (the B1 snapshots become the live feature source), chronological train/val/test split with a gap, PR-AUC/ROC-AUC vs observation window.
