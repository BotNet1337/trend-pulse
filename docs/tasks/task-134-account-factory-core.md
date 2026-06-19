---
id: TASK-134
title: account-factory core — buy→register→probation→promote + budget cap + probation gate
status: planned
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [account-factory, orchestration, budget, probation, promote, layer-b]
---

# TASK-134 — account-factory core (Layer B1+B4+B5)

> The orchestration brain: top up the pool when it's below target, within a hard USD budget — buy a
> number, register over a proxy, **hold on probation 1–2 weeks**, then promote the session into the
> live pool with `source='auto'`. Also relogin. The single Celery task the service runs.

## Context
Depends on the proxy column (TASK-129), the `source` param (TASK-130), the `factory_accounts` store
(TASK-132), and the provider/registrar abstraction (TASK-133). Pool health snapshot lives at Redis
`pool:health:latest`; the live-pool enroll API is `storage/pool_session_store.upsert_revive_or_add`.
Celery wiring: `celery_app.py` include list, `scheduler.py` beat_schedule. Promotion must NOT
double-connect a session (AuthKeyDuplicated): the factory registers fresh sessions; promotion writes
to `pool_sessions` + the existing reload/revive signal — it never connects a session already live.

## Goal
`factory/service.py` exposing pure decision helpers + a `factory_tick()` Celery task that:
1. reads pool health (healthy vs `pool_min_healthy`) + quarantine gaps;
2. if under target AND budget allows → `buy_number` (assign a proxy from the configured pool) →
   `register` → store `factory_accounts` row `registered` → set `probation_until = now + ACCOUNT_FACTORY_PROBATION_DAYS`;
3. for rows past probation that pass a health check (not banned; can read a public test channel) →
   promote: `upsert_revive_or_add(..., proxy=, source='auto')` + write pool reload signal → mark `promoted`;
4. budget hard-cap: never buy if `total_spent_usd + price > ACCOUNT_FACTORY_BUDGET_USD`;
5. relogin path for a failed/expired factory account (re-register, keep the row).
Activation is **provider-driven** (no separate enable flag — owner decision 2026-06-20): the tick is a
no-op when `ACCOUNT_FACTORY_PROVIDER` is unset/empty; `fake` → active with fakes (local/test); `smspva`
(+ `SMSPVA_API_KEY`) → live. The budget hard-cap always applies regardless of provider.

## Discussion
- Q: How is "$10 → buy when needed" modelled? → A: budget hard-cap + need-driven → Decision:
  `ACCOUNT_FACTORY_BUDGET_USD` ceiling; buy only when pool < target AND (budget - spent) ≥ price.
  Spend = `factory_account_store.total_spent_usd()` (persisted, not estimated).
- Q: Probation length? → A: 14 days default → Decision: `ACCOUNT_FACTORY_PROBATION_DAYS=14`, env-overridable;
  promotion gated on `now ≥ probation_until` AND health check pass.
- Q: How is the scenario testable without time travel? → A: inject clock + allow forcing `probation_until`
  → Decision: pure helpers take `now`; API/test can set `probation_until` in the past (verify path).
- Q: Concurrency vs worker pool? → A: never co-connect → Decision: factory uses its own clients/proxies;
  promotion is store-write + signal only; reuses the safe single-slot revive at the worker side.

## Scope
- Touch ONLY: `factory/service.py` (new — pure helpers: `needs_topup`, `can_afford`, `is_promotable`),
  `factory/tasks.py` (new — `factory_tick` Celery task), `factory/constants.py` (budget/probation
  defaults if not already), `config.py` (env: `ACCOUNT_FACTORY_BUDGET_USD`,
  `ACCOUNT_FACTORY_PROBATION_DAYS`, `ACCOUNT_FACTORY_PROXY_POOL`, `ACCOUNT_FACTORY_COUNTRY`),
  `celery_app.py` (include `factory.tasks`), `scheduler.py` (beat entry `factory-tick`).
- Do NOT touch: API surface (TASK-135), UI (TASK-136), compose/ops (TASK-137).
- Blast radius: new Celery task + beat entry; reads pool health, writes `factory_accounts` + (on
  promote) `pool_sessions` + reload signal. Config additions.

## Acceptance Criteria
- [ ] Given pool below target + budget available, When `factory_tick` runs (fake provider), Then a
      `factory_accounts` row appears `registered` with `probation_until` in the future and budget spent ↑.
- [ ] Given `total_spent + price > budget`, When tick runs, Then NO purchase occurs (hard-cap; asserted).
- [ ] Given a row past `probation_until` that passes health-check, When tick runs, Then it is promoted:
      a `pool_sessions` row exists with `source='auto'` + proxy set, factory row → `promoted`.
- [ ] Given a row still within probation, When tick runs, Then it is NOT promoted (gate; asserted).
- [ ] Given `ACCOUNT_FACTORY_PROVIDER` unset/empty, When tick runs, Then it is a no-op (no purchase, no promote).
- [ ] Manual QR add still yields `source='manual'` (no regression).

## Plan
1. `config.py` — factory env fields (enabled default False; budget Decimal; probation days; proxy pool; country).
2. `factory/service.py` — pure `needs_topup(health, target)`, `can_afford(spent, price, budget)`,
   `is_promotable(row, now)`, `assign_proxy(pool, used)`.
3. `factory/tasks.py` — `factory_tick` orchestrating provider→registrar→store→promote, all guarded.
4. `celery_app.py` include + `scheduler.py` beat entry (interval = named const).

## Invariants
- Budget is a hard ceiling (never exceeded). Probation gate never bypassed.
- Factory never connects a session already live in the worker pool (no AuthKeyDuplicated).
- Promotion sets `source='auto'` + the account's proxy; idempotent via `upsert_revive_or_add`.
- Disabled flag → exact no-op.

## Edge cases
- Provider out of balance / no number → row `failed`, logged, budget untouched.
- Registration banned → row `banned`, not promoted, not retried blindly.
- Health-check fails after probation → stay un-promoted, record `last_error`.
- Proxy pool exhausted → skip buy this tick (logged), no crash.

## Test plan
- unit: pure helpers (topup/afford/promotable/assign_proxy) incl. boundary budget; disabled no-op.
- integration: full fake-provider tick → registered→probation; force `probation_until` past → promote →
  `pool_sessions` row `source='auto'`; budget hard-cap; banned scenario.

## Checkpoints
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — full fake tick: register→probation→promote→pool source=auto; budget cap)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (handles sessions, proxy creds, money, external registration)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
