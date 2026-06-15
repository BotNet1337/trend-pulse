# TASK-110 — B2 forward-time-split harness (Cheng "doubling" label)

**Track:** B (data) → C (ML), step B2. **Depends on:** TASK-108 (B0 quality gate), TASK-109 (B1 snapshots), TASK-081/085 (eval harness + metrics).

## Goal

Build the LEAK-FREE early-detection harness that answers "can features observed only over a cluster's first `T_obs` predict its eventual virality?" — the methodology Track C (GBDT) trains against. Two leakage hazards closed: (1) temporal leakage at the chronological split boundary (a configurable GAP drops birth-time stragglers so a train cluster's future window cannot reach a test cluster's early window); (2) label leakage via the cohort (the Cheng WWW'14 balanced-doubling label's median reference is computed PER PARTITION).

## What was built

**Pure, DB-free, numpy-free, unit-tested core** (`backend/src/eval/forward_split.py`):
- `ClusterOutcome` — frozen, runtime-validated record carrying only label-time quantities (birth `t0_epoch`, `final_outcome`, `age_at_outcome_seconds`); features live separately so the record cannot leak features into the label.
- `split_by_time(clusters, ratios)` — chronological older→train / newer→test split by index on the t0-sorted order, with a `gap_seconds` no-overlap guard applied as a band on BOTH sides of each boundary (drops upstream tail AND downstream head, so the last surviving train cluster is born >= gap before the first surviving val cluster — closes a code-review CRITICAL where dropping only the upstream tail left a downstream cluster at the boundary unseparated); `gap_seconds=0` disables the guard. Returns `ForwardSplit` (train/val/test + `dropped_in_gap`).
- `SplitRatios` (validated: ratios sum to 1.0, gap >= 0), `Partition` enum + typed accessor.
- Three label variants via `LabelKind`: `DOUBLING` (Cheng balanced — outcome > comparable-age cohort median), `TOP_QUARTILE` (>= cohort 75th pct), `LOG_FINAL` (regression target log1p(final)).
- `CohortPolicy(bucket_seconds)` — comparable-age cohorting so a 6h-old and 6-day-old story are not compared.
- `label_partitions(split, kind, cohort)` — labels each partition from its OWN cohort references (the no-leakage enforcement point).

**PR-AUC added** to `backend/src/eval/metrics.py`: `average_precision` (interpolation-free AP / PR-AUC) — the metric of record for the imbalanced early-detection task, alongside existing `roc_auc`/`precision_at_k`.

**Corpus driver** (`eval_offline/harness3_forward_split.py`): re-clusters `corpus.sqlite` (harness2 method: cosine 0.75 + 48h window + 72h span guard) → gates every story through B0 `is_quality_cluster` → for each `T_obs` in {15m,30m,1h,3h,6h} builds early features over `[t0, t0+T_obs]` (B1 snapshot metric shape) + the future outcome → applies the B2 chronological split (24h gap) + per-partition doubling/top-quartile labels → reports test-set PR-AUC/ROC-AUC/P@20 for the v2 formula, each early feature, and a learned logistic blend. Reuses (never reimplements) the B0 gate, B2 split/label, and eval metrics.

## Results (re-clustered corpus.sqlite, 49,157 posts / 28 channels → 18,971 stories; B0 gate → 964 pass)

**PR-AUC vs observation window, B0-gated clean subset, doubling label** (test n=194, ~50% positive, 24h gap):

| T_obs | v2 PR-AUC | v2 ROC-AUC | best feature (PR-AUC) |
|---|---|---|---|
| 15m | 0.609 | 0.618 | e_eng_norm 0.616 |
| 30m | 0.641 | 0.647 | e_eng_log 0.642 |
| 1h  | 0.696 | 0.697 | e_eng_norm 0.704 |
| 3h  | 0.729 | 0.725 | e_eng_log 0.746 |
| 6h  | 0.750 | 0.747 | e_eng_log 0.785 |

PR-AUC rises monotonically with the window (more early signal accrues); engagement-log / engagement-norm carry the signal (consistent with the v2 derivation). Top-quartile (rarer positives) is harder: PR-AUC 0.43 @15m → 0.64 @3h.

**N caveat (honest):** the clean gated subset is THIN (964 stories on this run, test split 194). These AUCs prove the METHODOLOGY (no-leakage forward split + balanced label discriminates) but are N-limited — not a production-grade model. The volume comes from B1 live capture accruing + B3 public datasets.

**Leakage contrast:** the SAME pipeline on the UNGATED corpus (18,971 stories) reports v2 PR-AUC 0.965 — inflated because on the raw single-channel/duplicate-heavy corpus engagement-log nearly equals the doubling label by construction. This is exactly the artefact the B0 gate removes; the gated 0.61-0.75 is the honest number.

## Verification
- 18 new unit tests (`tests/unit/eval/test_forward_split.py`) + 3 PR-AUC tests (`test_metrics.py`), all hand-computed.
- Full backend unit suite **1040 passed** (5 DB-integration ERRORs are pre-existing, require live Postgres, unrelated — all B2 code is pure/DB-free).
- `ruff format --check` + `ruff check` + `mypy` (184 files) green. No `Any`, no `# type: ignore`.
