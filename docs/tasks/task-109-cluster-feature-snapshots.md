---
id: TASK-109
title: B1 — forward feature-snapshot capture (cluster_feature_snapshots)
status: review
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: 5f38ff53ded2d184d2c71f69df5397b474b797a8
branch: "track-b/task-109-cluster-feature-snapshots"
tags: [track-b, data, ml-dataset, migration, scorer-hook, self-supervised]
---

# TASK-109 — B1 forward feature-snapshot capture

> Per cluster, at fixed early observation windows (15m/30m/1h after first-seen), log a METRICS-ONLY feature snapshot to a new `cluster_feature_snapshots` table — building TrendPulse's OWN labeled dataset from the live stream going forward (self-supervised). The future label (eventual engagement/spread) is computed LATER (B2) from the snapshot + final outcome; it is NOT stored here.

## Context

B0 (TASK-108) proved the existing corpus yields only ~1.7% quality stories — a thin training set. B1 is the lever that grows it: capture each cluster's EARLY trajectory live, so C1 can train on real forward-time-split data. Metrics-only (views/forwards/reactions/channels/age) → compliance-safe (raw text purged at 48h; we never store text). Opportunistic capture at the existing 5-min scorer tick (`scorer.tasks._score_user`): when a cluster's age crosses a window not yet captured, INSERT the snapshot ON CONFLICT DO NOTHING (idempotent on `(user_id, cluster_id, window_label)`).

Locate facts: alembic head = `0022` (linear chain, 4-digit ids) → new migration `0023`, `down_revision="0022"`. Models use SQLAlchemy 2.0 `Mapped`/`mapped_column`, `UserOwnedBase` (id+user_id CASCADE), `utcnow()` tz-aware default, inline `__table_args__` Index tuple. Score persist uses `pg_insert(...).on_conflict_do_*` + `session.flush()` within the caller's `get_session()` commit. `test_models.py` enumerates table names + user-owned tuple; `test_migrations.py` runs `upgrade head`. Compose-CI gotcha: do NOT add `:?` required-env interpolation to shared included compose; migration runner is standalone.

## Goal

A new metrics-only `ClusterFeatureSnapshot` model + Alembic `0023` migration + an opportunistic capture hook in `_score_user` that writes 15m/30m/1h snapshots for EVERY fresh cluster with in-window posts (not just topic-matched ones), idempotently. DoD: model + migration + hook + unit & integration tests green; `make ci-fast` green; round-trip migration test; NO raw text persisted; NO `Any`/`# type: ignore`; concrete types + runtime validation.

## Discussion
- Q: Capture only topic-matched clusters or all fresh clusters? → A: ALL fresh clusters with in-window posts. → Decision: hook BEFORE the topic-match `continue` in `_score_user`, with its own lightweight metrics aggregation (mirrors `_build_score_inputs` sums but no channel_avg baseline). (rationale: the dataset must capture every cluster's early trajectory; topic-match is an alert concern, not a data-capture concern.)
- Q: Which windows + how scheduled? → A: 15m/30m/60m (named constant seconds). Opportunistic at the 5-min tick (no new beat task). At each tick compute age = now − first_seen; for each window whose seconds ≤ age and not yet captured, insert. → Decision: idempotent via UNIQUE(user_id, cluster_id, window_label) + ON CONFLICT DO NOTHING. (rationale: the 5-min tick + 1h freshness window naturally covers all three windows in a cluster's first hour; no scheduler change = smaller blast radius.)
- Q: Store the label? → A: NO. → Decision: snapshot is FEATURES + captured_at + age only; label computed in B2 by joining the snapshot to the cluster's eventual outcome. (rationale: leak-free; label definition (doubling/quartile/regress) is a B2 concern and must stay tunable.)
- Q: What features? → A: cumulative views/forwards/reactions (sum over posts since first_seen, NOT the 24h rolling window — early-window must be from birth), post_count, distinct_channels_reached, breadth_velocity (channels/hour), age_seconds, window_label. → Decision: aggregate posts WHERE posted_at >= cluster.first_seen (cumulative-since-birth), not the score's 24h window. (rationale: the forward early-window feature is "what had accrued by T_obs since birth"; per-interval deltas are derivable downstream from successive snapshots.)
- Q: per-interval vs cumulative? → A: store cumulative; per-interval deltas = snapshot[30m] − snapshot[15m] computed downstream. → Decision: cumulative only (smaller schema, no redundancy; deltas are a view). (rationale: immutability/normalization; deltas reconstructable.)

## Scope
- Touch ONLY:
  - `backend/src/storage/models/cluster_feature_snapshots.py` (new) — `ClusterFeatureSnapshot(UserOwnedBase)`.
  - `backend/src/storage/models/__init__.py` — export the new model.
  - `backend/migrations/versions/0023_cluster_feature_snapshots.py` (new) — create_table + indexes + unique; downgrade drop.
  - `backend/src/scorer/tasks.py` — add `_observation_windows()` helper + `_capture_feature_snapshots(session, *, user_id, cluster, now)` + one call in `_score_user` before the topic-match continue. Named window constants.
  - `backend/src/scorer/constants.py` OR config — named `OBSERVATION_WINDOW_SECONDS` constant (no magic literals).
  - `backend/tests/unit/scorer/test_feature_snapshots.py` (new) — pure window/age logic.
  - `backend/tests/integration/test_feature_snapshot_capture.py` (new) — seed cluster+posts at ages, run scorer, assert snapshots.
  - `backend/tests/unit/storage/test_models.py` — add table name + user-owned tuple entry.
  - `backend/tests/integration/test_migrations.py` — optional 0023 round-trip.
  - `docs/tasks/tasks-index.md`, `docs/learnings.md`, `cache/track-b-data-ml-report.md`.
- Do NOT touch: the score formula (`scorer/score.py`), alert logic, pipeline steps, public API/OpenAPI, prod. No raw text column. No new beat task.
- Blast radius: new table (migration 0023 must be head); `_score_user` gains one idempotent write per crossed window (bounded, ON CONFLICT DO NOTHING); per-user isolation preserved (user_id CASCADE). No consumer reads it yet (B2/C1 will). database-reviewer for the migration (schema/index/FK).

## Acceptance Criteria
- [ ] Given a cluster aged 16min with in-window posts, When the scorer tick runs, Then a `15m` snapshot row exists with cumulative metrics and age≈16min, and no 30m/60m row.
- [ ] Given the same cluster re-ticked at 16min again, Then NO duplicate 15m row (idempotent ON CONFLICT).
- [ ] Given a cluster aged 65min, When ticked, Then 15m, 30m, 60m rows all exist (all crossed windows captured, even if earlier ticks were missed).
- [ ] Given a cluster younger than 15min, Then no snapshot row.
- [ ] Given two users' identically-aged clusters, Then each gets its own snapshot scoped by user_id (no cross-user leakage).
- [ ] Snapshot stores NO text column; only metrics + window_label + captured_at + age_seconds.
- [ ] `alembic upgrade head` then `downgrade` round-trips (table created then dropped) on a fresh schema.
- [ ] `make ci-fast` green; NO `Any`/`# type: ignore`; runtime validation on window_label.

## Invariants
- Metrics-only: no raw text persisted (compliance, CONVENTIONS retention).
- Idempotent: re-running a tick never duplicates a `(user_id, cluster_id, window_label)` snapshot.
- Per-user isolation: every row carries `user_id` (CASCADE FK).
- Leak-free: no eventual-outcome/label column (label is a B2 join).
- No magic literals: window seconds + labels are named constants.
- Migration 0023 chains from 0022 (linear head); downgrade fully reverses.
- Pure aggregation of in-window posts; no mutation of cluster/posts.

## Edge cases
- Cluster with no posts since first_seen → skip (no snapshot; nothing to capture).
- first_seen in the future / clock skew → age ≤ 0 → no window crossed → skip.
- Window already captured by an earlier tick → ON CONFLICT DO NOTHING (no error).
- Cluster exits the 1h freshness window before 60m tick → 60m may be missed; acceptable (documented; bounded by freshness window which defaults ≥ 60m).
- Zero-span single-post cluster → breadth_velocity uses a clamped denominator (no div-by-zero), mirroring score's BURST_FLOOR.

## Test plan
- unit: `_observation_windows` crossing logic (age→which windows due); breadth_velocity clamp; window_label validation; age computation.
- integration: seed user+cluster(first_seen=now−Xmin)+posts; commit; run `score_recent_clusters`; assert snapshot rows per crossed window; re-run → no dup; two users isolated; <15m → none.
- migration: `test_migrations.py` upgrade head includes 0023; optional explicit up/down round-trip for 0023.

## Checkpoints
current_step: 7
baseline_commit: 5f38ff53ded2d184d2c71f69df5397b474b797a8
branch: "track-b/task-109-cluster-feature-snapshots"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — unit + integration + migration on real pgvector)
- [x] 5 review (code-reviewer opus — PASS, 2 HIGH advisories folded in)
- [x] 5.5 security (database-reviewer opus — PASS; captured_at index folded in)
- [x] 6 ship (PR opened)
- [x] 7 learnings (appended)
debug_runs: []

## Details
- Built `ClusterFeatureSnapshot` model (metrics-only, no text; UNIQUE user/cluster/window) + migration 0023 (chains 0022) + pure `scorer/feature_snapshots.py` (windows_due/breadth_velocity/build_snapshot_metrics, 12 unit tests) + `_capture_feature_snapshots` hook in `_score_user` (opportunistic at 5-min tick; captures ALL fresh clusters, not just topic-matched).
- TDD RED→GREEN. Verified on a disposable pgvector:pg16: 5 integration capture tests (crossed-windows-only, backfill+idempotent, young→none, stale-freshness→none, per-user isolation) + 3 migration tests (upgrade head, 0023 up/down round-trip). Full unit suite 1019 passed; ruff+mypy strict (184 files) clean; no Any/type:ignore.
- Review folded into PR — code-reviewer (opus) HIGH #1: SAVEPOINT-isolated the snapshot write + try/except+log at call site so a snapshot failure can NEVER abort the score/alert transaction (data capture is best-effort; alerts revenue-critical). HIGH #2: documented the 1h-window freshness-coupling KNOWN LIMITATION (quiet cluster ages out before 1h snapshot → missing-not-at-random; B2 must not impute) + added stale-`updated_at` integration test. MEDIUM: added `Post.posted_at <= now` upper bound (leak-free at observation instant). database-reviewer (opus) MEDIUM: added `ix_cluster_feature_snapshots_captured_at` for future B2/C1 time-ranged reads + pruning. LOW redundant `ix_user_id` + cluster_id CASCADE divergence accepted (mirror repo convention / deliberate).
