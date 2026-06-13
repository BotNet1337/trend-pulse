# TrendPulse — Signal Quality Report

## Baseline (T9 / TASK-081) — Offline accuracy harness, 2026-06-13

Reproducible, offline accuracy/quality measurement of the production corpus, built
because there are **no live users** (0 alerts delivered, 0 feedback rows) — accuracy
must be measured offline against the existing corpus.

Harness: `backend/src/eval/` (pure metric helpers, unit-tested) + runnable CLI
`backend/scripts/backtest_harness.py`. Snapshot exporter:
`backend/scripts/export_corpus.sh` (read-only `\copy SELECT`).

### Corpus snapshot (read-only export from prod, 2026-06-13)

Exported read-only from `deploy@167.233.81.243` (prod swarm, container
`trendpulse_postgres`) via `\copy (SELECT …) TO STDOUT` — never mutates the DB.

| Table | Rows | Fields exported |
|---|---|---|
| `posts` | 57,940 | `id, posted_at, channel_id, user_id, cluster_id, views, forwards, reactions` |
| `clusters` | 9,404 | `id, user_id, first_seen, updated_at, topic, embedding` (384-d centroid) |

Verified on prod before export:
- `posts.text IS NULL` for **all 57,940** rows (retention purged raw text — ADR-002 §4).
- `posts.embedding IS NULL` for **all 57,940** rows (post-level vectors never persisted).
- `clusters.embedding IS NOT NULL` for **all 9,404** rows (centroids available).
- 2 distinct `user_id` in both tables (the two seed/test tenants).
- 0 orphan posts (`cluster_id IS NULL`); every post's `cluster_id` resolves to a cluster.

NO text is exported → no PII/compliance concern (it is NULL anyway). Full CSVs are
gitignored (`backend/data/eval/.gitignore`; `clusters.csv` ≈ 47 MB); a small committed
sample (`posts.sample.csv`, `clusters.sample.csv`) keeps the harness runnable in CI/dev.
Regenerate the full snapshot with:

```bash
PROD_HOST=deploy@167.233.81.243 SSH_KEY=~/.ssh/id_ed25519 \
  OUT_DIR=backend/data/eval bash backend/scripts/export_corpus.sh
```

### What is NOT measurable on this corpus (and why)

- **Clustering ACCURACY** — cannot be judged: the source `posts.text` and per-post
  `posts.embedding` are gone, so we cannot replay embedding/clustering or compute a
  homogeneity/ARI against ground truth. We can only audit cluster **structure**
  (sizes / duplicates), not whether the grouping was semantically *correct*.
- **Embedding quality / re-clustering** — impossible offline (no vectors per post).
- **True detection lead time** — no external "mainstream date" labels exist in the
  corpus; only an intra-corpus PROXY is computed (and labelled as such).
- **Engagement baseline (`channel_avg`)** — the live value is a per-channel 7-day
  historical AVG that excludes the scored cluster and depends on the wall clock; it
  is not faithfully reconstructable from a static export. The replay uses the
  documented **cold-channel fallback** (`channel_avg = sum(views)/len(posts)`,
  `scorer.tasks._build_score_inputs`) → engagement is a **PROXY**.
- **`cross_channel`** — there are no live watchlists in the corpus, so
  `watched_channels_count` is an **assumption** (default 10 in the run below).

All of the above require a **forward text-capture experiment** — tracked as **T11**.

---

### 1. Scoring replay ("as-if-in-time")

Method: `eval.scoring_replay.replay_scores` reuses the REAL formula
(`scorer.score.compute_components` / `ScoreInputs`) — it does NOT reimplement it. It
reconstructs `ScoreInputs` with the exact rules of `scorer.tasks._build_score_inputs`:
per-cluster posts bounded to a rolling window (`posted_at >= anchor −
score_window_seconds`, TASK-079, default 24h = 86400s), summed views/forwards/
reactions, `delta_hours = (latest−earliest)/3600`, `delta_channel_count =
unique_channels_count = #distinct channels in-window`. The **anchor** is each
cluster's own `updated_at` (the instant the live scorer last touched it). A cluster
with no in-window posts is **skipped** (mirrors production `return None → continue`).

Run: `score_window_seconds=86400`, `watched_channels_count=10` (assumed).

| Metric | Value |
|---|---|
| Clusters total | 9,404 |
| **Clusters that produce a score** | **30** |
| Clusters skipped (no posts in window) | 9,374 |
| `viral_score` min / p50 / p90 / p95 / p99 / max | 0.762 / 17.026 / 17.037 / 17.039 / 17.056 / 17.063 |
| `viral_score` mean | 14.94 |
| Histogram (edges `0,1,10,50,85,90,100`) | `[1, 3, 26, 0, 0, 0, 0]` |
| **Clusters ≥ threshold 85** | **0** |
| **Clusters ≥ threshold 90** | **0** |
| velocity p50 / p99 / max / mean | 41.589 / 41.589 / 41.589 / 36.06 |
| engagement (PROXY) p50 / p99 / max / mean | 1.058 / 4.124 / 4.127 / 1.39 |
| cross_channel (assumed watched=10) p50 / max / mean | 0.100 / 0.200 / 0.103 |
| median lead-time **PROXY** (first→peak-engagement spread) | 6,257.6 h (≈ 261 days) |

**Key findings:**

- On the current corpus the production scorer would emit a score for only **30 of
  9,404 clusters**, and **ZERO would cross the typical 85/90 alert bar** — consistent
  with the 0-alerts reality. The scores cluster tightly around ~17 (the `0–10..50` bin
  holds 26 of 30), dominated by the velocity component (≈ `41.6 × 0.4 ≈ 16.6`),
  because the in-window slices are tiny (few channels in a short span → high
  `log1p(Δchannels)/Δhours`). The engagement contribution is ~`1.4 × 0.35 ≈ 0.49`
  and cross_channel ~`0.10 × 0.25 ≈ 0.025`.
- The 9,374 skips and the 6,257 h lead-time proxy are the **historical-backfill
  fingerprint**: a cluster's `updated_at` is months after most of its posts'
  `posted_at`, so almost nothing falls inside the 24h rolling window. TASK-078/079
  stopped the backfill and bounded the window, but the *existing* corpus is still
  backfill-shaped — which is exactly why offline scoring on it is near-empty.
- The lead-time number (≈ 261 days) is an **intra-corpus PROXY** (first→peak
  engagement spread), NOT a mainstream-vs-detection lead time; on backfilled data it
  measures the corpus' total time span, not real reaction speed. Do not quote it as
  product lead time.

### 2. Clustering-structure audit

Method: `eval.clustering_audit`. Sizes from post counts per `cluster_id`
(`eval.corpus.cluster_sizes`); duplicate topics by exact topic-string match;
duplicate centroids by blocked cosine over the 9,404 × 384 centroid matrix
(numpy, upper-triangle, threshold ≥ 0.9).

| Metric | Value | Known baseline | Match |
|---|---|---|---|
| Total clusters | 9,404 | 9,404 | ✅ |
| Clusters with ≥1 post | 8,357 (1,047 empty) | — | — |
| **Singletons** | **6,368 (67.7% of total)** | 6,368 / 9,404 (68%) | ✅ |
| **Top mega-buckets** | **4,102 / 1,713 / 1,210** (then 1,179 / 1,139) | 4,102 / 1,713 / 1,210 | ✅ |
| Size histogram (edges `1,2,3,6,11,51,501`) | `[6368, 719, 587, 231, 292, 140, 20]` | — | — |
| **Distinct topics** | **7,147** | 7,147 | ✅ |
| **Duplicate-topic groups** | **753** | 753 | ✅ |
| **Clusters in duplicate topics** | **3,010 (32.0%)** | 3,010 (32%) | ✅ |
| **Duplicate-centroid pairs (cosine ≥ 0.9)** | **5,122** | (new) | — |

**Key findings:**

- The known structural baseline **reproduces exactly** (singletons, mega-buckets,
  duplicate topics, distinct topics) — the harness is trustworthy.
- **68% singletons + three mega-buckets (4,102 / 1,713 / 1,210) is a bimodal,
  unhealthy clustering distribution**: most stories never group, while a few buckets
  swallow thousands of posts (likely catch-all/low-information centroids). The
  size histogram confirms it: 6,368 of 8,357 clusters-with-posts are singletons;
  only 20 clusters exceed 500 posts.
- **5,122 centroid pairs are near-duplicates (cosine ≥ 0.9)** and **3,010 clusters
  (32%) share an identical topic string** — strong evidence the clusterer is
  **over-splitting** the same story into many clusters. This is a quality smell, but
  whether merging them is *correct* needs the original text (T11) — structure alone
  cannot prove it.

### Caveats summary

1. Scoring engagement & cross_channel are **PROXIES** (cold-channel fallback +
   assumed watched-channel count), not the live values.
2. Lead-time is an **intra-corpus PROXY**, not real detection lead time.
3. Clustering **accuracy is not measurable** — only structure. Semantic correctness
   of clusters/duplicates requires forward text capture (**T11**).
4. Numbers are anchored to a **2026-06-13 read-only snapshot**; the corpus is
   backfill-shaped, so offline scoring is near-empty by construction.

### How to reproduce

```bash
# 1. read-only export from prod
PROD_HOST=deploy@167.233.81.243 SSH_KEY=~/.ssh/id_ed25519 \
  OUT_DIR=backend/data/eval bash backend/scripts/export_corpus.sh
# 2. run the harness (dummy secrets satisfy Settings; no DB connection happens)
cd backend && JWT_SECRET=dump OAUTH_STATE_SECRET=dump \
  GOOGLE_CLIENT_ID=dump GOOGLE_CLIENT_SECRET=dump \
  uv run python scripts/backtest_harness.py \
    --posts data/eval/posts.csv --clusters data/eval/clusters.csv \
    --score-window-seconds 86400 --watched-channels-count 10
```
