# TASK-112 — C1 GBDT virality model (LightGBM) + formula fallback

**Track:** B (data) → C (ML), step C1. **Depends on:** TASK-108 (B0 gate), TASK-110 (B2 split/label/PR-AUC), TASK-111 (B3 volume), TASK-086 (v2 formula).

## Goal

Replace the hand-tuned v2 *formula* RANKING with a GBDT that consumes the SAME B1/B2 early-window feature vector and emits a CALIBRATED probability — but only when the cluster has enough early signal; below that floor (cold-start) the scorer falls back to the v2 formula. Behind a clean typed interface, no `Any`.

## What was built

**Typed inference interface** (`backend/src/scorer/viral_model.py`, mypy --strict clean, no `Any`):
- `EarlyFeatures` — frozen, validated early-window vector (the B1 snapshot / B2 harness feature names: e_ch/e_posts/e_eng_log/e_burst). `FEATURE_ORDER` is the single source of truth shared by training + inference.
- `ViralModel` Protocol — `predict_proba(EarlyFeatures) -> float` in [0,1].
- `FormulaFallbackModel` — wraps the deterministic v2 formula (`scorer.score.compute_viral_score`) into a [0,1] pseudo-probability; the always-available cold-start baseline.
- `GbdtViralModel` — loads a LightGBM booster from its **native text dump** (no pickle → reviewable artifact); validates BOTH the caller-supplied feature order AND the feature names baked into the artifact (`booster.feature_name()`) against `FEATURE_ORDER`, so a stale/reordered model is rejected loudly, never silently mis-fed. LightGBM imported **lazily** (inside `load`) — the api/worker boot path never imports it unless a model is loaded.
- `_LightGbmBoosterAdapter` — confines lightgbm's `Any`-typed `predict` to one boundary, coercing to `list[float]`.
- `select_prediction` — the policy: GBDT when loaded AND `has_minimum_signal()` (>=2 posts and >=2 channels), else fallback; returns `ModelChoice` so the caller can measure the GBDT-vs-fallback split.

**Lazy scorer package** (`backend/src/scorer/__init__.py`): `score_recent_clusters` is now exported via PEP 562 `__getattr__` so importing the pure path (`scorer.score`, `scorer.viral_model`) does NOT drag in `scorer.tasks` -> billing -> storage -> config (prod secrets/DB). Only the task layer triggers that import.

**Offline trainer** (`eval_offline/train_gbdt_c1.py`): trains LightGBM on the B3 Higgs cascades (volume) with the B2 doubling label + chronological split, reports PR-AUC/ROC-AUC vs window, the v2-formula baseline on the same split, Brier score, and a reliability table; saves the native text model.

**`lightgbm>=4.5,<5`** added to the opt-in `ml` dependency group (not default — stays off the lean image, like sentence-transformers).

**Committed artifact:** `eval_offline/models/viral_gbdt_higgs_1h.txt` (LightGBM text, 350KB) — a real, loadable model.

## Results (Higgs 36k cascades, B2 doubling label, test n=5,574, ~46% positive)

| T_obs | GBDT PR-AUC | GBDT ROC-AUC | v2 formula PR-AUC | Brier (GBDT) |
|---|---|---|---|---|
| 15m | 0.883 | 0.884 | 0.851 | 0.139 |
| 30m | 0.907 | 0.912 | 0.886 | 0.121 |
| **1h** | **0.920** | 0.927 | 0.914 | **0.106** |
| 3h | 0.911 | 0.919 | 0.908 | 0.122 |

**Honest read.** The GBDT modestly beats the v2 formula at short windows (15m: 0.883 vs 0.851 PR-AUC) and is roughly tied at 1h (0.920 vs 0.914) — consistent with the known <50% variance ceiling: the early features carry most of the signal and a tree ensemble adds a small, real lift, not a transformation. Crucially the GBDT output is **calibrated** (Brier 0.11 at 1h; reliability table: predicted [0.8,1.0) → 0.98 observed, [0.0,0.2) → 0.13 observed), which the unbounded formula is not — so the alert threshold becomes a real probability. The tie at 1h justifies keeping the formula as the fallback.

## N caveat (CRITICAL — read honestly)
**The 0.92 PR-AUC is on the Higgs PUBLIC cascade dataset (B3), NOT TG production data.** On the B0-gated TG corpus the clean subset is thin (~315-964 stories) — too few for a production-grade TG GBDT. C1 here proves the methodology + interface + produces a loadable artifact trained on real cascade VOLUME. The durable TG model comes from (a) B1 `cluster_feature_snapshots` accruing in prod over time, and (b) re-training on the TG snapshots once N is sufficient. The interface is feature-schema-identical so swapping the artifact needs no code change. Do NOT report 0.92 as the TG production number.

## Verification
- 13 unit tests (`tests/unit/scorer/test_viral_model.py`) with a fake booster (no lightgbm dep in CI): feature-order validation, min-signal floor, fallback monotonicity, GBDT clamp, select policy, missing-artifact.
- Full backend unit suite **1054 passed** (5 pre-existing DB-integration ERRORs, unrelated). ruff + mypy --strict (185 files) green, no `Any`/`# type: ignore`. `uv.lock` updated with lightgbm.
- Saved artifact reloads via `GbdtViralModel.load` and predicts; feature-name cross-check verified.
- Adversarial code review (opus, fresh ctx): 5 HIGH addressed (artifact feature-name validation, baseline watched-count unit fix, degenerate-test guard, label alignment, Brier empty-guard).
