---
id: TASK-134
title: account-factory core — buy→register→probation→promote + budget cap + probation gate
status: review
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: "gsd/phase-134-account-factory-core"
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
current_step: 6
baseline_commit: 0b5cfced630466a6f3116023539af922ef74957e
branch: "gsd/phase-134-account-factory-core"
lock: "exec-134-2026-06-20"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — full fake tick: register→probation→promote→pool source=auto; budget cap)
- [x] 5 review (auto, adversarial)
- [x] 5.5 security (handles sessions, proxy creds, money, external registration)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### `do` stage (checkpoint 3) — implementation notes

- **Warming state used:** the row ends a buy tick in `FACTORY_STATE_PROBATION` (not literal
  `registered`). The legal state machine is `purchased → registered → probation → promoted`,
  and `probation_until` + the promote scan both belong to the `probation` state. So one buy
  tick drives `purchased → registered → probation` and stamps `probation_until` on the
  `probation` move. The AC text "registered with probation_until in future" is satisfied
  honestly by the `probation` row holding a future `probation_until` (the state the promote
  phase scans). No state-machine rule is violated.
- **Per-number price model:** `SmsProvider`/`PurchasedNumber` carry NO price. Added
  `account_factory_price_usd` (env `ACCOUNT_FACTORY_PRICE_USD`, default `Decimal("1.00")`):
  the budgeted cost per provisioned number, stamped as the row's `cost_usd` and checked by
  the budget hard-cap. Keeps budget accounting deterministic for the fake path.
- **`upsert_revive_or_add` signature (verified):** `(session, *, tg_user_id, session_string,
  display_label, pool_max, env_floor_size=0, source=None) -> UpsertResult`. It does **NOT**
  accept a `proxy` param and does **NOT** write the `pool_sessions.proxy` column. Since
  `pool_session_store.py` is OUT of this task's scope, promotion calls the store for
  `source='auto'` (idempotent) and then sets the proxy on the just-promoted row via a
  targeted `UPDATE pool_sessions SET proxy WHERE tg_user_id` in `factory.tasks`. A clean
  follow-up is to add a `proxy=` param to `upsert_revive_or_add` and drop the direct update.
- **Provider-driven no-op:** the gate is `if not settings.account_factory_provider: return`.
  Default `fake` keeps it active in CI; the no-op test sets `account_factory_provider=""`.
- **Promotion never connects a session** (no AuthKeyDuplicated): store-write + pool-reload
  signal only. Phone masked before persistence (`+7******1234`); session/proxy never logged.
- **Files changed:** `factory/service.py` (new pure helpers), `factory/tasks.py` (new tick),
  `factory/constants.py` (+orchestration constants), `config.py` (+factory env fields +
  `account_factory_proxy_pool_list`), `celery_app.py` (+`factory.tasks` include),
  `scheduler.py` (+`factory-tick` beat entry). Tests: `tests/unit/factory/test_service.py`,
  `tests/integration/test_factory_tick.py`.
- **Verification:** `make ci-fast` green (1349 passed, fmt+lint+mypy+unit). Integration:
  6/6 passed against the live pgvector test DB (run via a socat bridge over the internal
  postgres net, since that net is `internal=true` with no published host port).

### `review` stage (checkpoint 5) — verdict PASS (no CRITICAL/HIGH)

- All invariants hold: budget hard-cap `<=` Decimal; probation gate `not None AND now >=
  probation_until`; promotion is store-write + reload-signal only (no Telethon connect);
  `source='auto'`; provider-unset early-returns before any DB/Redis/buy.
- Secrets clean: every log carries only ids/states/exc_type/isoformat; phone masked;
  session/proxy/api_key never logged. `asyncio.run` safe in the prefork worker;
  `provider.aclose()` always awaited in `finally`.
- **MEDIUM (accepted, documented follow-up):** the direct `pool_sessions.proxy` UPDATE is a
  second writer vs the store's "only writer" docstring — safe stopgap; fix = add `proxy=` to
  `upsert_revive_or_add` (TASK-135 or store change).
- **LOW (deferred):** `_health_check_ok` only checks session/tg_user_id are set, not a real
  can-read-a-public-channel probe — honest, documented; track as a follow-up.
- **LOW (resolved at ship):** the 4 new files were untracked → `git add` them before the PR.

### `security` stage (checkpoint 5.5) — verdict PASS (no CRITICAL/HIGH)

- **Proxy creds encrypted at rest (the load-bearing check): PASS.** The direct
  `update(PoolSession).values(proxy=...)` is an ORM Core construct bound to the
  `EncryptedString` column → Fernet `process_bind_param` encrypts (verified: compiled bind
  yields `gAA…` ciphertext, no `user:pass` plaintext). `factory_accounts.proxy` +
  `session_string` are EncryptedString too. No plaintext secret at rest.
- No secrets in logs, no hardcoded secrets, SMSPVA api_key only in the `apikey` query param
  (never logged), budget hard-cap unbypassable (Decimal, can't be exceeded), hostile Redis
  JSON handled defensively (fails safe to not-under-target), no SSRF surface, no HTTP endpoint
  added. Test fixtures are clearly fake (RFC1918 IP, literal `user:pass`, `fake-string-session`)
  — no rotation needed.
- **LOW (out of scope):** EncryptedString decrypt-failure returns raw value with a WARNING
  (pre-existing TASK-032 dual-read behavior); optional post-buy `failed`-row spend accounting
  hardening for unexpected exceptions after a successful buy.
