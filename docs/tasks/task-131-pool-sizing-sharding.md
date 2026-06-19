---
id: TASK-131
title: Pool sizing + deterministic channel sharding
status: planned
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
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
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — determinism + fallback + no rotation regression)
- [ ] 5 review (auto, adversarial)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
