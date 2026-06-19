---
id: TASK-130
title: Pool source field — manual|auto end-to-end (schema → health → API → UI badge)
status: planned
owner: backend+frontend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [telegram, pool, source, ui, observability, layer-a]
---

# TASK-130 — Pool `source` field (Layer A3)

> Every pool account is tagged `manual` (added by owner via QR) or `auto` (added by account-factory),
> carried from the DB through the health snapshot to a **visible UI badge**. QR add stays `manual`.

## Context
`pool_sessions` (`storage/models/pool_sessions.py`) has no provenance field. Health flows:
`AccountPool.account_statuses()` → `AccountStatus` dataclass (`account_pool.py:117`) →
`observability/pool_health.py:141` writes snapshot to Redis `pool:health:latest` →
`api/routes/pool_admin.py` `PoolHealthAccount` (line 210) / `PoolHealthResponse` (line 233) →
frontend `features/pool-admin/ui/pool-health-table.tsx` rows. QR add path:
`pool_admin.py` qr-login poll → `upsert_revive_or_add`.

## Goal
`source` (enum `manual`|`auto`, default `manual`) on `pool_sessions`; existing rows + QR adds →
`manual`; threaded into `AccountStatus` → snapshot → `PoolHealthAccount.source` → a badge in the UI
table. New API field → `make gen-openapi gen-types` (else openapi-drift-check red).

## Discussion
- Q: enum or free string? → A: constrained → Decision: `source` String with a named
  `PoolSource` literal/const (`manual`|`auto`); validator at the boundary; default `manual`.
- Q: backfill existing rows? → A: yes → Decision: migration sets existing rows + server_default `manual`.
- Q: where does `auto` get set? → A: TASK-134 promotion calls `upsert_revive_or_add(..., source='auto')`;
  this task adds the param (default `manual`) so QR keeps `manual` with no change at the call site.

## Scope
- Touch ONLY: `migrations/versions/0027_pool_sessions_source.py` (new, down_revision `0026`);
  `storage/models/pool_sessions.py` (+`source`); `storage/pool_session_store.py`
  (`upsert_revive_or_add(source=...)` default manual; `StoredSession.source`);
  `collector/telegram/account_pool.py` (`AccountStatus.source` + `_Account.source`, set in `from_sessions`);
  `observability/pool_health.py` (snapshot already serialises `asdict(status)` → carries source);
  `api/routes/pool_admin.py` (`PoolHealthAccount.source: str`); frontend `pool-health-table.tsx`
  (+ source badge), regenerate `gen.types.ts`.
- Do NOT touch: rotation/quarantine, proxy (TASK-129), factory (TASK-134 sets the value).
- Blast radius: `pool_sessions` schema (additive), public API (`PoolHealthAccount`) → drift-gen required.

## Acceptance Criteria
- [ ] Given existing rows, When migration `0027` runs, Then `source='manual'`.
- [ ] Given a QR-added account, When pool-health is read, Then its `source='manual'`.
- [ ] Given `upsert_revive_or_add(source='auto')`, When pool-health is read, Then `source='auto'`.
- [ ] `GET /pool-admin/pool-health` JSON includes `accounts[].source`; `make openapi-drift-check` green.
- [ ] UI `/admin/pool` renders a `manual`/`auto` badge per row (Playwright asserts both badge texts present).

## Plan
1. `0027_pool_sessions_source.py` — add `source` (String, server_default `manual`, not null).
2. `pool_sessions.py` — `source: Mapped[str]`; `collector/constants.py` — `POOL_SOURCE_MANUAL`/`_AUTO`.
3. `pool_session_store.py` — `upsert_revive_or_add(..., source=POOL_SOURCE_MANUAL)`; `StoredSession.source`.
4. `account_pool.py` — `_Account.source`, `AccountStatus.source`, set in `from_sessions`.
5. `pool_admin.py` — `PoolHealthAccount.source: str = "manual"`.
6. frontend `pool-health-table.tsx` — source badge (reuse badge CSS); `make gen-openapi gen-types`.

## Invariants
- Default is `manual` everywhere; only the factory promotion sets `auto`.
- No secret exposure (source is non-secret).

## Edge cases
- Snapshot from before this change (no `source`) → UI defaults to `manual` (back-compat).

## Test plan
- unit: store default manual / explicit auto; `account_statuses` carries source.
- integration: `0027` round-trip + backfill; `GET /pool-admin/pool-health` returns source.
- e2e: Playwright badge render.

## Checkpoints
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — migration + curl pool-health JSON + Playwright badge)
- [ ] 5 review (auto, adversarial)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
