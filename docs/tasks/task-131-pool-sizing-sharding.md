---
id: TASK-131
title: Pool sizing + deterministic channel sharding
status: review
owner: backend
created: 2026-06-19
updated: 2026-06-20
baseline_commit: 76e569da0a0e02794f05fac3849a9b858f66a960
branch: "gsd/phase-131-pool-sizing-sharding"
tags: [telegram, pool, sharding, throughput, floodwait, layer-a]
---

# TASK-131 — Pool sizing + channel sharding (Layer A2)

> Raise pool ceiling/target and **shard channels across accounts** so reads parallelise and FLOOD_WAIT
> per account drops — instead of every channel cycling through one shared rotation.

## Context
`collector/constants.py:27-28` `POOL_MIN`/`POOL_MAX`. `config.py` `pool_min_healthy`
(`_DEFAULT_POOL_MIN_HEALTHY=3`, line 401). Collector `collector/telegram/reader.py` reads each ref
via `pool.acquire()` round-robin — no channel→account affinity, so all refs contend on the same
cooldowns. `AccountPool` rotation/quarantine must stay intact.

## Goal
`POOL_MAX→20`, `pool_min_healthy` default →5; a **deterministic** channel→slot assignment so a given
channel is preferentially read by a stable subset of healthy accounts (spreads load, cuts FLOOD_WAIT),
falling back to normal rotation when the preferred slot is cooling/quarantined. No regression to
rotation, backoff, or quarantine semantics.

## Discussion
- Q: Sharding strategy? → A: stable hash → Decision: `shard_index = stable_hash(channel_handle) %
  healthy_count`, pick that healthy slot; if unavailable → existing `acquire()` rotation. Pure helper
  `pick_slot_for_channel()` so it's unit-testable and deterministic.
- Q: Raise `POOL_MIN` too? → A: no → Decision: keep `POOL_MIN=1` (correct dev floor, per TASK-059);
  only `POOL_MAX` + `pool_min_healthy` change. Target size is operational, not a hard min.
- Q: Risk of pinning a channel to a dead slot? → A: mitigated → Decision: fallback to rotation; never
  block a read because the preferred slot is down.

## Scope
- Touch ONLY: `collector/constants.py` (`POOL_MAX=20`); `config.py` (`_DEFAULT_POOL_MIN_HEALTHY=5`);
  `collector/telegram/account_pool.py` (add `acquire_for_channel(handle)` / `pick_slot_for_channel`
  helper using healthy slots; keep `acquire()` as fallback); `collector/telegram/reader.py`
  (call channel-aware acquire in `_read_one`).
- Do NOT touch: schema, proxy (129), source (130), API/UI, FLOOD_WAIT backoff math.
- Blast radius: collector read path only (internal). No schema/API change.

## Acceptance Criteria
- [ ] Given N healthy accounts and a channel handle, When picking a slot, Then the same handle maps to
      the same slot deterministically (unit asserts stability across calls).
- [ ] Given the preferred slot is cooling/quarantined, When reading, Then it falls back to rotation and
      the read still proceeds (no exception, no skipped ref vs today).
- [ ] Given two distinct channels, When healthy_count>1, Then they can map to different slots (load spread asserted).
- [ ] `POOL_MAX=20`, `pool_min_healthy` default `5`; existing rotation/quarantine tests still green.

## Plan
1. `collector/constants.py` — `POOL_MAX = 20`.
2. `config.py` — `_DEFAULT_POOL_MIN_HEALTHY = 5`.
3. `account_pool.py` — pure `pick_slot_for_channel(handle, healthy_slots)` + `acquire_for_channel(handle)`
   (prefer mapped healthy slot, else `acquire()`).
4. `reader.py` — `_read_one` uses `acquire_for_channel(ref.handle)`.

## Invariants
- All existing rotation/cooldown/quarantine behaviour preserved (fallback path == today).
- Deterministic mapping (no `random`); pure helper, no I/O.

## Edge cases
- healthy_count==0 → behave exactly as today (AllAccountsFloodWaitError / PoolExhausted).
- healthy_count==1 → mapping trivially that slot (== today).

## Test plan
- unit: `pick_slot_for_channel` determinism + distribution; `acquire_for_channel` fallback when slot down.
- regression: run existing `test_account_pool_rotation.py` / `test_auth_quarantine.py` green.

## Checkpoints
current_step: 6
baseline_commit: 76e569da0a0e02794f05fac3849a9b858f66a960
branch: "gsd/phase-131-pool-sizing-sharding"
lock: "agent-a14b9d477b61677df"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — determinism + fallback + no rotation regression)
- [x] 5 review (auto, adversarial — PASS, no CRITICAL/HIGH; NIT assertion strengthened)
- [x] 5.5 security — N/A (no auth/secrets/input/crypto/public-API; sha256 used only for load distribution, not a security decision)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### do (stage 3) — TDD, implemented
- `collector/constants.py`: `POOL_MAX` 10→20 (+ comment updated to "3..20", TASK-131 note).
- `config.py`: `_DEFAULT_POOL_MIN_HEALTHY` 3→5 (+ comment updated).
- `collector/telegram/account_pool.py`:
  - pure module-level `pick_slot_for_channel(handle, healthy_slots) -> int | None`:
    `healthy_slots[ int(sha256(handle),16) % len(healthy_slots) ]`; `None` on empty list.
    Cross-process stable (sha256, NOT builtin `hash()`); no I/O, no randomness, pure.
  - `AccountPool.acquire_for_channel(handle)`: computes healthy slots
    (`not quarantined and cooldown_until <= now`), picks via the pure helper, sets
    `self._index` (so note_read_*/report_flood_wait annotate the right account), and
    FALLS BACK to `self.acquire()` (identical AllAccountsFloodWaitError/PoolExhaustedError
    contract) when no healthy slot maps. NEVER mutates cooldown/quarantine/strikes.
- `collector/telegram/reader.py`: `_acquire_ready_client(self, handle)` now calls
  `self._pool.acquire_for_channel(handle)` (was `acquire()`); `_read_one` threads
  `ref.handle`. `validate_ref` left on `acquire()` (read-path sharding only, per scope).
- New unit test `tests/unit/collector/test_pool_sharding.py` (19 tests):
  determinism (algorithm pinned to sha256, asserts ≠ builtin hash), load spread (>1 slot),
  empty→None, n==1 trivial, acquire_for_channel maps to healthy slot, fallback when mapped
  slot cooling/quarantined (read proceeds, returns live non-cooling/non-quarantined client),
  all-cooling→AllAccountsFloodWaitError, all-quarantined→PoolExhaustedError.

### Deviation (test-mechanics, intent preserved)
Wiring `acquire_for_channel` into the reader changed WHICH slot a handle acquires.
Existing reader regression tests pin the dead/erroring account at index 0 and asserted it
is acquired first under `@news` — but `@news` → slot 1 (n=2). Changed the shared handles so
the index-0 account stays the mapped (acquired) slot, preserving each test's
dead/flood→quarantine/rotate→healthy intent unchanged:
- `test_auth_quarantine.py` `_REF`: `@news` → `@dead` (slot 0 for n=1,2,3).
- `test_account_pool_rotation.py` `_REF` + inline read handle: `@news` → `@ch` (slot 0 for n=1,2,3).
- `test_reader_read_outcome.py` (`@alpha`, all single-slot pools): UNCHANGED (slot 0 trivially).
No production semantics weakened; only the test handle is chosen so the account-under-test
is the deterministically-mapped slot.

### verify (stage 4, G2) — PASS
`make ci-fast` fully green:
- ruff format --check: 397 files already formatted.
- ruff check: passed.
- mypy: Success: no issues found in 189 source files (+ dump_openapi.py).
- pytest -m 'not integration': **1286 passed, 313 deselected, 23 warnings** (pre-existing).
Targeted suites: `test_pool_sharding.py` (19) + `test_account_pool_rotation.py` +
`test_auth_quarantine.py` + `test_reader_read_outcome.py` = 58 passed; full collector
unit suite 300 passed. Determinism + load-spread + fallback (cooling/quarantined) +
all-cooling→AllAccountsFloodWaitError + all-quarantined→PoolExhaustedError all asserted.
No migration/API change → no curl/Playwright required; behavior asserted via unit tests.

### review (stage 5, opus) — PASS, no CRITICAL/HIGH
Verified: acquire_for_channel never mutates cooldown/quarantine/strikes (only self._index);
eligibility predicate matches acquire()/cooling_count; fallback preserves exact exception
contract; sha256 (not builtin hash); self._index makes the mapped slot "current" so
note_read_*/report_flood_wait/quarantine_current act on the right account; scope clean.
- NIT (fixed): weak fallback-cooling assertion strengthened to
  `assert returned_slot != preferred` + `cooldown_until <= now`.
- LOW (no change, by design): a live-but-`failing` (TASK-118) slot is eligible for sharding,
  identical to acquire() semantics — acquire() is explicitly UNAFFECTED by `failing`. Keeping
  the two paths aligned; any "avoid failing slots" policy is a separate task.
Security stage 5.5: N/A — no auth/authz/secrets/input/crypto/public-API surface; sha256 is a
load-distribution hash, not a security control.
