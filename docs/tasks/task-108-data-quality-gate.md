---
id: TASK-108
title: B0 — data-quality gate (is_quality_cluster + corpus quality report)
status: review
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: 6f576fba90038812f78f7c54c3a7e2d1ce5e0655
branch: "track-b/task-108-data-quality-gate"
tags: [track-b, data, eval, quality-gate, ml-prereq]
---

# TASK-108 — B0 data-quality gate

> Build a reusable, unit-tested data-quality evaluation module that scores corpus clusters and DEFINES a clean training subset; C-training MUST pass through `is_quality_cluster()`. This is the GATE.

## Context

Owner's explicit prerequisite for Track C (ML): "train only on quality data". The signal-quality report (`apps/trendPulse/cache/trendpulse-signal-quality-report.md`) proves the corpus is pathological: 68% singletons, 3 mega-buckets (4,102/1,713/1,210 posts), 5,122 near-dup centroid pairs (cosine≥0.9), 753 dup-topic groups (3,010 clusters / 32%), backfill-shaped, single-channel-heavy, recurring "Доброе утро"/daily-market boilerplate chains. Training a GBDT on this raw would learn artefacts. B0 produces (a) a quality report with numbers and (b) a reusable `is_quality_cluster()` filter the downstream B2 harness + C1 training consume.

Reuse surface (locate stage): `backend/src/eval/{corpus,clustering_audit,distribution,metrics}.py` give immutable records + pure helpers (size audit, dup-topic, dup-centroid cosine pass, percentile/summary). `eval_offline/harness2_predictive.py` re-clusters `corpus.sqlite` (cosine 0.75 + window + span guard) → `list[list[int]]` of post-indices. No `is_quality_cluster`/co-channel/boilerplate predicate exists anywhere — that is the new code.

## Goal

A pure, substrate-agnostic, unit-tested quality module in `backend/src/eval/quality.py` + tests in `backend/tests/unit/eval/test_quality.py`, plus a runnable `backend/scripts/quality_report.py` that emits the corpus quality numbers. `is_quality_cluster()` operates on a `ClusterQualityFeatures` record so it works on BOTH the prod CSV snapshot AND the re-clustered `corpus.sqlite` stories that C-training uses. DoD: module + tests green under `make ci-fast`; report numbers written to `cache/track-b-data-ml-report.md`; the filter is importable and documented as the C-training gate.

## Discussion
- Q: Which corpus is the gate's substrate? → A: `corpus.sqlite` (has text → real re-clustered stories) is the C-training substrate, but the prod CSV snapshot is metrics-only. → Decision: make `is_quality_cluster()` consume a substrate-agnostic `ClusterQualityFeatures` dataclass (post_count, unique_channels, span_hours, max_cross_cluster_cosine, is_recurring_boilerplate, completeness_ok, temporal_ok). Both substrates project into it. (rationale: one gate, reused everywhere; no coupling to a single corpus shape.)
- Q: What does "quality" exclude? → A: from the report pathologies — singletons (post_count<MIN_POSTS), mega-buckets (post_count>MAX_POSTS catch-all centroids), near-dup clusters (max cosine to another centroid ≥ DUP_COSINE), recurring boilerplate (span > MAX_QUALITY_SPAN with low channel breadth = daily-market chains), single-channel-only (unique_channels<MIN_CHANNELS → no cross-channel signal = label-leakage-prone & not the product's target), incomplete fields, temporally-insane (backfill: fetched_at − posted_at huge). → Decision: each is a named-constant gate; `is_quality_cluster` ANDs them; `QualityVerdict` records WHICH gates failed (for the report breakdown). (rationale: transparent, tunable, debuggable.)
- Q: bot/coordinated-amplification heuristic? → A: full collusion graph is Track D (D1). → Decision: B0 ships a LIGHT co-channel rapid-repeat heuristic as ONE quality signal (a cluster whose posts are dominated by a single channel posting in rapid bursts → coordinated/self-amplified, not organic spread), not the full graph. (rationale: surgical; the moat graph is its own task.)
- Q: label-leakage risk? → A: the quality features are EARLY/STRUCTURAL only (size, channels, span, dup) — they must NOT include the future label. → Decision: document that `ClusterQualityFeatures` is leak-free (no eventual-engagement field); the gate runs at feature time. (rationale: clean separation for B2/C1.)

## Scope
- Touch ONLY:
  - `backend/src/eval/quality.py` (new) — `ClusterQualityFeatures`, `QualityThresholds`, `QualityVerdict`, `is_quality_cluster()`, `assess_cluster()`, `summarize_quality()`, per-cluster feature builders from `PostRecord` clusters, recurring-boilerplate + co-channel heuristics.
  - `backend/tests/unit/eval/test_quality.py` (new) — unit tests (pytest.mark.unit, inline factories mirroring test_clustering_audit.py).
  - `backend/scripts/quality_report.py` (new) — runnable offline report over the corpus (CSV snapshot + optional sqlite re-cluster), stdout numbers.
  - `cache/track-b-data-ml-report.md` (new) — report numbers.
  - `docs/tasks/tasks-index.md` — add TASK-108 row.
  - `docs/learnings.md` — append B0 learning.
- Do NOT touch: `scorer/`, `pipeline/`, any DB/Alembic, prod, public API, existing `eval/` modules (only ADD a sibling). No new heavy deps (numpy already present).
- Blast radius: none at runtime (pure offline eval module, no import by api/collector/pipeline/scorer). Downstream consumers = B2 harness + C1 training (future tasks), by import.

## Acceptance Criteria
- [ ] Given a `ClusterQualityFeatures` with post_count below MIN, When `is_quality_cluster`, Then False with verdict.failed_gates containing "too_small".
- [ ] Given features for a healthy multi-channel medium cluster, When `is_quality_cluster`, Then True and failed_gates empty.
- [ ] Given a mega-bucket (post_count > MAX), Then False ("mega_bucket").
- [ ] Given near-dup (max_cross_cluster_cosine ≥ DUP_COSINE), Then False ("near_duplicate").
- [ ] Given recurring boilerplate (span huge, breadth low), Then False ("recurring_boilerplate").
- [ ] Given single-channel cluster (unique_channels < MIN_CHANNELS), Then False ("single_channel").
- [ ] Given a sequence of features, When `summarize_quality`, Then it reports total, quality_count, quality_pct, and a per-gate failure histogram — all reproducible.
- [ ] `quality_report.py` runs offline (no DB/network) over `backend/data/eval/*.csv` and prints the numbers; documented reproduce command.
- [ ] All new tests pass; `make ci-fast` (ruff format/check + mypy + pytest -m 'not integration') green; NO `Any`, no `# type: ignore`.

## Invariants
- Pure/immutable: features and verdicts are frozen dataclasses; functions return new data, never mutate inputs.
- Leak-free: `ClusterQualityFeatures` carries NO future-label field; gate runs at feature time.
- All thresholds are NAMED constants in `QualityThresholds` (no magic literals); spans in SECONDS as named constants.
- Concrete types only; validate feature inputs at the boundary (raise `QualityInputError` on malformed, mirroring `MetricInputError`/`CorpusParseError`).
- Reuses existing helpers (`audit_*`, `count_duplicate_centroid_pairs`, `percentile`/`summarize`) rather than reimplementing.

## Edge cases
- Empty cluster sequence → summarize returns total=0, quality_pct=0.0 (honest placeholder, like `summarize`).
- Cluster with 0 posts (empty prod cluster) → too_small gate, excluded.
- Zero-span single-post cluster → span heuristic must not divide by zero (clamp like harness2 MIN_WINDOW).
- Centroid cosine for a cluster with no comparator (only cluster) → max_cross_cluster_cosine = 0.0 (passes that gate).
- All-channels-equal vs single-channel-dominant → co-channel heuristic uses a dominance RATIO, not absolute count.

## Test plan
- unit: gate-by-gate truth table for `is_quality_cluster`; feature-builder from `PostRecord` clusters; `summarize_quality` counts + per-gate histogram; boundary values at each threshold; input validation raises; recurring-boilerplate + co-channel heuristics; empty/degenerate inputs.
- integration: none (pure module).
- e2e: none. Manual: run `quality_report.py` on the committed CSV sample + full snapshot if present, capture numbers.

## Checkpoints
current_step: 7
baseline_commit: 6f576fba90038812f78f7c54c3a7e2d1ce5e0655
branch: "track-b/task-108-data-quality-gate"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — PASS, no CRITICAL/HIGH; 1 MEDIUM + LOWs folded in)
- [x] 5.5 security (N/A — pure offline eval; SQL via bind param; no auth/secrets/public-API/network input)
- [x] 6 ship (PR opened)
- [x] 7 learnings (appended)
debug_runs: []

## Details
- Built `eval/quality.py`: substrate-agnostic, leak-free `ClusterQualityFeatures` + 8 named gates + `is_quality_cluster`/`assess_cluster`/`summarize_quality`/`build_cluster_features`. 27 unit tests (TDD RED→GREEN).
- `scripts/quality_report.py`: CSV mode (prod metrics-only snapshot) + sqlite re-cluster mode (harness2 method on corpus.sqlite, the C-training substrate).
- Verify: full backend unit suite 1001 passed; eval suite 101→ (with 6 added review tests) green; ruff format/check + mypy --strict (182 files) clean; no Any/no type:ignore.
- Real-behavior numbers (re-clustered corpus.sqlite, 49,157 posts/28 ch → 18,971 stories): **315/18,971 (1.66%)** pass the gate; dominant rejections single_channel 17,309 + too_small 16,800; near_duplicate 3,949. Quality subset is thin (median 3 posts) — the data-ceiling B1 forward-capture must grow.
- Review (opus, fresh ctx) PASS. Folded findings into PR: MEDIUM centroid-definition inconsistency fixed (`_recluster` now returns its own final L2-normalised centroids, reused by the near-dup gate → self-consistent: near_dup 3,942→3,949); LOW tz fix (`_to_utc_timestamp`, naive→UTC); LOW added 6 boundary/guard/histogram tests.
