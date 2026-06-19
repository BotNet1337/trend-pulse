---
id: TASK-132
title: factory_accounts table + store (state machine)
status: planned
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [account-factory, storage, state-machine, probation, layer-b]
---

# TASK-132 — `factory_accounts` table + store (Layer B3)

> Durable state for accounts the factory is provisioning: a state machine
> `purchased → registered → probation → promoted → failed/banned`, with the encrypted session, masked
> phone, provider order, proxy, and probation deadline. Source-of-truth for the factory loop + API.

## Context
The live pool reads `pool_sessions`. The factory needs its OWN table so an account can be held on
probation **before** it ever enters the pool. Mirror `pool_sessions` conventions
(`storage/models/pool_sessions.py`, `EncryptedString` ADR-008, `storage/pool_session_store.py`
repository style, `tests/integration/test_pool_session_store.py` test style). Migration head `0027`
(after TASK-130) → this is `0028`.

## Goal
`factory_accounts` table + `factory_account_store.py` repository with typed create/transition/list/get.
Encrypted `session_string`; masked `phone`; `state` constrained to the named set; `probation_until`
timestamp; `cost_usd` for budget accounting (TASK-134); `last_error`; `provider`/`provider_order_id`;
`proxy`; `tg_user_id`. State transitions validated (illegal transition → domain error).

## Discussion
- Q: Separate table or reuse pool_sessions? → A: separate → Decision: probation lifecycle ≠ live-pool
  lifecycle; promotion COPIES the session into `pool_sessions` via `upsert_revive_or_add(source='auto')`.
- Q: Store phone in clear? → A: no → Decision: store masked (`+79*****1234`); full number not persisted
  after registration (compliance + minimise secret surface).
- Q: Cost field here? → A: yes → Decision: `cost_usd Numeric` per account → budget sum is a query, not an estimate.
- Q: State set? → A: `purchased|registered|probation|promoted|failed|banned` with a `FactoryState` const + transition map.

## Scope
- Touch ONLY: `migrations/versions/0028_factory_accounts.py` (new, down_revision `0027`);
  `storage/models/factory_accounts.py` (new ORM); `storage/factory_account_store.py` (new repo);
  `factory/constants.py` (new — state names, transition map, col widths).
- Do NOT touch: pool/collector/API/UI yet (TASK-134/135 consume this).
- Blast radius: new table only (no existing-schema change).

## Acceptance Criteria
- [ ] Migration `0028` creates `factory_accounts` (encrypted `session_string`, masked `phone`, indexes
      on `state` and `probation_until`); applies and rolls back.
- [ ] Store: `create_purchased(...)`, `transition(id, to_state)` (rejects illegal transitions),
      `list_by_state(...)`, `get(id)`, `total_spent_usd()`.
- [ ] `session_string` persisted as Fernet ciphertext (raw-SQL assert); `phone` stored masked only.
- [ ] Illegal transition (e.g. `purchased → promoted`) raises `IllegalFactoryTransitionError`.

## Plan
1. `factory/constants.py` — `FactoryState` names + `ALLOWED_TRANSITIONS` map + col widths.
2. `storage/models/factory_accounts.py` — ORM (id, phone_masked, provider, provider_order_id, proxy,
   tg_user_id nullable, session_string EncryptedString nullable, state, probation_until, cost_usd,
   created_at, updated_at, last_error).
3. `migrations/versions/0028_factory_accounts.py` — create table + indexes.
4. `storage/factory_account_store.py` — typed repo + transition validation + `total_spent_usd`.

## Invariants
- Session encrypted at rest; full phone never persisted; transitions follow `ALLOWED_TRANSITIONS`.
- Repository is the only writer (no raw SQL elsewhere).

## Edge cases
- Concurrent transition → guarded by row state check (optimistic); illegal → domain error.
- Promotion (`probation → promoted`) only legal transition into terminal-success.

## Test plan
- unit: transition map legal/illegal; masking; `total_spent_usd` sum.
- integration: `0028` round-trip + ciphertext assert (mirror `test_pool_session_store.py`).

## Checkpoints
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — migration round-trip + ciphertext + transition rejection)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (encrypted session + PII phone masking)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
