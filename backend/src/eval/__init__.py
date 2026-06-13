"""Offline accuracy/quality harness for the prod corpus (TASK-081, metrics-only).

There are no live users (0 alerts / 0 feedback), so signal quality must be measured
OFFLINE against the existing corpus. The corpus has a hard limitation: `posts.text`
and `posts.embedding` are NULL for ALL rows (retention purged text; post-level
vectors were never persisted). Only per-post METRICS survive (views/forwards/
reactions + posted_at/channel_id/user_id/cluster_id) and per-cluster CENTROIDS.

Therefore this harness measures exactly the two things the corpus CAN support and
nothing it cannot:

- `scoring_replay` — replays the REAL scorer formula (`scorer.score.compute_components`)
  over the corpus "as if in time", reusing the production input-building aggregation
  (same `score_window_seconds` semantics) WITHOUT reimplementing the formula.
- `clustering_audit` — audits cluster STRUCTURE (size histogram, singletons, mega
  buckets, duplicate topics, duplicate centroids via cosine on the 384-d vectors).

What is NOT measurable here (and why) is documented in the baseline report and the
task doc: clustering/embedding ACCURACY cannot be evaluated because the source text
and post-level vectors are gone — that needs a forward text-capture experiment (T11).

The harness is extended (TASK-085, T14) to prove the score is MEANINGFUL — that a
high score means "spreading / worth an alert" and a low score means "noise" — not
merely non-zero:

- `metrics` — pure ranking-quality helpers (ROC-AUC, precision@k, Spearman, viral-vs-
  noise separation, confusion at a threshold), exact and numpy-free, unit-tested.
- `scenarios` — labeled `(ScoreInputs, label)` sets: synthetic controlled cases
  (viral/noise/borderline with intended labels) and a committed fixture of human-
  judged REAL prod clusters. Both reuse `scorer.score.compute_components` — the
  formula is never reimplemented.
"""
