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

---

## Score meaningfulness (T14 / TASK-085) — is the viral_score VALUABLE, 2026-06-13

The owner asked for assurance that `viral_score` is SENSIBLE — that a high score
genuinely means "this is spreading / worth an alert" and a low score means "noise" —
not just that numbers appear. This section answers that with concrete ranking metrics
over two labeled sets. Every number below was produced by **actually running**
`backend/scripts/meaningfulness_eval.py`; the pure metric helpers
(`backend/src/eval/metrics.py`: ROC-AUC, precision@k, Spearman, separation, confusion)
are unit-tested (`backend/tests/unit/eval/test_metrics.py`). The score formula is
**imported and reused** (`scorer.score.compute_components`), never reimplemented.

Reproduce:

```bash
cd backend && JWT_SECRET=dump OAUTH_STATE_SECRET=dump \
  GOOGLE_CLIENT_ID=dump GOOGLE_CLIENT_SECRET=dump \
  uv run python scripts/meaningfulness_eval.py \
    --real-judged data/eval/real_judged.sample.csv
```

### Verdict (plainly)

**The formula is meaningful BY CONSTRUCTION — but it is NOT yet demonstrably
meaningful on the current prod corpus.**

- On controlled scenarios where real virality exists (multi-channel, fast, high
  engagement) the score discriminates **perfectly**: ROC-AUC = **1.000**, viral-vs-
  noise mean margin ≈ **21.4**, Spearman vs an ordinal severity judgement = **0.976**.
- On a human-judged sample of **35 real prod clusters** the score **fails to
  discriminate**: ROC-AUC = **0.564** (barely above a coin flip), Spearman = **0.013**
  (no rank correlation), and the viral class' **mean is BELOW** the noise class'
  (mean margin **−4.57**). precision@1 = 0.00, precision@3 = 0.33.

The gap is not a contradiction — it is a **diagnosed defect of the velocity term on
this corpus' shape**, see "Why real ≠ synthetic" below. The score *responds correctly*
to virality (layer 1 monotonicity tests all pass; synthetic AUC is perfect), so the
weighting/intent is sound; but on the existing **backfill-shaped, single-channel**
corpus the dominant `velocity = log1p(Δchannels)/Δhours` term is **degenerate** and
actually **inverts** the ranking. Until live multi-channel data accrues (or the
zero-width-window velocity clamp is revisited — a SCORER change, out of scope here),
the score cannot be claimed valuable *on real data* from these numbers.

### Layer 1 — Monotonicity / property tests (deterministic, no labels)

`backend/tests/unit/eval/test_monotonicity.py` (all pass) asserts, against the REAL
`compute_components`, that each driver moves the score the correct way:

| Property | Asserted | Result |
|---|---|---|
| more distinct channels → higher velocity | parametrized 1→2…15→50 | ✅ |
| faster spread (smaller Δhours) → higher velocity | parametrized 0.5h…24h | ✅ |
| engagement numerator > channel_avg → engagement > 1 (and rising) | ✅ | ✅ |
| broader unique/watched coverage → higher cross_channel | parametrized | ✅ |
| composite viral_score monotonic non-decreasing in each component | velocity/eng/cross | ✅ |
| weights sum to 1.0 (convex combination) | 0.4 + 0.35 + 0.25 | ✅ |
| all-drivers-viral input outranks all-drivers-noise input | end-to-end | ✅ |

**Finding:** the formula is, by construction, correctly *shaped* — it rewards
virality in every driver. This is the necessary condition for "meaningful".

### Layer 2 — Discrimination (viral vs noise)

#### (a) Synthetic controlled scenarios (`eval.scenarios.synthetic_scenarios`)

8 hand-built cases, channel_avg=1000, watched=20; intended labels (1=viral / 0=noise)
and an ordinal severity. Scores (descending), produced by the real scorer:

| score | label | ord | scenario |
|---:|:---:|:---:|---|
| 39.91 | 1 | 5 | breaking_news_15ch_20min_high_engagement |
| 20.24 | 1 | 4 | fast_spread_10ch_30min_strong_engagement |
| 5.50 | 1 | 3 | moderate_spread_6ch_2h_aboveavg_engagement |
| 1.35 | 0 | 2 | borderline_3ch_6h_avg_engagement |
| 0.65 | 0 | 1 | borderline_2ch_8h_slightly_belowavg |
| 0.38 | 0 | 0 | noise_single_channel_normal_engagement |
| 0.10 | 0 | 0 | noise_single_channel_belowavg_slow |
| 0.03 | 0 | 0 | noise_dead_post_no_engagement |

| Metric | Value | How computed |
|---|---|---|
| **ROC-AUC** (score vs binary) | **1.0000** | Mann–Whitney rank-sum (`eval.metrics.roc_auc`) |
| **separation** mean (viral/noise) | 21.887 / 0.500 → **margin 21.387** | `eval.metrics.separation` |
| separation median (viral/noise) | 20.243 / 0.375 → margin 19.868 | — |
| **precision@1 / @3 / @5** | **1.00 / 1.00 / 0.60** | top-k by score (`precision_at_k`); only 3 of 8 are viral so @5 is capped at 3/5 |
| **Spearman** (score vs ordinal) | **0.9759** | tie-averaged-rank Pearson (`spearman_rho`) |

**Finding:** when genuine virality is present, the score **separates viral from noise
with a perfect AUC and a ~21-point margin**, and its ordering matches the severity
judgement (ρ≈0.98). This is direct evidence the score is meaningful *as designed*.

#### (b) Real prod clusters, human-judged (`backend/data/eval/real_judged.sample.csv`)

Exported read-only from prod (`deploy@167.233.81.243`, container
`trendpulse_postgres`, `\copy SELECT` only — see `scripts/export_real_judged.sh`):
one row per **scoreable** cluster (≥1 post in the 24h window before its `updated_at`
anchor — same window as `scorer.tasks._build_score_inputs`). **35 clusters** qualified
(consistent with the ~30 from the T9 baseline). I (the agent) labeled each from the
`topic` text + metrics: **1 = real signal worth an alert, 0 = noise/borderline**, plus
an ordinal severity. The labels + a `judge_note` rationale are committed in the
fixture for reproducibility. `channel_avg` uses the cold-channel fallback
(`views/posts_in_window`, matches the T9 replay); `watched_channels_count=10` (ASSUMED).

Judged split: **9 viral / 26 noise**. Examples: SpaceX-$75B-IPO / "Musk first
trillionaire" / Gensler-SEC-lawsuit news-day clusters → **viral**; daily "Курсы
криптовалют" price recaps, "Топ-15 активов" lists, a conference ad, and v=1 dead
posts → **noise**.

| Metric | Value | How computed |
|---|---|---|
| **ROC-AUC** (score vs binary) | **0.5641** | `eval.metrics.roc_auc` over the 35 real scores |
| **separation** mean (viral/noise) | 11.829 / 16.404 → **margin −4.575** | viral mean is BELOW noise mean |
| separation median (viral/noise) | 17.035 / 17.024 → margin +0.010 | — |
| **precision@1 / @3 / @5** | **0.00 / 0.33 / 0.60** | top-k by score (`precision_at_k`) |
| **Spearman** (score vs ordinal) | **0.0128** | `spearman_rho` — effectively no correlation |

**Finding:** on real data the score is **near-useless as a ranker** (AUC 0.56,
ρ 0.01). The single highest-scoring real cluster is NOT viral (precision@1 = 0).

#### Why real ≠ synthetic (the root cause — a concrete, valuable finding)

The corpus is **backfill-shaped and single-channel**: 33 of the 35 scoreable clusters
are single-channel (`unique_channels=1`), and the single-post windows have
`Δhours = 0`. The velocity term clamps `Δhours` to `MIN_WINDOW_HOURS` (1 minute), so:

```
single-post zero-window cluster: velocity = log1p(1)/(1/60) = 0.6931/0.016667 = 41.59
  → viral_score ≈ 41.59·0.4 + ~1.05·0.35 + 0.10·0.25 ≈ 17.03   (verified by running)
real multi-channel story (cluster 3292, 2 ch over 4.10 h):
  velocity = log1p(2)/4.10 = 0.268 → viral_score ≈ 1.596         (verified by running)
```

**31 of the 35 scoreable clusters (89%) have `delta_hours` below `MIN_WINDOW_HOURS`**
(the harness prints this warning next to the metrics, so the AUC is never read naked).
So a **trivial single post in a zero-width window outscores a genuine 2-channel story
that spread over 4 hours by ~10×** — the ranking is *inverted*. Every single-post
cluster piles up at ~17.0 (the noise floor becomes the ceiling), while the few real
multi-post/multi-channel events fall to ~1–2 because their real elapsed time divides
the velocity down. **This is the velocity formula degenerating on zero-width windows,
not a labeling artifact.** It is a scorer-design issue (out of scope for this
read-only eval) and the single most actionable output of T14.

### Layer 3 — Threshold calibration

Current defaults: watchlist `threshold` default = **0.0** (alert on every scored
cluster — `storage.models.watchlists._DEFAULT_THRESHOLD`); packs ship **70**; showcase
uses **85** (post) / **90** (case). Confusion at a sweep (alert iff score ≥ thr):

**Synthetic set (n=8, 3 viral):**

| thr | TP | FP | TN | FN | precision | recall |
|---:|--:|--:|--:|--:|---:|---:|
| 0 | 3 | 5 | 0 | 0 | 0.375 | 1.000 |
| 1 | 3 | 1 | 4 | 0 | 0.750 | 1.000 |
| **5** | **3** | **0** | **5** | **0** | **1.000** | **1.000** |
| 10 | 2 | 0 | 5 | 1 | 1.000 | 0.667 |
| 50 / 70 / 85 / 90 | 0 | 0 | 5 | 3 | 0.000 | 0.000 |

On well-formed data the **clean cut sits around 5** (perfect precision AND recall),
and the production 70/85/90 bars would catch **nothing** — they are calibrated for a
differently-scaled score than the formula actually emits.

**Real set (n=35, 9 viral):**

| thr | TP | FP | TN | FN | precision | recall |
|---:|--:|--:|--:|--:|---:|---:|
| 0 | 9 | 26 | 0 | 0 | 0.257 | 1.000 |
| 1 | 9 | 25 | 1 | 0 | 0.265 | 1.000 |
| 5 | 6 | 25 | 1 | 3 | 0.194 | 0.667 |
| 10 | 6 | 25 | 1 | 3 | 0.194 | 0.667 |
| 50 / 70 / 85 / 90 | 0 | 0 | 26 | 9 | 0.000 | 0.000 |

**Finding:** on the real corpus **no threshold separates viral from noise** — because
the score itself doesn't (precision peaks at ~0.27, barely above the 0.257 base rate).
The 85/90 showcase bars fire on **zero** of the 35 scoreable clusters, consistent with
the 0-alerts reality from T9. The default watchlist threshold of **0.0** would alert on
**all 35** (precision 0.26 → mostly spam); the operative range where the score has any
signal is single-digit (≈1–5), but even there real-data precision stays ~0.19–0.27. So
the current high defaults aren't "too high" in a vacuum — they're **mismatched to a
score that is mis-scaled and non-discriminating on this corpus**.

### Layer 4 — Lead-time sanity (PROXY)

A true detection-vs-mainstream lead time is **not derivable** — no external mainstream-
date labels exist in the corpus. The only available proxy is the T9 intra-corpus
first→peak-engagement spread (median ≈ 6,258 h ≈ 261 days), which on backfilled data
measures the corpus' total time span, not reaction speed. **Do not quote it as product
lead time.** With the score non-discriminating on real data (layer 2b), a "would it
cross threshold before peak" check is moot here — there is no reliable threshold to
cross. Real lead-time validation requires forward, live, multi-channel data (T11).

### Caveats (honest)

1. **Sample size is small.** Only 35 clusters are scoreable on the current corpus; the
   real-data AUC/Spearman are computed on n=35 (9 viral) — directionally clear (the
   score is non-discriminating on real data) but not statistically tight.
2. **Judge subjectivity.** I (the agent) labeled the real clusters from topic text +
   metrics; labels are committed (with rationale) for reproducibility, but a different
   judge could shift a few borderline calls. The *synthetic* set has unambiguous
   labels and is the rigorous discrimination proof; the real set is the honesty check.
3. **Proxies persist from T9.** Real-cluster `channel_avg` is the cold-channel fallback
   and `watched_channels_count` is assumed (10); cross_channel is therefore an
   assumption, not a live value.
4. **Real-label rigor grows as live data accrues.** Once live, multi-channel, non-
   backfilled clusters exist (and the velocity zero-width-window degeneracy is
   addressed in the SCORER), the same harness re-run on a fresh judged fixture will
   give a trustworthy real-data AUC. The harness + metrics are reusable and committed;
   only the fixture needs refreshing.

### Bottom line for the owner

The score's *design* is sound and provably meaningful (perfect synthetic AUC, all
monotonicity tests pass). But **right now, on real prod data, it does not separate
viral from noise** (AUC 0.56) because the velocity term degenerates on the corpus'
single-channel, zero-width-window shape and inverts the ranking. The fix is a
**scorer-side** change (revisit the `Δhours` clamp / velocity scaling) plus accruing
genuine multi-channel live data — both outside this read-only eval. T14 delivers the
reusable harness and the concrete numbers that make this diagnosable.
