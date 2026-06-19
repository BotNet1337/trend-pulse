---
id: TASK-135
title: account-factory REST API (/factory) — superuser
status: planned
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [account-factory, api, fastapi, superuser, layer-b]
---

# TASK-135 — account-factory REST API (Layer B6)

> Superuser endpoints to trigger provisioning, inspect factory accounts + probation, relogin, and read
> budget — the surface the UI (TASK-136) and curl verification drive.

## Context
Mirror `api/routes/pool_admin.py` (superuser dependency, Pydantic boundary, 503 if unconfigured).
Router registration: `api/main.py:56` import + `v1_router.include_router(...)` (~line 367). New API
fields → `make gen-openapi gen-types` (openapi-drift-check). Backs onto `factory_account_store`
(TASK-132) + `factory.service`/`factory.tasks` (TASK-134).

## Goal
`api/routes/factory.py` (`APIRouter(prefix="/factory", tags=["factory"])`, superuser-only):
- `POST /factory/accounts` — trigger provisioning of N (or auto-by-need); enqueues/invokes `factory_tick`.
- `GET /factory/accounts` — list factory accounts (state, masked phone, probation_until, cost, last_error).
- `POST /factory/accounts/{id}/relogin` — re-register/relogin a failed/expired factory account.
- `GET /factory/budget` — `{budget_usd, spent_usd, remaining_usd, enabled}`.
Pydantic response models; secrets (session) never returned; registered in `api/main`.

## Discussion
- Q: Sync trigger or enqueue? → A: enqueue → Decision: `POST /accounts` enqueues `factory_tick` (Celery)
  and returns 202 + a summary; the loop verify forces a synchronous tick in tests via the service helper.
- Q: Expose session anywhere? → A: never → Decision: API returns only masked phone + state + identity;
  the session lives encrypted in the DB, promoted via the store.
- Q: 503 semantics? → A: like pool_admin → Decision: if `ACCOUNT_FACTORY_PROVIDER` is unset/empty (factory
  inactive), mutating endpoints return 503 with a clear message (read endpoints still work).

## Scope
- Touch ONLY: `api/routes/factory.py` (new); `api/main.py` (import + include router); regenerate
  `frontend/src/shared/api/gen.types.ts` via `make gen-openapi gen-types`.
- Do NOT touch: factory core logic (TASK-134), UI (TASK-136).
- Blast radius: public API (new routes) → openapi-drift-gen required.

## Acceptance Criteria
- [ ] `GET /factory/accounts` (superuser) returns the factory rows with state/probation/cost; non-superuser → 403.
- [ ] `POST /factory/accounts` enqueues a tick (202) and, with the fake provider, results in a registered row.
- [ ] `GET /factory/budget` returns budget/spent/remaining/enabled correctly.
- [ ] `POST /factory/accounts/{id}/relogin` transitions a failed row back through registration (fake).
- [ ] No session string ever appears in any response; `make openapi-drift-check` green.

## Plan
1. `api/routes/factory.py` — router + Pydantic models (`FactoryAccountOut`, `BudgetOut`, `TriggerIn/Out`),
   superuser dep, 503 guards.
2. `api/main.py` — import + `v1_router.include_router(factory_router)`.
3. `make gen-openapi gen-types`.

## Invariants
- Superuser-only; Pydantic at boundary; no secret in any response; 503 when unconfigured.

## Edge cases
- Trigger while disabled → 503. Relogin unknown id → 404. Budget when disabled → `enabled:false`.

## Test plan
- integration: route auth (superuser/403), trigger→registered (fake), budget math, relogin, no-secret assert.

## Checkpoints
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — curl all 4 endpoints against live API + openapi-drift)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (superuser authz, no secret leakage)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
