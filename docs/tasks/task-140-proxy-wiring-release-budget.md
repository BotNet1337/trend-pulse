---
id: TASK-140
title: Wire dynamic ProxyProvider into factory_tick — allocate/release/budget + mig 0029
status: planned
owner: backend
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: ""
tags: [account-factory, proxy, factory-tick, budget, migration, layer-b]
---

# TASK-140 — proxy wiring + release + budget (B-proxy/2)

> When a `ProxyProvider` is configured, `factory_tick` allocates a fresh sticky proxy per buy,
> registers + holds the account through it, persists the lease (encrypted uri + non-secret
> lease_id), **releases** it on registration failure / banned / revoke, and accounts its cost
> in the hard budget. Default (no provider) keeps today's static-pool path byte-for-byte.

## Context
TASK-139 ships the `ProxyProvider`/`ProxyLease` interface + `get_proxy_provider`. This task
wires it into `backend/src/factory/tasks.py` (`_buy_phase` / `_provision` / off-ramps).
Today: static pool via `account_factory_proxy_pool_list` + pure `assign_proxy`; `_provision`
already releases the NUMBER on failure (`provider.cancel`, #213); `_promote_phase` already
carries `record.proxy` onto the pool row. `factory_accounts.proxy` is already an encrypted
column; there is NO lease-id column yet — needed so `release(lease_id)` works after persistence.

## Goal
`factory_tick`, when `get_proxy_provider(settings)` is not `None`:
1. `_buy_phase` → `lease = proxy_provider.allocate(country=settings.account_factory_country)`;
2. pass `lease.uri` into `_provision` → `registrar.register(proxy=lease.uri)`;
3. persist `proxy=lease.uri` (encrypted) + `proxy_lease_id=lease.lease_id` on the row;
4. `proxy_provider.release(lease.lease_id)` best-effort on registration failure / banned /
   timeout / failed off-ramp (mirror the number `cancel`, never raises, never masks);
5. account the proxy cost in the budget (`can_afford` / `total_spent_usd` stay exact).
When `get_proxy_provider` is `None` → EXACT current static-pool behavior (no regression).

## Discussion
- Q: Budget accounting for proxy cost? → A: add a per-account proxy price → Decision: new
  `account_factory_proxy_price_usd: Decimal = 0` setting; the row's `cost_usd` becomes
  `number_price + proxy_price` so `total_spent_usd` (already summed) and `can_afford` remain
  exact with NO new counter. Default 0 → no budget change for existing/static-pool paths.
- Q: Where does `proxy_lease_id` live? → A: factory_accounts only → Decision: mig 0029 adds a
  nullable non-secret `proxy_lease_id` String col; the pool row needs only the URI (already
  carried), so `pool_sessions` is untouched. Release uses the factory row's lease_id.
- Q: Allocate vs the static pool — both? → A: provider XOR static → Decision: if provider
  configured, IGNORE the static pool (allocate dynamically); else use the static pool exactly
  as today. The `_used_proxies` exhaustion guard applies only to the static path.
- Q: Release on the SmsNumberUnavailable off-ramp (no number bought)? → A: allocate AFTER a
  number is secured to avoid paying for a proxy with no number → Decision: allocate inside the
  buy flow only once a number is in hand; if allocate itself fails, cancel the number + skip.
  Net: never hold a proxy without a number, never hold a number without releasing on failure.
- Q: Release on promote/expiry? → A: NO — sticky for life → Decision: a promoted account KEEPS
  its proxy (carried to the pool row); release happens only on failure/banned/revoke off-ramps.

## Scope
- Touch ONLY:
  - `backend/migrations/versions/0029_factory_proxy_lease_id.py` (new — add `proxy_lease_id`)
  - `backend/src/storage/models/factory_accounts.py` (add `proxy_lease_id` mapped col)
  - `backend/src/storage/factory_account_store.py` (thread `proxy_lease_id` through
    `create_purchased` + the record dataclass)
  - `backend/src/factory/tasks.py` (`_buy_phase`, `_provision`, off-ramps — allocate/release/cost)
  - `backend/src/factory/constants.py` (`FACTORY_PROXY_LEASE_ID_MAX`)
  - `backend/src/config.py` (`account_factory_proxy_price_usd`)
  - tests: `backend/tests/unit/factory/test_provision_proxy.py`,
    `backend/tests/integration/test_factory_tick.py` (extend), store test (extend)
- Do NOT touch: the `ProxyProvider` package (TASK-139, consumed only), API/UI, compose (142),
  the health-probe (141), `_promote_phase` proxy-carry (already correct).
- Blast radius: migration 0029 (additive nullable col); `factory_tick` flow; `factory_accounts`
  store signature. NO public API change (factory_accounts is internal) → no openapi drift.

## Acceptance Criteria
- [ ] Given no proxy provider configured, When a tick buys, Then the static-pool path runs
      exactly as before (assign_proxy, `_used_proxies` guard) — no behavior change; existing
      `test_factory_tick` passes unmodified.
- [ ] Given `=fake` proxy provider, When a tick buys under target+budget, Then `allocate` is
      called with the configured country, `register` receives `lease.uri`, and the row persists
      `proxy==lease.uri` + `proxy_lease_id==lease.lease_id`.
- [ ] Given the registration fails (Telegram rejects), When the off-ramp runs, Then BOTH the
      number is cancelled (existing) AND `proxy_provider.release(lease_id)` is called once;
      neither raises nor masks the original error; the row records the failure with its cost.
- [ ] Given a promoted account, When promotion runs, Then its proxy URI is carried onto the
      pool row (existing) and the proxy is NOT released (sticky for life).
- [ ] Given `account_factory_proxy_price_usd>0`, When buying, Then `cost_usd ==
      number_price + proxy_price` and `can_afford` refuses once `spent + that ≥ budget`.
- [ ] `make ci-fast` + `make test-integration` (factory_tick, real pgvector) green; migration
      0029 applies + downgrades cleanly.

## Plan
1. mig `0029_factory_proxy_lease_id.py` — `op.add_column('factory_accounts',
   sa.Column('proxy_lease_id', sa.String(FACTORY_PROXY_LEASE_ID_MAX), nullable=True))`; downgrade
   drops it. (Non-secret → plain String, not EncryptedString.)
2. `factory/constants.py` — `FACTORY_PROXY_LEASE_ID_MAX: Final = 128`.
3. `storage/models/factory_accounts.py` — add nullable `proxy_lease_id: Mapped[str | None]`.
4. `storage/factory_account_store.py` — `create_purchased(..., proxy_lease_id: str | None = None)`
   persists it; add `proxy_lease_id` to the record dataclass.
5. `config.py` — `account_factory_proxy_price_usd: Decimal = Decimal("0")` (named default const).
6. `factory/tasks.py`:
   - `_buy_phase`: `proxy_provider = get_proxy_provider(settings)`. If not None → skip the
     static pool; the proxy is allocated inside `_provision`. If None → today's static path.
   - `_provision(provider, registrar, proxy_provider, *, country, static_proxy)`: after
     `buy_number`, if `proxy_provider` → `lease = await proxy_provider.allocate(country)`
     (on failure: cancel number, re-raise); use `lease.uri` for register; on register failure
     → `provider.cancel(number)` + `proxy_provider.release(lease.lease_id)`; return the lease.
   - Persist `proxy`/`proxy_lease_id` from the lease (or the static proxy) on `create_purchased`;
     add `proxy_price` to `cost_usd`.
   - Banned/timeout/failed off-ramps: release the lease best-effort if one was allocated.
7. Tests — unit `_provision` proxy paths (allocate, release-on-failure, sticky-on-success);
   integration tick on FakeProxyProvider (persist lease + cost, release on failure, static
   fallback unchanged); store test for `proxy_lease_id`.

## Invariants
- One proxy per account; a promoted/in-flight account's proxy is never reused (static guard) /
  never released until a failure off-ramp.
- Budget hard-cap stays exact (`cost_usd` = number+proxy; `total_spent_usd` persisted).
- `release` is best-effort and never masks the registration result (mirror `cancel`, #213).
- No number held without a proxy-release path; no proxy held without a number.
- Secrets (uri, session) never logged; `proxy_lease_id` is non-secret.
- No `Any`/`type: ignore`; migration additive + reversible.

## Edge cases
- allocate fails after number bought → cancel number, skip buy this tick (budget reflects the
  number only if the provider already charged; record a failed row with number cost).
- provider configured but `allocate` returns a non-socks5 uri → treated as a provider response
  error upstream (139); tick logs + skips (best-effort tick never crashes).
- static pool exhausted (no provider) → existing skip (unchanged).
- migration on a DB with existing rows → `proxy_lease_id` NULL (fine; release no-ops on NULL).

## Test plan
- unit: `_provision` with FakeProxyProvider — success persists lease; register-fail releases +
  re-raises; allocate-fail cancels number. Budget cost = number+proxy.
- integration (`test_factory_tick`): fake provider end-to-end (buy→register→probation→promote,
  proxy on pool row, lease persisted); release-on-failure; provider-unset static path unchanged.
- store: `create_purchased` round-trips `proxy_lease_id`.

## Checkpoints
current_step: 3
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (touches secrets + migration → YES)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
