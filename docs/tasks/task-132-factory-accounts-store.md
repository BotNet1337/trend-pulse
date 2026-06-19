---
id: TASK-132
title: factory_accounts table + store (state machine)
status: done
owner: backend
created: 2026-06-19
updated: 2026-06-20
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
- [x] Migration `0028` creates `factory_accounts` (encrypted `session_string`, masked `phone`, indexes
      on `state` and `probation_until`); applies and rolls back. (verify: `test_factory_accounts_migration_up_down` live PG)
- [x] Store: `create_purchased(...)`, `transition(id, to_state)` (rejects illegal transitions),
      `list_by_state(...)`, `get(id)`, `total_spent_usd()`. (all in `storage/factory_account_store.py`, unit+integration tested)
- [x] `session_string` persisted as Fernet ciphertext (raw-SQL assert); `phone` stored masked only. (verify: `test_session_stored_as_ciphertext` live PG `gAA...`; `test_phone_stored_masked_only`)
- [x] Illegal transition (e.g. `purchased → promoted`) raises `IllegalFactoryTransitionError`. (`test_illegal_transition_purchased_to_promoted_raises`)

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
current_step: done
baseline_commit: 4007b06585ba0564c735130d006e82a2e9403865
branch: "gsd/phase-132-factory-accounts-store"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — migration round-trip + ciphertext + transition rejection)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (encrypted session + PII phone masking)
- [x] 6 ship (PR #197 merged --admin)
- [x] 7 learnings (auto)
debug_runs: []

## Details

### do (TDD, opus)
Created: `factory/__init__.py`, `factory/constants.py` (FactoryState Final consts + FACTORY_STATES frozenset + ALLOWED_TRANSITIONS + col widths), `factory/errors.py` (FactoryError/FactoryAccountStoreError/FactoryAccountNotFoundError/IllegalFactoryTransitionError), `storage/models/factory_accounts.py` (FactoryAccount ORM — EncryptedString session_string/proxy, masked phone, Numeric(10,2) cost_usd, indexes on state + probation_until), `storage/factory_account_store.py` (frozen FactoryAccountRecord DTO repr=False on secrets; create_purchased/transition/get/list_by_state/total_spent_usd), `migrations/versions/0028_factory_accounts.py` (rev 0028 ← 0027, local constants). Edited: `storage/models/__init__.py` (register + __all__), `tests/integration/test_migrations.py` (factory_accounts in _EXPECTED_TABLES + test_factory_accounts_migration_up_down), `tests/unit/test_models.py` (schema-completeness set). Tests: `tests/unit/storage/test_factory_account_store.py` (15) + `tests/integration/test_factory_account_store.py` (2). No Any / no `# type: ignore` / no magic literals.

### verify (G2, sonnet) — PASS, all 6 ACs
- ci-fast: ruff format `405 files already formatted`; ruff check `All checks passed!`; mypy `Success: no issues found in 191 source files`; pytest `1301 passed, 316 deselected`.
- Live Postgres integration: `8 passed` (test_factory_account_store.py 2 + test_migrations.py 6).
- Migration 0028 up/down on live PG: `test_factory_accounts_migration_up_down` — upgrade creates table + ix_factory_accounts_state + ix_factory_accounts_probation_until, downgrade→0027 drops it, re-upgrade restores. `alembic current` = `0028 (head)` (full 0001→0028 chain clean).
- Ciphertext-at-rest on real PG: `test_session_stored_as_ciphertext` — raw SELECT returns Fernet token `gAA...`, ORM read decrypts.
- Illegal transition: `test_illegal_transition_purchased_to_promoted_raises` + `..._registered_to_promoted_raises` → `IllegalFactoryTransitionError`.
- total_spent_usd: `test_total_spent_usd_sums_on_postgres` — Decimal('1.50')+Decimal('2.25')=Decimal('3.75') on real PG NUMERIC.
- Masked phone: `test_phone_stored_masked_only` — `+79*****1234` stored as-is, no raw-phone leak.

### review (python-reviewer, opus) — PASS (no CRITICAL/HIGH)
All CONVENTIONS hard rules PASS; scope contained; state-machine/migration audits clean. Folded in 2 MEDIUM + 1 security-LOW (below). Remaining LOWs are pre-existing patterns / belt-and-suspenders (no change): `text()` DROP-TABLE in test_migrations (trusted pg_tables, pre-existing) and the unreachable None-branch in `total_spent_usd` (coalesce guarantees non-NULL).

### security (security-reviewer, opus) — PASS (no CRITICAL/HIGH)
(a) `session_string` + `proxy` encrypted at rest via EncryptedString (Fernet, ADR-008) ✅; (b) both repr-suppressed, never in any log `extra` ✅; (c) full phone never persisted (only `phone_masked` column/param) ✅. MEDIUM (pre-existing, NOT this diff): `EncryptedString.process_result_value` InvalidToken fallback returns raw value — inherited from pool_sessions, deferred (would touch shared encryption.py).

### follow-up do (opus) — 3 improvements, re-verified green
1. State machine: `purchased → banned` now LEGAL (provider can ban a slot pre-registration, e.g. VoIP); comment fixed; `purchased→promoted`/`→probation` remain illegal (tested).
2. PII boundary guard: `create_purchased` raises new domain error `FactoryAccountValidationError` when `phone_masked` lacks the mask char (`FACTORY_PHONE_MASK_CHAR: Final = "*"`); message omits the PII value (tested).
3. Proxy repr test: asserts proxy creds (`secretpass`/`socks5://`) absent from `repr(record)` (tested).
Re-verify: ci-fast `1305 passed`; integration `8 passed` (migration up/down + ciphertext + total_spent_usd on live PG) with `POSTGRES_HOST` override.
