---
id: TASK-115
title: Per-account pool health snapshot + last-error reason + Redis emit
status: planned
owner: backend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
tags: [telegram, pool, observability, redis]
---

# TASK-115 — Per-account pool health snapshot + Redis bridge

> Expose a read-only per-account status (state, last-error reason, cooldown remaining) from
> `AccountPool`, record the last error reason where errors are caught, and publish the snapshot to
> Redis each collect-tick so the API process can read it.

## Context
Part of EPIC-TG-QR-POOL. The pool lives in the Celery worker process; the API can't read it
directly, so health crosses processes via Redis. `AccountPool` already exposes `cooling_count` /
`quarantined_count` (`account_pool.py:88-106`) and `_Account` holds `cooldown_until`,
`flood_strikes`, `quarantined` (`account_pool.py:30-46`). Errors are caught in
`collector/telegram/reader.py` (quarantine on `is_permanent_auth_error`, flood-wait reporting).
Aggregates are already emitted by `observability/pool_health.py`.

## Goal
1. `_Account` gains a `last_error_reason: str = ""` field; reader populates it (the permanent-error
   class name, or `"FLOOD_WAIT"`) at the existing catch sites — WITHOUT changing rotation behavior.
2. `AccountPool.account_statuses()` returns a list of frozen `AccountStatus(index, state,
   cooldown_remaining_seconds, last_error_reason)` where `state ∈ {healthy, cooling, quarantined}`.
   Read-only, no mutation, no secrets.
3. The collector publishes the snapshot (aggregates + per-account list) to a fixed Redis key
   (`pool:health:latest`) as JSON each tick, with a TTL, so the API can read the freshest state.

## Discussion
- Q: keep historical errors or last only? → A: last only (`last_error_reason`), reset is not
  required — keep most recent for debugging.
- Q: where to emit to Redis? → A: extend the existing pool-health emit path
  (`observability/pool_health.py` is already called from the collect-tick); add a Redis write of the
  full snapshot. Reuse the worker's existing Redis client wiring — do not open a new connection
  pattern; mirror how the collector already uses Redis.
- Q: TTL? → A: a named-constant seconds TTL (e.g. a few minutes) so a dead worker's snapshot ages out
  and the API can show "stale".

## Scope
- Touch ONLY:
  - `backend/src/collector/telegram/account_pool.py` (add `AccountStatus`, `last_error_reason` field,
    `account_statuses()`)
  - `backend/src/collector/telegram/reader.py` (set `last_error_reason` at existing catch sites)
  - `backend/src/observability/pool_health.py` (include per-account list; write snapshot to Redis)
  - `backend/src/collector/constants.py` (snapshot TTL / Redis key as named constants)
  - tests: extend `backend/tests/unit/test_account_pool.py` (+ pool_health test if present)
- Do NOT touch: rotation logic (`acquire`/`report_flood_wait`/`quarantine_current` behavior),
  the API, the QR service.
- Blast radius: `pool_health.emit_*` return shape grows (additive). Confirm no consumer asserts exact
  keys. Redis key is new.

## Acceptance Criteria
- [ ] Given a pool with 1 healthy, 1 cooling (cooldown_until>now), 1 quarantined account, When
      `account_statuses()` is called, Then it returns 3 `AccountStatus` with the correct `state`,
      cooldown seconds only for the cooling one, and the recorded `last_error_reason`.
- [ ] Given the reader quarantines an account on a permanent auth error, When inspected, Then that
      account's `last_error_reason` equals the error class name (e.g. `AuthKeyDuplicatedError`).
- [ ] Given the reader reports a flood-wait, Then that account's `last_error_reason == "FLOOD_WAIT"`.
- [ ] Given a collect-tick runs, When it completes, Then `pool:health:latest` in Redis holds JSON
      with `size/healthy/cooling/quarantined` and an `accounts` list, and the key has a TTL.
- [ ] Rotation behavior is unchanged (existing `test_account_pool.py` still passes).
- [ ] No session string / api_hash in the snapshot (index is the only per-account identifier).

## Plan
1. `account_pool.py` — add `last_error_reason: str = ""` to `_Account`; add frozen
   `AccountStatus` dataclass; add `account_statuses()` (mirror `cooling_count` clock logic).
2. `reader.py` — at the permanent-auth-error catch, set
   `self._pool._accounts[self._pool._index].last_error_reason = type(exc).__name__` BEFORE
   `quarantine_current()`; at the flood-wait branch set `"FLOOD_WAIT"`. Keep all existing behavior.
   (Prefer a tiny pool helper `note_current_error(reason)` over reaching into `_accounts` if it reads
   cleaner — decide in `do`, keep it minimal.)
3. `observability/pool_health.py` — add `accounts=[asdict(s) for s in pool.account_statuses()]` to the
   emitted dict; write the full snapshot JSON to Redis `pool:health:latest` with TTL.
4. `collector/constants.py` — `POOL_HEALTH_REDIS_KEY = "pool:health:latest"`,
   `POOL_HEALTH_SNAPSHOT_TTL_SECONDS = <named>`.
5. Tests — extend `test_account_pool.py` for `account_statuses()` + `last_error_reason`; add/extend a
   pool_health test asserting the Redis write (fake redis) and snapshot shape.

## Invariants
- Rotation, cooldown, and quarantine semantics are byte-for-byte unchanged.
- Snapshot contains NO secrets; per-account identity is the stable pool index only.
- Reason is set at the SAME place the existing handling happens — no new control flow.

## Edge cases
- Empty pool → `account_statuses()` returns `[]`; snapshot has empty `accounts`.
- Account healthy again after cooldown → `state=healthy`, `cooldown_remaining=None`, but
  `last_error_reason` may still show the prior reason (acceptable — last-known).
- Redis write failure → log + continue (never break the collect-tick); mirror existing best-effort.

## Test plan
- unit: `test_account_pool.py` (statuses + reason), `test_pool_health` (snapshot shape + fake-redis
  write + TTL). Reader reason-setting covered via existing reader unit harness or a focused test.

## Checkpoints
current_step: 4
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + lint + typecheck)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (no auth/secret surface — likely N/A)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### 3 do (TDD, GREEN)
Smallest-diff implementation across the 4 declared source files + 3 test files.

- **`collector/constants.py`** — added `POOL_HEALTH_REDIS_KEY = "pool:health:latest"` and
  `POOL_HEALTH_SNAPSHOT_TTL_SECONDS = 5 * 60` (300s, via private `_POOL_HEALTH_SNAPSHOT_TTL_MINUTES`).
- **`collector/telegram/account_pool.py`** —
  - `_Account` gained `last_error_reason: str = ""` (last-known only; never a secret).
  - new `AccountState = Literal["healthy","cooling","quarantined"]` + frozen `AccountStatus`
    dataclass `(index:int, state, cooldown_remaining_seconds: float|None, last_error_reason:str)`.
  - `account_statuses() -> list[AccountStatus]` mirrors the `cooling_count` clock logic
    (quarantine precedes cooling; cooldown seconds only for cooling; index-only identity; empty
    pool → `[]`).
  - `note_current_error(reason)` helper sets the reason on the CURRENT account (no rotation/cooldown
    /quarantine change) — keeps the reader from reaching into `_accounts`.
- **`collector/telegram/reader.py`** — at the EXISTING catch sites only: `note_current_error(
  type(exc).__name__)` before `quarantine_current()` (in `_quarantine_dead_account`), and
  `note_current_error("FLOOD_WAIT")` before each `report_flood_wait(...)` (both flood branches),
  set BEFORE the call that rotates `_index`. `_emit_health_best_effort` now passes `self._redis`
  into `emit_pool_health`. No new control flow.
- **`observability/pool_health.py`** — `emit_pool_health(pool, settings, redis=None)`; return
  shape unchanged. When `redis` is given, `_publish_snapshot` writes JSON to
  `POOL_HEALTH_REDIS_KEY` with `ex=POOL_HEALTH_SNAPSHOT_TTL_SECONDS`. Snapshot = aggregates +
  `as_of` (UTC ISO) + `accounts` (`[asdict(s) for s in pool.account_statuses()]`). Best-effort:
  `RedisError|TypeError|ValueError` → warn + continue (never breaks the collect-tick).

### Verify
`make fmt` (clean) · `make lint` (All checks passed) · `make typecheck` (Success: no issues in 186
files) · `make test` (**1100 passed**, 279 deselected). Existing rotation/quarantine/pool-health
tests pass unchanged.

### Schema (for TASK-116)
See `cache/tgqr-notes-task-115.md` — exact Redis key, JSON field types, TTL, and how the API
should read/parse and compute staleness from `as_of`.
