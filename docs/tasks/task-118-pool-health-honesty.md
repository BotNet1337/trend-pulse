---
id: TASK-118
title: Pool-health honesty — per-account read outcome + "failing" state + ingest-staleness contradiction
status: planned
owner: backend+frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: ""
tags: [telegram, pool, observability, redis, frontend]
---

# TASK-118 — Pool-health honesty (a "Connected" row means actually reading)

> Track a per-account READ OUTCOME on `_Account` (last successful read, consecutive failures, last
> non-fatal reason). Add a `failing` state when an account connects but its reads persistently fail
> (the swallowed "wrong session ID" class). Surface the all-healthy-but-ingest-stale contradiction.
> Fix the emit cadence to once per tick. Frontend renders `failing` + relabels `healthy/target`.

## Context
Part of EPIC-POOL-HEALTH-REVIVE. The pool (`collector/telegram/account_pool.py`) already exposes
`account_statuses()` returning `AccountStatus(index, state ∈ {healthy,cooling,quarantined},
cooldown_remaining_seconds, last_error_reason)`, with `_Account` holding `last_error_reason`
(TASK-115). The reader (`collector/telegram/reader.py`) calls `note_current_error(...)` ONLY in the
flood-wait and permanent-auth branches; the **non-permanent transient** branch
(`_emit_health_best_effort(notify_reason="auth_error", ...)`) records nothing and never quarantines
— that is exactly where the "wrong session ID" class lands (it is not in
`auth_errors._PERMANENT_AUTH_ERROR_NAMES`, and `report_success()` is only reached after a clean
iteration). So an account that connects but whose every read errors stays `healthy` forever. The
snapshot is published by `observability/pool_health.py::emit_pool_health` → Redis
`pool:health:latest`; the API reads it in `api/routes/pool_admin.py`; the FE renders it in
`frontend/src/features/pool-admin/ui/pool-health-table.tsx` + `lib.ts`. Ingest staleness already
exists as `observability/signal_latency.py::emit_ingest_staleness` (TASK-100).

## Goal
1. `_Account` gains read-outcome fields: `last_read_ok_at: float | None`, `consecutive_read_failures:
   int`, plus reuse of `last_error_reason` for the non-fatal reason. The reader records a success
   (reset failures, stamp `last_read_ok_at`) on a clean read and a failure (increment, set reason) at
   the currently-silent transient catch site.
2. `AccountState` gains `"failing"`; `account_statuses()` returns `failing` when an account is live
   (not quarantined/cooling) but `consecutive_read_failures >= POOL_FAILING_THRESHOLD` OR it has never
   read OK within `POOL_FAILING_NO_READ_WINDOW_SECONDS` while errors are present. Carries the reason.
3. The snapshot gains a derived `ingest_contradiction: bool` — true when `healthy == size` (all green)
   yet ingest is stale (read cross-process from the ingest-staleness signal / `MAX(fetched_at)` age).
   This makes "all healthy but 0 posts" visible without changing rotation.
4. Emit cadence: `pool_health` is emitted ONCE per `read()` cycle (it already is at the end of
   `read()`); remove/guard any path that emits it per-channel or per-acquire so prod stops seeing
   ~1 emit/sec. Best-effort calls that ONLY notify_ops keep their throttle; the metric/snapshot write
   is the once-per-tick one.
5. Frontend: relabel the `{healthy}/{target} healthy` line (it is healthy-vs-target, not 2/1) to an
   unambiguous "{healthy} of {target} target healthy"; add a `Failing` badge + reason column row for
   the new state; show the `ingest_contradiction` banner when set.

## Discussion
- Q: Should `failing` gate `acquire()` (stop handing out a failing account)? → **A (default): NO.**
  `failing` is observational only this story — gating acquisition risks starving the pool on a false
  positive (a transient network blip). Revive (TASK-119) is the real remediation. Flagged as an
  owner decision if they want auto-cooldown of failing accounts later.
- Q: Failing thresholds? → **A (default):** `POOL_FAILING_THRESHOLD = 5` consecutive read failures,
  `POOL_FAILING_NO_READ_WINDOW_SECONDS = 30 * 60` (30 min). Named constants in
  `collector/constants.py`; owner can tune. Rationale: 5 consecutive covers the steady "wrong session
  ID" loop; 30 min covers an account that connects but never once reads in a window.
- Q: Where does the snapshot learn ingest staleness (it is computed in a DIFFERENT task, against
  Postgres)? → **A:** `emit_ingest_staleness` already runs in `observability/tasks.py`; have it (or the
  collector) publish the latest `stale`/`age_s` to a small Redis key, and `_publish_snapshot` reads
  that key (best-effort, fail-open to `ingest_contradiction=false`). Do NOT add a DB query to the
  collect-tick hot path. **Owner-flag:** if they prefer the API to compute the contradiction
  (it already can query Postgres) instead of the collector, that is an equivalent design — default is
  collector-side derived flag so the snapshot is self-contained.
- Q: keep last reason after recovery? → **A:** yes, last-known (consistent with TASK-115);
  `consecutive_read_failures` resets on success so the STATE recovers even if the reason text lingers.

## Scope
- Touch ONLY:
  - `backend/src/collector/telegram/account_pool.py` — `_Account` read-outcome fields; `AccountState`
    += `failing`; `account_statuses()` failing logic; `note_read_success()` / `note_read_failure(reason)`
    helpers (mirror `note_current_error`).
  - `backend/src/collector/telegram/reader.py` — call `note_read_success()` after a clean iteration
    (where `report_success()` is) and `note_read_failure(type(exc).__name__)` at the
    currently-silent transient catch site (the `auth_error` branch). No rotation/quarantine change.
  - `backend/src/observability/pool_health.py` — `AccountStatus` serialization already via `asdict`;
    add `ingest_contradiction` to the snapshot (read the ingest-staleness Redis key best-effort);
    confirm single-emit semantics.
  - `backend/src/observability/signal_latency.py` and/or `observability/tasks.py` — publish the latest
    ingest-staleness `{stale, age_s}` to a Redis key for the collector to read (small, additive).
  - `backend/src/collector/constants.py` — `POOL_FAILING_THRESHOLD`, `POOL_FAILING_NO_READ_WINDOW_SECONDS`,
    the ingest-staleness Redis key + its TTL (named constants).
  - `backend/src/api/routes/pool_admin.py` — `PoolHealthAccount.state` doc widened to include
    `failing`; `PoolHealthResponse` += `ingest_contradiction: bool = False`; `_PoolHealthSnapshot`
    += `ingest_contradiction` (extra="ignore" already tolerant). Boundary only.
  - `frontend/src/features/pool-admin/lib.ts` — `AccountState` union += `failing`; `accountStateLabel`/
    `accountStateBadgeVariant`/`asAccountState` handle it.
  - `frontend/src/features/pool-admin/ui/pool-health-table.tsx` — relabel the summary line; render
    `failing` reason in the last-error column; `ingest_contradiction` banner.
  - tests: `backend/tests/unit/test_account_pool.py`, pool-health test, reader test; FE `lib` test.
- Do NOT touch: rotation logic (`acquire`/`report_flood_wait`/`quarantine_current`), the QR service,
  the DB (no schema here — that is TASK-119).
- Blast radius: `AccountState` Literal grows (the FE `asAccountState` default maps unknown →
  quarantined today; widen it). Snapshot JSON gains `ingest_contradiction` (additive; `extra="ignore"`
  consumer). OpenAPI types regenerate for the new response field.

## Acceptance Criteria
- [ ] Given an account that connects but every read raises a non-permanent error (e.g. a class named
      like the "wrong session ID" error), When `POOL_FAILING_THRESHOLD` consecutive failures occur,
      Then `account_statuses()` reports `state == "failing"` with the recorded reason, and `acquire()`
      behavior is UNCHANGED (still hands it out — observational only).
- [ ] Given an account reads cleanly, When inspected, Then its `consecutive_read_failures == 0`,
      `last_read_ok_at` is stamped, and `state == "healthy"`.
- [ ] Given a snapshot where `healthy == size` but the ingest-staleness key says stale, When the API
      serves `/pool-admin/pool-health`, Then `ingest_contradiction == true`.
- [ ] Given a collect-tick runs, When it completes, Then `pool_health` is emitted exactly ONCE for the
      cycle (no per-channel/per-acquire metric emit).
- [ ] FE: a `failing` account renders a distinct "Failing" badge + its reason; the summary line reads
      unambiguously (target-relative, not "2/1"); the contradiction banner shows when set.
- [ ] No session string / api_hash in the snapshot; index stays the only per-account identifier.
- [ ] `make test` + ruff + mypy strict green; FE typecheck + vitest green.

## Plan (per-file, ordered)
1. `collector/constants.py` — add `POOL_FAILING_THRESHOLD = 5`,
   `POOL_FAILING_NO_READ_WINDOW_SECONDS = 30 * 60` (via a private `_..._MINUTES`),
   `INGEST_STALENESS_REDIS_KEY = "ingest:staleness:latest"`, `INGEST_STALENESS_TTL_SECONDS`.
2. `account_pool.py` — `_Account`: `last_read_ok_at: float | None = None`,
   `consecutive_read_failures: int = 0`. `AccountState` += `"failing"`. `note_read_success()` (reset
   failures, stamp clock) + `note_read_failure(reason)` (increment, set `last_error_reason`).
   `account_statuses()`: after quarantine/cooling checks, classify live accounts as `failing` when
   `consecutive_read_failures >= POOL_FAILING_THRESHOLD` OR (`last_read_ok_at is None` and
   `last_error_reason` and the account has been live longer than the no-read window — track a
   `created_at`-style first-seen monotonic if needed, keep minimal). Else `healthy`.
3. `reader.py` — in `_read_one`, after the successful `iter_messages` loop call `note_read_success()`
   alongside `report_success()`; in the transient (`auth_error`) catch site call
   `note_read_failure(type(exc).__name__)` before `_emit_health_best_effort(...)`. No new control flow.
4. `signal_latency.py`/`observability/tasks.py` — after `emit_ingest_staleness`, write
   `{stale, age_s}` JSON to `INGEST_STALENESS_REDIS_KEY` with TTL (best-effort).
5. `pool_health.py` — in `_publish_snapshot`, read `INGEST_STALENESS_REDIS_KEY` best-effort; set
   `ingest_contradiction = (healthy == size) and stale`. Confirm metric emitted once per cycle.
6. `pool_admin.py` — add `ingest_contradiction` to `_PoolHealthSnapshot` + `PoolHealthResponse`;
   widen the `state` doc string to mention `failing`.
7. `lib.ts` — `AccountState` += `failing`; label "Failing"; badge variant `warning` (distinct from
   quarantined `danger`); `asAccountState` accepts it.
8. `pool-health-table.tsx` — relabel summary; render `failing` reason; `ingest_contradiction` banner.
9. Tests (TDD: failing test first) — see Test plan.

## Invariants
- Rotation, cooldown, and permanent-quarantine semantics are byte-for-byte unchanged.
- `failing` is observational; it NEVER changes what `acquire()` returns this story.
- Snapshot carries NO secrets; per-account identity is the stable pool index only.
- Self-observation never crashes the collect-tick (best-effort; mirror existing patterns).

## Edge cases
- Empty pool → `account_statuses()` == `[]`; `ingest_contradiction == false` (no accounts → not "all
  healthy"). Decide: with `size == 0`, `healthy == size == 0` would be vacuously "all healthy" —
  guard `ingest_contradiction` with `size > 0`.
- Account recovers (one clean read) → failures reset to 0 → state returns to `healthy` even if the
  reason text lingers (last-known).
- Ingest-staleness key missing/expired (cold start, or its task hasn't run) → `ingest_contradiction =
  false` (fail-open; never alarm on absence).
- FLOOD_WAIT is NOT a read failure for the failing-counter — it is cooling; do not increment
  `consecutive_read_failures` in the flood branch (only the genuine transient-error branch).

## Test plan
- unit `test_account_pool.py`: failing after N failures; success resets; flood-wait does not increment
  failing; `failing` precedence vs cooling/quarantined; empty pool.
- unit pool-health test: `ingest_contradiction` true when all-healthy + stale key; false when key
  absent / not-all-healthy; single-emit assertion (metric logged once per cycle).
- reader unit: transient catch site increments failing + sets reason; clean read stamps success.
- FE `lib` vitest: `failing` label/variant/narrowing.

## Checkpoints
current_step: 4
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: "feat/pool-health-revive"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — full suite + ruff + mypy strict + FE typecheck/vitest green)
- [ ] 5 review (code-reviewer)
- [ ] 5.5 security (snapshot index-only; confirm no secret/identity leak)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details (initial)
The honesty fix is the foundation TASK-120's revive UI relies on to SHOW the status flip: a revived
account must visibly leave `failing`/`quarantined` and enter `healthy`. Keep `failing` purely
observational here so a false positive can never starve the pool before revive exists. The
ingest-staleness contradiction is the single most operator-meaningful signal from the incident
("all green but 0 posts") — surface it as a derived flag, computed cheaply from an existing metric,
never by adding a DB query to the hot collect path.

## Details (do — step 3, 2026-06-16)
Implemented TDD (RED→GREEN), smallest diff. All gates green (see below).

What changed (per-file, matches Scope):
- `collector/constants.py` — `POOL_FAILING_THRESHOLD=5`, `POOL_FAILING_NO_READ_WINDOW_SECONDS=1800`
  (via `_..._MINUTES`), `INGEST_STALENESS_REDIS_KEY="ingest:staleness:latest"`,
  `INGEST_STALENESS_TTL_SECONDS=900` (named, no magic literals).
- `account_pool.py` — `_Account` += `last_read_ok_at: float|None`, `consecutive_read_failures: int`,
  `first_read_failure_at: float|None` (annotation-only). `AccountState` += `"failing"`. New
  `note_read_success()` (stamp clock + reset failures/window) and `note_read_failure(reason)`
  (increment + stamp first-failure window start + set `last_error_reason`). `account_statuses()`
  classifies a LIVE account `failing` via pure `_is_failing()` AFTER quarantine/cooling (precedence
  preserved). `acquire()`/rotation/cooldown/quarantine BYTE-FOR-BYTE unchanged.
- `reader.py` — `note_read_success()` after the clean iteration loop (beside `report_success()`);
  `note_read_failure(type(exc).__name__)` at the previously-silent transient `auth_error` branch AND
  the mid-iteration transient branch. Cadence fix: `_emit_health_best_effort(emit_metric=...)` — the
  once-per-tick `read()`-end call keeps `emit_metric=True`; the notify-only sites (auth_error /
  all_flood / pool_exhausted / auth_dead) pass `emit_metric=False` so they only throttle-notify and
  no longer re-emit the metric/snapshot per-channel/acquire (the ~1 emit/sec fix).
- `signal_latency.py` — new `publish_ingest_staleness(redis, {stale, age_s})` writes the small bridge
  key with TTL (best-effort). `observability/tasks.py` calls it after `emit_ingest_staleness`.
- `pool_health.py` — `_publish_snapshot` adds `ingest_contradiction` via `_ingest_contradiction()`:
  true iff `size>0 and healthy==size` AND the bridge key says `stale` (fail-open on
  missing/expired/malformed/Redis-error). Single-emit semantics confirmed.
- `pool_admin.py` — `_PoolHealthSnapshot` += `ingest_contradiction: bool=False` (extra="ignore" →
  legacy snapshot still validates), `PoolHealthResponse` += `ingest_contradiction`, `state` doc
  widened to mention `failing`. OpenAPI dump + gen types regenerated (additive +5/+5).
- FE `lib.ts` — `AccountState` += `failing`; `asAccountState`/`accountStateLabel`("Failing")/
  `accountStateBadgeVariant`(warning, distinct from quarantined danger). `pool-health-table.tsx` —
  summary relabelled "{healthy} of {target} target healthy"; last-error column renders for `failing`
  too; new `ingest_contradiction` alert banner.

Tests added: `tests/unit/collector/test_account_pool_failing.py` (11),
`tests/unit/collector/test_reader_read_outcome.py` (3), `+4` in `test_pool_health.py`, `+2` in
integration `test_pool_admin_api.py`, FE `tests/unit/pool-admin/lib.spec.ts` (4).

Gates: `make fmt/lint/typecheck` green; `make test` = 1117 passed; FE `tsc -b`/`eslint`/`vitest`
= 306 passed; `openapi-drift-check` idempotent (only the additive field). Rotation invariant verified
by the unchanged `test_account_pool_rotation.py` + `test_auth_quarantine.py` (still pass).

Decision recorded: `failing` is OBSERVATIONAL — `test_failing_does_not_change_acquire` pins that a
failing account is still handed out by `acquire()`.
