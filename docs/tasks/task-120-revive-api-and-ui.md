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
current_step: 3
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — full suite + ruff + mypy strict + FE typecheck/vitest + OpenAPI regen green)
- [ ] 5 review (code-reviewer)
- [ ] 5.5 security (MANDATORY — confirm only the one-shot session copy-field is secret; identity
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
