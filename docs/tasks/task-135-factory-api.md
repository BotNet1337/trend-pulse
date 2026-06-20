---
id: TASK-135
title: account-factory REST API (/factory) — superuser
status: review
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
current_step: 6
baseline_commit: f74515d82185c4321d417cbc9576df734b01cb37
branch: "gsd/phase-135-factory-api"
lock: "executor-135-run1"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — TestClient all 4 endpoints + openapi regenerated)
- [x] 5 review (auto, adversarial — PASS, 0 CRITICAL/HIGH)
- [x] 5.5 security (superuser authz, no secret leakage — PASS, 0 CRITICAL/HIGH)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### do (TDD) — checkpoint 3
New superuser `/factory` router mirroring `pool_admin.py`. Files: `backend/src/api/routes/factory.py` (new), `backend/src/api/main.py` (import + `v1_router.include_router(factory_router)`), `backend/tests/integration/test_factory_api.py` (new, 16 tests). RED confirmed (404 before impl) → GREEN (16/16). Tick runner injected via `get_factory_tick_runner()` dep for in-proc testability; `session_string`/`proxy` explicitly omitted from `FactoryAccountOut`.

### verify (G2) — checkpoint 4
`make ci-fast` GREEN (1349 passed, 338 deselected). Integration 16/16 pass. Literal TestClient JSON bodies captured (curl-equivalent — `make up` blocked by Docker net exhaustion):
- `GET /factory/budget` (fake) → 200 `{budget_usd:"10.00", spent_usd:"4.00", remaining_usd:"6.00", provider:"fake", enabled:true}`
- `GET /factory/accounts` → 200 list, NO `session_string`/`proxy` key or value present
- `POST /factory/accounts` (fake) → 202 `{status:"triggered"}`, `factory_accounts` row created
- `POST /factory/accounts/{id}/relogin` → 202 known id; 404 unknown id
- provider unset: `POST /accounts` + `.../relogin` → 503; `GET /accounts` + `GET /budget` → 200 (`enabled:false, provider:""`)
- non-superuser GET → 403
No-secret sweep across all bodies: clean. `make gen-openapi gen-types` regenerated `frontend/src/shared/api/{gen.types.ts,openapi.json}` (+ backend openapi) with `/v1/factory/*` paths + `FactoryAccountOut`/`BudgetOut`/`FactoryTriggerOut` schemas; drift-check confirms regenerated (to be committed by ship). Verify also fixed 4 ruff lint/format nits from do (unused import, import order) — no logic change.

### review — checkpoint 5 (PASS)
Faithful secure mirror of pool_admin. 0 CRITICAL/HIGH. Advisory: MEDIUM (budget spent_usd intentionally includes failed/banned sunk cost — documented), LOW×3 (stale docstring `now=None`; proxy no-secret test is key-name-only; N+1-by-state read for admin list). Applied cheap docstring fixes (now-default note + spent_usd-semantics note). N+1 and proxy-value test left as follow-up (admin endpoint, low cardinality).

### security — checkpoint 5.5 (PASS)
0 CRITICAL/HIGH. Secret-exposure gate clean: `FactoryAccountOut` omits `session_string`/`proxy`, `extra="forbid"`, logs class-name-only, store uses bind params, all 4 routes superuser-gated, no hardcoded secrets. INFO: optional rate-limit on mutating POSTs (superuser-only + budget hard-cap in core → not blocking).
