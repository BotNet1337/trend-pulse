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

## B1–C2 — pending (see loop doc for queue)
Not yet started. Next: B1 forward feature-snapshot capture (`cluster_feature_snapshots` Alembic migration + scorer hook).
