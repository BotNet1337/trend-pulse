---
id: TASK-117
title: Admin UI — TG pool QR-login flow + connection-status dashboard
status: planned
owner: frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
tags: [frontend, admin, telegram, qr-login]
---

# TASK-117 — Admin UI: QR-login flow + pool connection-status dashboard

> An admin page at `/admin/pool` that renders the pool-health table (per-account state + disconnect
> reason) and an "Add account" QR flow (start → render QR → poll → show success/error + the new
> session string to copy).

## Context
Part of EPIC-TG-QR-POOL. Depends on TASK-116 (endpoints). FSD layout — mirror
`frontend/src/features/admin-metrics/` (api.ts/queries.ts) and `frontend/src/pages/admin/`. API client:
`frontend/src/shared/api/client.ts`; generated types via `npm run gen:api` after the backend OpenAPI
includes the new routes. Routes registered in `frontend/src/app/router/` (TanStack Router); admin route
is behind the existing protected/auth guard; backend `current_superuser` enforces 403.

## Goal
- `features/pool-admin/` (api.ts, queries.ts, index.ts, components) calling the 3 endpoints.
- `pages/admin/pool.tsx` page: pool-health dashboard + QR add-account flow.
- Route `/admin/pool` registered + a nav entry (mirror the admin-metrics route).
- QR rendering via a small lib (`qrcode.react`) added to `frontend/package.json`.

## Discussion
- Q: QR library? → A: `qrcode.react` (tiny, React 19 compatible) renders the `tg://login?token=...`
  string to an SVG. No new backend image dependency.
- Q: polling cadence? → A: QR poll every ~2s while a token is active and not terminal; pool-health
  on-demand + a manual refresh button + light auto-refresh (e.g. 15s) — avoid spamming.
- Q: show the session string? → A: yes, on success, in a copy-to-clipboard field with a note "add to
  TELEGRAM_POOL_SESSIONS in the vault and redeploy" (per ADR). Never auto-store.
- Q: state display? → A: per-account row: index, state badge (connected/cooling/quarantined), cooldown
  countdown for cooling, last-error reason for quarantined; a `stale` banner when the snapshot is old.

## Scope
- Touch ONLY:
  - NEW `frontend/src/features/pool-admin/` (api.ts, queries.ts, index.ts, ui components)
  - NEW `frontend/src/pages/admin/pool.tsx` (+ route file if the router is file-based)
  - `frontend/src/app/router/*` (register `/admin/pool` + path constant)
  - admin nav (wherever admin-metrics link lives)
  - `frontend/package.json` (+`qrcode.react`)
  - generated `frontend/src/shared/api/gen.types.ts` (via `npm run gen:api`)
  - tests: a component/unit test for the status formatter + QR flow state machine if a FE test setup exists
- Do NOT touch: other features, the backend, shared client internals.
- Blast radius: new route + new dependency; OpenAPI types regenerated.

## Acceptance Criteria
- [ ] Given a superuser at `/admin/pool`, Then the pool-health table lists each account with a state
      badge and (for cooling) a cooldown and (for quarantined) the last-error reason.
- [ ] Given the snapshot is stale, Then a clear "data from collector is stale" banner shows.
- [ ] Given the admin clicks "Add account", When start succeeds, Then a scannable QR (the `qr_url`)
      renders and the UI polls status.
- [ ] Given the QR is scanned/authorized, Then the UI shows success and a copy-able session string
      with the "add to vault & redeploy" note.
- [ ] Given timeout/password_needed/error, Then the UI shows the specific reason (not a generic error).
- [ ] `npm run build` + typecheck + lint pass; generated types match the backend schema.

## Plan
1. Run backend to emit OpenAPI, then `npm run gen:api` so `components['schemas']` has the new models.
2. `features/pool-admin/api.ts` — `startQrLogin()`, `pollQrLogin(token)`, `getPoolHealth()` using
   `apiClient` + generated types.
3. `features/pool-admin/queries.ts` — `usePoolHealth()` (auto+manual refresh), `useQrLoginStart()`
   mutation, `useQrLoginPoll(token)` (refetchInterval while non-terminal).
4. components — `PoolHealthTable`, `QrLoginDialog` (QRCodeSVG + status/reason + copy field).
5. `pages/admin/pool.tsx` — compose them; mirror admin-metrics page shell.
6. router + nav — register route + path constant + admin nav link.
7. `package.json` — add `qrcode.react`; `npm install`.

## Invariants
- Session string shown only in the UI on success; never logged to console; copy-to-clipboard only.
- Route gated behind the existing auth guard; relies on backend 403 for non-superusers.
- Types are generated from the backend OpenAPI (no hand-rolled response shapes).

## Edge cases
- Endpoint 503 (not configured) → friendly "QR login not configured on the server" message.
- Poll returns `expired` → offer "regenerate QR".
- Empty pool / no accounts → "no pool accounts" empty state.

## Test plan
- unit/component: status-formatter + QR flow reducer (terminal vs pending). Manual e2e in verify:
  load `/admin/pool`, exercise start→QR render→poll, against the running stack.

## Checkpoints
current_step: 4
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD where FE setup allows → minimal code)
- [ ] 4 verify (G2 — build + typecheck + lint + load page)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (renders/handles session secret in UI — REQUIRED)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### do (step 3) — 2026-06-16

Implemented the FSD `pool-admin` feature + `/admin/pool` page, mirroring
`admin-metrics`. All types from the regenerated OpenAPI schema (no hand-rolled
shapes); TypeScript strict, no `any`.

**Files (new):**
- `frontend/src/features/pool-admin/lib.ts` — pure helpers: `AccountState`/
  `QrLoginStatus` literal unions, `isTerminalQrStatus`, `asQrLoginStatus`/
  `asAccountState` narrowers (unknown → fail-safe), `accountStateLabel`/
  `accountStateBadgeVariant`, `qrStatusMessage` (reason-bearing, never generic),
  `formatCooldown` (m:ss), `shouldShowPoolAdminNotFound` (404-clone guard).
- `frontend/src/features/pool-admin/api.ts` — `startQrLogin`, `pollQrLogin`,
  `getPoolHealth` over `apiClient`; types = `components['schemas'][…]`.
- `frontend/src/features/pool-admin/queries.ts` — `usePoolHealth` (15s
  background refresh + manual refetch, retry:false), `useQrLoginStart` mutation,
  `useQrLoginPoll` (refetchInterval 2s while non-terminal, → false on terminal).
- `frontend/src/features/pool-admin/ui/pool-health-table.tsx` — per-account row
  (index, state badge, cooldown for cooling, last_error_reason for quarantined),
  aggregates line, stale banner, empty state. `fs-*`/`fs-table` styling.
- `frontend/src/features/pool-admin/ui/qr-login-dialog.tsx` — start→QR(`QRCodeSVG`)
  →poll→success(copy session string + vault note) / specific reason + Regenerate.
  Secret never logged; poll query removed on close so it does not linger.
- `frontend/src/features/pool-admin/index.ts` — barrel.
- `frontend/src/pages/admin/pool.tsx` — page shell (mirrors admin-metrics): head
  with Refresh + Add-account, loading/error (503 messaging), `PoolHealthTable`,
  `QrLoginDialog`.
- `frontend/tests/unit/admin/pool-admin.spec.ts` — 17 tests (api paths, query/
  poll options incl. terminal stop condition, status/state narrowing, messages,
  cooldown, not-found guard).

**Files (edited):** `path.ts` (+`admin.pool`), `router.ts` (+`adminPoolRoute`),
`pages/admin/index.ts` (barrel), `pages/index/app-shell.tsx` (superuser-gated
"TG pool (admin)" link in the account menu), `package.json`/`package-lock.json`
(+`qrcode.react@^4.2.0`), `openapi.json` + `gen.types.ts` (regen, additive only).

**Verify (authoritative gate):** `tsc -b` clean; `eslint .` clean (only a
baseline-data advisory); `vitest run` 303/303 (17 new); `npm run build` green.
Live `/admin/pool` render against the running stack deferred to the TEST stage
(needs backend); build+typecheck is the gate here.

**Notes/gotchas:** backend types `state`/`status` as plain `string` (not enums)
in OpenAPI → local literal unions + narrowers in `lib.ts`. OpenAPI dump = `make
gen-openapi` (`GEN_DUMP_ENV uv run --directory backend python scripts/dump_openapi.py`,
writes straight to `frontend/src/shared/api/openapi.json`) then `npm run gen:api`;
diff is additive (271/0 openapi, 240/0 types) so no drift on existing routes.
