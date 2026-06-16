---
id: TASK-120
title: Revive API + frontend — identity, REVIVE/ADD outcome, in-place status flip
status: planned
owner: backend+frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: ""
tags: [telegram, pool, qr-login, revive, api, frontend]
---

# TASK-120 — Revive API + frontend (same account re-connected, not a new row)

> The QR poll/complete path persists the minted session via the store (TASK-119) and returns the
> account identity + whether it was a REVIVE (existing account) or ADD (new). Pool-health exposes a
> per-account non-secret identity so the UI shows WHICH account each row is. The "Add account" flow
> becomes "Add / re-connect account": after scan+success the matching row flips to Connected and the
> UI makes it clear it is the SAME account re-connected.

## Context
Part of EPIC-POOL-HEALTH-REVIVE; the thin surface over TASK-119's store + revive and TASK-118's
honesty. The API router is `backend/src/api/routes/pool_admin.py` (superuser-gated: `start_qr_login`,
`poll_qr_login`, `get_pool_health`), with pydantic boundary models (`extra="forbid"`) and the
`session_string` served only on SUCCESS (the existing one-shot superuser copy-field). The FE is
`frontend/src/features/pool-admin/` (`api.ts`, `queries.ts`, `lib.ts`, `ui/qr-login-dialog.tsx`,
`ui/pool-health-table.tsx`) + `frontend/src/pages/admin/pool.tsx`. TASK-119 gives the poll-success
result `tg_user_id`/`display_label` and the store's `ReviveOutcome`; this story persists on success
and returns identity+outcome, and adds per-account identity to the health snapshot+API+UI.

## Goal
1. **QR poll completion persists + classifies**: on a SUCCESS poll, the API calls the store
   (TASK-119) `upsert_revive_or_add(...)` and returns, in `QRLoginPollResponse`, the non-secret
   `tg_user_id` + `display_label` + `outcome: "revive" | "add"`. The `session_string` copy-field stays
   (the owner can still copy it to the vault as the disaster-recovery floor), but the persistence is
   now automatic. A revive ALSO writes the worker revive-signal (TASK-119) so the live slot flips.
2. **Per-account identity in pool-health**: the snapshot/`PoolHealthAccount` gains a non-secret
   `display_label` (masked id / `@username`) and optional `tg_user_id` so the UI labels each row by
   account, not just by index. Identity is sourced from the store (worker side) and carried in the
   snapshot; NEVER the session string.
3. **FE "Add / re-connect account"**: relabel the button + dialog; after a SUCCESS poll the dialog
   shows the identity + whether it was a REVIVE ("re-connected <label>") or ADD ("added <label>"),
   invalidates the pool-health query so the table refetches, and the matching row's state flips to
   Connected. The table shows the per-account `display_label` column.

## Discussion
- Q: still expose the raw `session_string` in the poll response? → A (default): YES, keep the existing
  one-shot superuser copy-field — it is the documented disaster-recovery floor (paste into the env
  vault). Persistence is now automatic on top; the field is unchanged (secret, never logged, superuser
  + HTTPS only). **Owner-flag:** if they want to DROP the copy-field now that persistence is automatic,
  that is a one-line removal — default is keep-for-DR.
- Q: where does the UI learn "this row is now Connected after my scan"? → A: invalidate
  `POOL_HEALTH_QUERY_KEY` on poll-success; the worker applies the revive on its next tick and the next
  snapshot shows the slot healthy. There may be a one-tick lag (the dialog says "re-connected — the
  pool will show Connected within ~one collect cycle"). Honest, no fake optimistic flip.
- Q: identity privacy? → A: `display_label` is a MASKED id / public `@username` from `get_me()` — not
  a phone number, not the session. `tg_user_id` is the account's public numeric id (non-secret).
- Q: revive vs add detection lives where? → A: the STORE (TASK-119) decides by `tg_user_id`; the API
  just surfaces the outcome. No duplicate detection logic in the API/UI.

## Scope
- Touch ONLY:
  - `backend/src/api/routes/pool_admin.py` — on SUCCESS poll, call the store + write the revive-signal;
    `QRLoginPollResponse` += `tg_user_id: int | None`, `display_label: str | None`,
    `outcome: str | None` ("revive"/"add"); `PoolHealthAccount` += `display_label: str | None`,
    `tg_user_id: int | None`; `_PoolHealthSnapshot` mirrors (extra="ignore"). Map store over-cap /
    failure to a clear 4xx via the envelope. Inject the store + a redis client as dependencies.
  - `backend/src/observability/pool_health.py` — include per-account `display_label`/`tg_user_id`
    in the snapshot (sourced from the store/pool; non-secret only).
  - `backend/src/collector/telegram/account_pool.py` — `AccountStatus` (+ `_Account`) carry the
    non-secret `display_label`/`tg_user_id` so `account_statuses()` can surface them (additive; index
    stays the stable identifier; secrets never added).
  - `frontend/src/features/pool-admin/api.ts` — types regenerate from OpenAPI (no hand-rolled shapes).
  - `frontend/src/features/pool-admin/lib.ts` — a helper for the revive/add success message + label
    formatting.
  - `frontend/src/features/pool-admin/queries.ts` — invalidate `POOL_HEALTH_QUERY_KEY` on poll-success.
  - `frontend/src/features/pool-admin/ui/qr-login-dialog.tsx` — show identity + REVIVE/ADD outcome on
    success; relabel to "Add / re-connect account".
  - `frontend/src/features/pool-admin/ui/pool-health-table.tsx` — add the per-account label column.
  - `frontend/src/pages/admin/pool.tsx` — relabel the "Add account" button.
  - tests: `pool_admin` route tests (success → store called + outcome returned; identity in health),
    FE `lib`/`queries` vitest, dialog test.
- Do NOT touch: the store internals / revive mechanics (TASK-119), the failing-state logic (TASK-118),
  rotation/quarantine, the env vault, deploy.
- Blast radius: `QRLoginPollResponse` + `PoolHealthAccount` grow (additive, `extra` tolerant); OpenAPI
  regenerates (`make gen:api` / project's openapi step) → FE types update. The poll route now has a
  side effect (persist) on SUCCESS — keep it idempotent (the store upsert is idempotent by
  `tg_user_id`).

## Acceptance Criteria
- [ ] Given a SUCCESS QR poll for a NEW account, When the route returns, Then the store was called
      (`add`), `outcome == "add"`, and `tg_user_id`/`display_label` are present (non-secret); the
      `session_string` copy-field is still present (DR floor).
- [ ] Given a SUCCESS QR poll for an EXISTING account, When the route returns, Then `outcome ==
      "revive"`, the revive-signal was written for the worker, and NO duplicate is created (store
      upsert by `tg_user_id`).
- [ ] Given the pool-health snapshot, When served, Then each `PoolHealthAccount` carries a non-secret
      `display_label`/`tg_user_id` (or null when unknown) — never a session string.
- [ ] FE: the button/dialog read "Add / re-connect account"; on success the dialog states whether the
      account was re-connected (revive) or added, names the `display_label`, and the pool-health query
      is invalidated so the table refetches and the row shows Connected within one cycle.
- [ ] No secret in any response except the existing one-shot `session_string` copy-field; nothing
      secret logged.
- [ ] `make test` + ruff + mypy strict green; FE typecheck + vitest green; OpenAPI regenerated.

## Plan (per-file, ordered)
1. `account_pool.py` — `_Account`/`AccountStatus` += `display_label: str | None`,
   `tg_user_id: int | None` (additive; populated from the store at build/revive). No secret.
2. `pool_health.py` — include the two identity fields per account in the snapshot.
3. `pool_admin.py` — inject the store + redis; on SUCCESS poll call `upsert_revive_or_add` (map
   over-cap → 409/422 via the envelope), write the revive-signal on a revive; extend
   `QRLoginPollResponse` (`tg_user_id`/`display_label`/`outcome`) and `PoolHealthAccount`/
   `_PoolHealthSnapshot` (identity fields). Keep `session_string` copy-field.
4. Regenerate OpenAPI → FE `gen.types`.
5. `lib.ts` — success-message + label helpers (pure, unit-testable).
6. `queries.ts` — invalidate `POOL_HEALTH_QUERY_KEY` on poll-success (use the query client).
7. `qr-login-dialog.tsx` — render identity + REVIVE/ADD on success; relabel.
8. `pool-health-table.tsx` — per-account label column.
9. `pages/admin/pool.tsx` — relabel button.
10. Tests (TDD: failing test first) — see Test plan.

## Invariants
- The ONLY secret ever returned is the existing one-shot `session_string` copy-field (superuser,
  HTTPS); identity fields are non-secret (masked id / public username / numeric id).
- The API never mutates the live pool directly — it persists to the store + writes the non-secret
  revive-signal; the worker applies the swap (TASK-119).
- Pydantic validates the boundary (`extra="forbid"` on responses; the snapshot validator stays
  `extra="ignore"`). Superuser gate unchanged (401/403).
- No fake optimistic UI flip — the row flips to Connected when the worker reports it (≤ one cycle).

## Edge cases
- Store over `POOL_MAX` on add → a clear 409/422 in the dialog ("pool is full — revoke an account
  first"), not a 500.
- `display_label`/`tg_user_id` unknown for an env-only (non-store) account → null; the table shows the
  index only (graceful).
- Poll-success persistence fails (store/DB error) → surface a clear error in the dialog but the minted
  `session_string` copy-field is STILL returned (DR floor preserved) — the owner can still paste it
  into the vault.
- Worker hasn't applied the revive yet → the table shows the prior state for ≤ one cycle; the dialog
  message sets that expectation honestly.
- Polling is a loop — the persistence side effect must be idempotent (store upsert by `tg_user_id`),
  so a repeated SUCCESS poll does not create duplicates or re-fire harmful effects.

## Test plan
- route `test_pool_admin*`: SUCCESS poll for new → store `add` called + outcome/identity in body;
  SUCCESS for existing → `revive` + revive-signal written; over-cap → 409/422; session_string still
  present; no secret logged; identity in `get_pool_health`.
- FE `lib` vitest: revive vs add success message + label formatting.
- FE `queries` vitest: poll-success invalidates the pool-health key.
- FE dialog test: success state shows identity + REVIVE/ADD; button relabel.

## Checkpoints
current_step: 6
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: "feat/pool-health-revive"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (1152 unit + 25 integration + 315 FE) (G2 — full suite + ruff + mypy strict + FE typecheck/vitest + OpenAPI regen green)
- [x] 5 review (opus: HIGH rollback fixed) (code-reviewer)
- [x] 5.5 security (opus PASS clean) (MANDATORY — confirm only the one-shot session copy-field is secret; identity
      non-secret; persistence side effect idempotent)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details (initial)
This story is intentionally thin: all the danger lives in TASK-119 (the live swap) and TASK-118 (the
honesty model). Here we only (a) persist on success + classify revive/add via the store, (b) carry
non-secret identity into the snapshot/UI, and (c) make the UX say the truth — "same account
re-connected" with at most a one-cycle lag, no fake optimistic flip. The one-shot `session_string`
copy-field is kept as the disaster-recovery floor (paste into the env vault) per the ADR's fail-open
posture; flagged as an owner decision to drop it once automatic persistence is trusted in prod.

## Details

Implemented (TDD, RED→GREEN) within the planned scope. Notes file: `cache/poolfix-notes-task-120.md`.

### Backend
- `backend/src/api/routes/pool_admin.py`:
  - `QRLoginPollResponse` += `tg_user_id: int | None`, `display_label: str | None`,
    `outcome: str | None` ("revive"/"add") — all present only on SUCCESS; `session_string`
    copy-field unchanged (DR floor).
  - `PoolHealthAccount` += `display_label: str | None`, `tg_user_id: int | None` (null for an
    env-only slot). `_PoolHealthSnapshot` validates them via `accounts: list[PoolHealthAccount]`
    (no change needed — the writer already carries them via `asdict`).
  - `poll_qr_login` now persists on SUCCESS via `_persist_qr_success`: opens a caller-owned sync
    `Session` (new dep `get_pool_admin_db`), runs `upsert_revive_or_add(... pool_max=POOL_MAX,
    env_floor_size=len(set(telegram_pool_sessions(settings))))` in a threadpool. On REVIVE writes the
    non-secret revive-signal (`POOL_REVIVE_SIGNAL_REDIS_KEY`, TTL) + SREMs the OLD fingerprint from
    `pool:quarantined_fingerprints` via a new `_ReviveRedisLike`/`_ReviveRedisAdapter` seam (new dep
    `get_pool_revive_redis`). Over-cap ADD → 409 (`_POOL_FULL_MESSAGE`), session copy-field STILL
    returned. Any other store/DB error → copy-field preserved, no `outcome`, class-name-only log.
  - Idempotent: the store upsert is keyed by `tg_user_id`, so a repeated SUCCESS poll never dupes.
- `backend/src/collector/telegram/account_pool.py`: `_Account`/`AccountStatus` += `display_label`;
  `from_sessions(... display_labels=)`, `account_statuses()` surfaces it, `revive_slot(... display_label=)`
  refreshes it (additive; index stays the stable id; no secret).
- `backend/src/collector/registry.py`: `_union_pool_sessions` returns a 3-tuple incl. `display_labels`
  (DB rows carry the label, env slots None); passed to `from_sessions`.
- `backend/src/collector/telegram/reader.py`: revive-apply passes `display_label` from the StoredSession.

### Frontend
- `lib.ts`: `ReviveOutcome` union + `asReviveOutcome` (unknown→null), `accountLabel` (fallback
  `account #<index>`), `reviveSuccessMessage` (distinct re-connect vs add, names the label).
- `queries.ts`: `invalidatePoolHealth(queryClient)` invalidates exactly `POOL_HEALTH_QUERY_KEY`.
- `qr-login-dialog.tsx`: title "Add / re-connect account"; on SUCCESS shows the outcome-aware message
  + identity, invalidates pool-health (honest ≤1-cycle flip — no fake optimistic flip); vault note
  re-worded to "already persisted; this is a one-time DR backup".
- `pool-health-table.tsx`: new "Account" column (`display_label` / fallback).
- `pages/admin/pool.tsx`: button "Add / re-connect account".
- OpenAPI regenerated (`make gen-openapi gen-types`) → `gen.types.ts` carries the new fields (no `any`).

### Verification evidence
- Backend `make fmt` (386 unchanged) / `make lint` (All checks passed) / `make typecheck`
  (Success: no issues, 189 files, mypy strict, no Any/ignore).
- `make test` = 1152 passed, 307 deselected (updated 4 shape/call-assert tests for the additive fields).
- Integration on throwaway `pgvector/pgvector:pg16` (host 127.0.0.1:55440): pool_admin(24) +
  pool_session_store + at_rest_encryption + migrations = 38 passed; container torn down.
- New pool_admin tests: per-account identity in health; SUCCESS ADD → store add + outcome + identity
  + no revive-signal; SUCCESS REVIVE → revive-signal written (non-secret, no session) + OLD quarantine
  cleared + no duplicate; over-cap → 409 with session copy-field preserved + no secret leak; idempotent
  repeated SUCCESS poll → no duplicate.
- Frontend: `npm install`, `npx tsc -b` clean, `npm run lint` clean, `npx vitest run` = 315 passed
  (9 new in `tests/unit/pool-admin/revive.spec.ts`).

## Details (2026-06-16 — fix: roll back on persist-path DB error so the session DR floor survives)

HIGH bug found in review of the degrade-gracefully branch of `_persist_qr_success`
(`backend/src/api/routes/pool_admin.py`).

### Problem
On a SUCCESS poll the route persists via `upsert_revive_or_add`, which **FLUSHES**.
The `except Exception` branch existed to preserve the DR floor — it returns a 200 still
carrying the minted `session_string` (so the admin can paste it into the vault) with
`outcome=None`. But a **flush-level** DB error (e.g. `IntegrityError`/`DBAPIError`) leaves
the SQLAlchemy `Session` in a *failed-transaction* state. When the handler returned,
`storage.database.get_session`'s teardown `commit()` then raised `PendingRollbackError`
→ the client got a **500 and LOST the minted `session_string`** — the exact invariant
this branch exists to protect.

### Fix (minimal)
In the `except Exception` branch, call `db.rollback()` **before** returning the response
(mirrors `api/watchlist/service.py`, which rolls back a caught `IntegrityError` before
continuing). The returned 200 body still carries `session_string` (DR floor) and
`outcome=None`. The session string is never logged — the warning logs only
`type(exc).__name__` + `tg_user_id` + the non-secret `session_fingerprint(...)`.

### Test (RED→GREEN)
`backend/tests/integration/test_pool_admin_api.py::TestQRLoginPersistOnSuccess::`
`test_persist_db_error_rolls_back_and_keeps_session_dr_floor` (`@pytest.mark.integration`).
Injects a genuine failed-flush by monkeypatching `api.routes.pool_admin.upsert_revive_or_add`
with a fake that `session.add`s two rows sharing the same UNIQUE `tg_user_id` and flushes
(raising `IntegrityError`, leaving the Session failed). Asserts: (a) HTTP **200** (not 500),
(b) body still carries the minted `session_string` (DR floor survived), (c) `outcome` is null,
(d) no secret in logs (`caplog`), and that the rolled-back transaction persisted **nothing**.
Verified RED without the fix (`PendingRollbackError` → 500) and GREEN with it.

### LOW (revive-signal write-before-commit) — documented, not changed
`get_session` commits at teardown, so the revive-signal is written inside
`_persist_qr_success` slightly before that teardown commit. Making it strictly
post-commit is non-trivial (the commit is owned by the context-manager dependency, not
the handler) and the window self-heals: the signal is best-effort/fail-open, a missed
or premature signal self-heals on the next full pool build, and the persisted row is the
source of truth. Left as-is per "do not over-engineer".

### Verification evidence
- `make fmt` — 2 files reformatted, rest unchanged.
- `make lint` — All checks passed.
- `make typecheck` — Success: no issues found in 189 source files (mypy strict; no `Any`/`# type: ignore`).
- `make test` (unit, `-m 'not integration'`) — 1152 passed, 308 deselected.
- Integration on throwaway `pgvector/pgvector:pg16` (alt `POSTGRES_HOST=localhost POSTGRES_PORT=55432`,
  throwaway password): new test green; full `tests/integration/test_pool_admin_api.py` = 25 passed
  (24 prior + 1 new). New test verified RED→GREEN. Container torn down after.
