---
id: TASK-130
title: Pool source field — manual|auto end-to-end (schema → health → API → UI badge)
status: planned
owner: backend+frontend
created: 2026-06-19
updated: 2026-06-20
baseline_commit: ee11b039aa3998b82ecc38fdb924498d42751424
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
current_step: 6
baseline_commit: ee11b039aa3998b82ecc38fdb924498d42751424
branch: ""
lock: "executor-task130-2026-06-20"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — migration + curl pool-health JSON + Playwright badge)
- [x] 5 review (auto, adversarial) — PASS, 1 MEDIUM fixed + 1 INFO fixed
- [ ] 5.5 security — N/A (source is non-secret; no auth/input/crypto/secret surface)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### G2 verify evidence (2026-06-20)
- `make ci-fast` GREEN: backend `1266 passed, 313 deselected`; mypy `Success 189 files`; ruff clean; frontend vitest `340 passed (29 files)`.
- Migration 0027 up/down/re-up clean: `upgrade 0026 -> 0027` adds `source VARCHAR(16) NOT NULL DEFAULT 'manual'`; `downgrade 0027 -> 0026` drops it; re-upgraded to head (DB consistent).
- Backfill: INSERT without `source` → `source='manual'`. Integration pool suite `32 passed` (incl. default-manual/explicit-auto round-trip, snapshot source passthrough, legacy snapshot-without-source defaults manual, 5-tuple sources union loader).
- pool-health JSON (superuser, TestClient + fakeredis snapshot with both values): `HTTP 200`, `accounts[0].source="manual"`, `accounts[1].source="auto"`. Live curl not possible — `make up` failed (Docker network address pool exhausted, 32 networks on host); TestClient+superuser is the contract-sanctioned alternative.
- Playwright: spec `frontend/tests/e2e/pool-source-badge.spec.ts` CREATED but NOT run — same Docker network exhaustion blocks `make up`/nginx edge. Honest fallback per contract: badge logic covered by vitest unit tests (`asAccountSource`/`accountSourceLabel`/`accountSourceBadgeVariant` → Manual/Auto) + integration API contract; `data-testid="pool-account-source"` present in `pool-health-table.tsx`. Spec committed for CI/manual run.
- openapi+types regenerated (`make gen-openapi gen-types`): `PoolHealthAccount.source: string` now in `gen.types.ts` + `openapi.json`.

### Review (opus, adversarial) — PASS, no CRITICAL/HIGH
- Unbroken DB→snapshot→API→UI chain confirmed; CONVENTIONS met (named constants, no Any, frozen DTOs); migration down_revision=0026, server_default backfills, downgrade clean; back-compat (Pydantic default + `asAccountSource` narrowing) verified; no scope creep (the two `docs/*autoprovision*` edits are pre-existing owner changes, NOT in this commit); source non-secret, no session-string leak.
- **MEDIUM (FIXED):** QR-revive demoted an `auto` account to `manual` because the REVIVE branch unconditionally wrote `existing.source = source` with the QR default. Fix: `upsert_revive_or_add(source: str | None = None)` — REVIVE now PRESERVES existing provenance unless an explicit non-None source (the factory) is passed; ADD coalesces None→`manual`. New test `test_qr_revive_preserves_auto_provenance` encodes the invariant. ruff/mypy/18 store unit tests green post-fix.
- **INFO (FIXED):** frontmatter `baseline_commit` aligned to Checkpoints value (`ee11b039`); `updated` → 2026-06-20.
- **INFO (noted):** live Playwright badge-render deferred (Docker network exhaustion) — covered by vitest/integration; spec committed for CI.

### Security stage 5.5 — N/A
`source` is non-secret; the diff touches no auth/authz, input validation, secrets/env, crypto, or raw SQL. Reviewer confirmed no secret leak. Skipped.
