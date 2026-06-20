---
id: TASK-136
title: account-factory UI on /admin/pool — factory panel + source badge + manual trigger
status: done
owner: frontend
created: 2026-06-19
updated: 2026-06-20
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: "gsd/phase-136-factory-ui"
tags: [account-factory, frontend, ui, admin-pool, layer-b]
---

# TASK-136 — account-factory UI (Layer B7)

> On `/admin/pool`: a factory-accounts panel (state + probation countdown), a `source` badge
> (manual|auto) on live-pool rows, and a "Register account" button to trigger provisioning. Manual QR
> add stays.

## Context
`frontend/src/pages/admin/pool.tsx` (page), `frontend/src/features/pool-admin/` (`api.ts`,
`queries.ts`, `ui/pool-health-table.tsx`). Types from `frontend/src/shared/api/gen.types.ts`
(`components['schemas'][...]`). Consumes TASK-135 `/factory/*` + TASK-130 `source` field.

## Goal
- A `FactoryAccountsPanel` listing `GET /factory/accounts` (state badge, masked phone, probation
  countdown, cost) with React Query (poll like pool-health).
- `source` badge (`manual`|`auto`) in `pool-health-table.tsx` rows.
- A "Register account" button → `POST /factory/accounts` (disabled/explanatory when factory disabled);
  shows budget (`GET /factory/budget`).
- Manual QR add flow unchanged.

## Discussion
- Q: New page or extend /admin/pool? → A: extend → Decision: same page, new panel below the health table.
- Q: Disabled-factory UX? → A: explain → Decision: button disabled with tooltip "factory disabled" when
  `budget.enabled===false` (no dead clicks).

## Scope
- Touch ONLY: `frontend/src/features/pool-admin/api.ts` (+factory calls), `queries.ts` (+factory hooks),
  `ui/pool-health-table.tsx` (source badge), new `ui/factory-accounts-panel.tsx`,
  `pages/admin/pool.tsx` (mount panel + button). Uses regenerated `gen.types.ts` (from TASK-135).
- Do NOT touch: backend, QR flow internals.
- Blast radius: frontend admin page only.

## Acceptance Criteria
- [ ] `/admin/pool` (superuser) shows the factory panel with each account's state + probation countdown.
- [ ] Live-pool rows show a `manual`/`auto` source badge (Playwright asserts both texts).
- [ ] "Register account" button calls `POST /factory/accounts`; disabled with tooltip when factory off.
- [ ] Budget (remaining/total) is displayed.
- [ ] Manual QR "add account" flow still present and functional.

## Plan
1. `api.ts` — `getFactoryAccounts`, `triggerFactory`, `getFactoryBudget`, `reloginFactory`.
2. `queries.ts` — `useFactoryAccounts`, `useFactoryBudget`, trigger mutation.
3. `ui/factory-accounts-panel.tsx` — table + countdown + badges.
4. `ui/pool-health-table.tsx` — source badge column.
5. `pages/admin/pool.tsx` — mount panel + register button + budget.

## Invariants
- Superuser-gated (page already checks `is_superuser`); no secret rendered.
- Source badge defaults `manual` if field absent (back-compat).

## Edge cases
- Factory disabled → panel shows "disabled", button disabled.
- Empty factory list → empty-state row.

## Test plan
- e2e: Playwright on `/admin/pool` — factory panel renders, both source badges present, register button
  state correct, budget shown. (Backend seeded via fake-provider trigger + forced promote in verify.)

## Checkpoints
current_step: done
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: "gsd/phase-136-factory-ui"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code) — 23 new tests RED→GREEN; vitest 363/363; tsc clean; real FACTORY_STATES used
- [x] 4 verify (G2) — ci-fast GREEN (be 1349, fe tsc 0, vitest 43/43 pool-admin); e2e factory-panel.spec.ts authored+typechecks; live Playwright DEFERRED (Docker network exhausted)
- [x] 5 review (opus, adversarial) — PASS, 0 CRITICAL/HIGH; 1 MEDIUM (trigger mutateAsync unhandled rejection) FIXED → mutate()+onError surface+isPending gate; 2 LOW (1 fixed via pending/error UX; 1 deferred e2e render-case, documented)
- [x] 5.5 security — N/A (read-only superuser-gated panel + trigger on already-gated endpoint; no auth/secrets/input/crypto touched)
- [x] 6 ship (PR #205, squash-merged 2026-06-20; depsec-only red, allowed)
- [x] 7 learnings (docs/learnings.md 2026-06-20 block)
debug_runs: []

## Details
- Source badge (manual|auto) AC was already shipped in TASK-130 (lib.ts helpers + pool-health-table.tsx column + pool-source-badge.spec.ts) — TASK-136 left it untouched.
- Real FACTORY_STATES from backend/src/factory/constants.py: purchased/registered/probation/promoted/failed/banned (task spec's draft list was stale).
- Money fields (cost_usd/budget_usd/spent_usd/remaining_usd) rendered as Decimal STRINGS — never parsed to float.
- Register button disabled+tooltip when budget.enabled===false OR budget loading OR trigger pending; manual QR flow unchanged.
- Review MEDIUM fix: useTriggerFactory consumers use .mutate() (not .mutateAsync) so a 503/500 lands in mutation error state (surfaced via [data-testid="factory-register-error"]) instead of an unhandled rejection.
- Live Playwright DEFERRED: `make up` fails with Docker network exhaustion ("all predefined address pools have been fully subnetted") — same documented blocker as prior tasks. e2e spec committed; superuser-render case documented as not-automatable (no superuser-seed endpoint), proven instead by the 23 vitest unit tests + backend integration test_factory_api.py.
