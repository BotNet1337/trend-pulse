# TASK-113 — C2 science-grounded early-window features (measure lift each)

**Track:** B (data) → C (ML), step C2. **Depends on:** TASK-110 (B2), TASK-111 (B3), TASK-112 (C1).

## Goal

Add science-grounded early-window features incrementally and MEASURE the marginal lift each contributes over the C1 base feature set, keeping only the ones that pay. Every feature is pure, leak-free (early-only), and unit-tested.

## What was built

**Pure typed feature module** (`backend/src/eval/science_features.py`, mypy --strict, no `Any`):
- `TimedEvent` — frozen, validated (epoch + source_id + weight) — the substrate-agnostic projection both TG posts and Higgs interactions map into.
- `ewma_velocity` / `ewma_acceleration` — exponentially-weighted event rate (recent activity weighted more) + first-vs-second-half rate change (accelerating vs decaying).
- `breadth_velocity` — distinct-source growth per hour (cross-channel spread speed).
- `hawkes_branching_ratio` — moment estimate of the self-exciting branching factor n* (Mishra CIKM'16 hybrid; n*>=1 ≈ super-critical / self-sustaining).
- `time_of_day_phase` — TiDeH circadian phase of birth in [0,1) (diurnal attention; Kobayashi & Lambiotte 2016).
- `source_entropy` + `effective_independent_sources = exp(H)` — the independence/collusion MOAT: effective number of independent sources (collapses toward 1 under single-source amplification even if raw count is high).
- `channel_authority` — TunkRank-style one-pass influence of the strongest early mover.
- `compute_science_features` — the full bundle in one pass.

**Lift harness** (`eval_offline/harness_c2_lift.py`): for each feature measures, on the leak-free B2 Higgs test split, (a) standalone test PR-AUC/ROC-AUC and (b) marginal lift = base-GBDT PR-AUC vs base+feature GBDT PR-AUC.

## Results (Higgs 36k cascades, B2 doubling label, test n=5,574)

**Standalone predictive power (which features carry signal at all):**

| Feature | Standalone PR-AUC | ROC-AUC |
|---|---|---|
| **effective_independent_sources** | **0.831** | 0.844 |
| **hawkes_branching** | 0.721 | 0.652 |
| channel_authority | 0.671 | 0.626 |
| ewma_acceleration | 0.494 | 0.387 |
| time_of_day_phase | 0.455 | 0.502 |
| breadth_velocity | 0.402 | 0.242 |
| ewma_velocity | 0.356 | 0.189 |

**Marginal lift over the C1 base GBDT (base PR-AUC = 0.920):**

| +Feature | PR-AUC | Δ |
|---|---|---|
| time_of_day_phase | 0.924 | **+0.004** |
| ewma_acceleration | 0.920 | +0.001 |
| effective_independent_sources | 0.919 | -0.001 |
| (all others) | 0.917-0.918 | -0.001 to -0.003 |
| base + ALL C2 | 0.917 | -0.003 |

## Honest finding (measured, not asserted)

`effective_independent_sources` (the independence/collusion moat) and `hawkes_branching` (self-excitation) carry **real standalone signal** (PR-AUC 0.83 / 0.72) — they ARE predictive. But the **marginal lift over the C1 base set on Higgs is ~zero** (best +0.004): the 4 base features already capture most of what they add (effective_sources correlates with e_ch; hawkes with the velocity/burst terms). Adding all C2 features together slightly HURTS (−0.003, overfit on redundant inputs).

Implication (honest): on the Higgs retweet substrate the base early features are near-sufficient. The C2 features are kept available because (a) they are individually validated to carry signal, and (b) the independence/collusion moat (`effective_independent_sources`) is expected to matter MORE on TG — where coordinated single-source amplification is the exact noise the product must filter and the base features are weaker — than on Higgs organic retweets. They should be re-measured on the TG B1 snapshots once N accrues; do NOT blindly add all to the C1 vector now (it overfits).

## Verification
- 18 unit tests (`tests/unit/eval/test_science_features.py`), hand-computed (each feature + validation + empties + the bundle).
- Full eval unit suite green; ruff + mypy --strict (184 files) clean, no `Any`/`# type: ignore`.
