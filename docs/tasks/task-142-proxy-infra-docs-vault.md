---
id: TASK-142
title: Proxy infra — MOBILEPROXY_API_TOKEN via vault, compose dev+release, ops/ansible, docs, ADR
status: planned
owner: infra
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: ""
tags: [account-factory, proxy, infra, compose, ansible, vault, adr]
---

# TASK-142 — proxy infra / docs / vault (B-proxy/4)

> Make the proxy provider deployable: pass `ACCOUNT_FACTORY_PROXY_*` to the account-factory
> service in compose (dev+release), render `MOBILEPROXY_API_TOKEN` from the vault (never clear),
> document it, and record the decision in an ADR. Mirrors TASK-137 (SMSPVA infra).

## Context
TASK-137 wired the account-factory service into compose dev+release + ops/ansible with the
SMSPVA key via vault. TASK-139 added the `account_factory_proxy_provider` / `mobileproxy_api_token`
settings. This task gives them the same deploy treatment so a live proxy run is possible by
config alone (owner-gated). Follow the exact SMSPVA key pattern (no clear secret in compose,
git, or logs). `make ansible-unpack` renders secrets from the encrypted vault.

## Goal
- account-factory service (dev + release compose) receives `ACCOUNT_FACTORY_PROXY_PROVIDER`,
  `MOBILEPROXY_API_TOKEN`, `ACCOUNT_FACTORY_PROXY_PRICE_USD`, `ACCOUNT_FACTORY_HEALTH_PROBE_CHANNEL`.
- `MOBILEPROXY_API_TOKEN` is rendered from the vault (mirror the SMSPVA key); never clear-text.
- Docs in `development/` + `release/` explain enabling the proxy provider + cost/budget.
- ADR `adr-proxy-autoprovision` records: Mobileproxy.space choice, dedicated-mobile-as-sticky,
  the `ProxyProvider` abstraction, IPRoyal alternative, the SMSPVA-rental follow-up.

## Discussion
- Q: New service or reuse account-factory? → A: reuse → Decision: the proxy provider runs INSIDE
  the existing account-factory worker (TASK-137) — only env vars are added, no new container.
- Q: Secret handling? → A: identical to SMSPVA → Decision: `MOBILEPROXY_API_TOKEN` lives in the
  encrypted vault, rendered by `make ansible-unpack`; compose references the env var, never the
  literal; egress allowed, no edge exposure.
- Q: API/openapi impact? → A: none → Decision: no API surface change → openapi-drift must stay
  green (this task touches only compose/ansible/docs/ADR + possibly a `.env.example` comment).

## Scope
- Touch ONLY:
  - dev compose fragment for account-factory (add the 4 env vars)
  - release compose fragment for account-factory (add the 4 env vars)
  - `ops/ansible/` per-service env + vault template (render `MOBILEPROXY_API_TOKEN`)
  - `.env.example` / dev env template (commented, no real value)
  - `docs/development/*` + `docs/release/*` (enable-proxy section)
  - `docs/architecture/adr-proxy-autoprovision.md` (new)
  - `docs/tasks/tasks-index.md` + epic doc cross-link
- Do NOT touch: backend code (139–141), API/UI, the SMSPVA wiring (reuse its pattern).
- Blast radius: compose env + ansible vault rendering + docs. NO code, NO schema, NO API.

## Acceptance Criteria
- [ ] Given the dev + release compose, When rendered/validated (`make` config validate), Then the
      account-factory service exposes `ACCOUNT_FACTORY_PROXY_PROVIDER`, `MOBILEPROXY_API_TOKEN`,
      `ACCOUNT_FACTORY_PROXY_PRICE_USD`, `ACCOUNT_FACTORY_HEALTH_PROBE_CHANNEL`; config is valid.
- [ ] Given the vault, When `make ansible-unpack`, Then `MOBILEPROXY_API_TOKEN` is rendered from
      the encrypted vault — the literal token is NOWHERE in compose/ansible/git history.
- [ ] Given the docs, When an operator reads `development/`+`release/`, Then enabling the proxy
      provider (set provider=mobileproxy + token + budget) is documented with the cost note.
- [ ] ADR `adr-proxy-autoprovision` records the decision + alternatives + the rental follow-up.
- [ ] `make ci-fast` + openapi-drift green (no API change); compose config validates.

## Plan
1. dev compose — add the 4 env vars to the account-factory service (mirror SMSPVA key line).
2. release compose — same.
3. ops/ansible — add `MOBILEPROXY_API_TOKEN` to the vault template + the service env map
   (mirror the SMSPVA key task); document the vault key.
4. `.env.example` — commented entries (no real value).
5. docs — `development/` + `release/` "Enable proxy auto-provisioning" subsection (provider,
   token via vault, `ACCOUNT_FACTORY_PROXY_PRICE_USD` budget interaction, sticky/one-per-account).
6. ADR `adr-proxy-autoprovision.md` — decision, comparison summary (link the research doc),
   IPRoyal alternative, SMSPVA-rental follow-up, security (vault-only secret).
7. tasks-index + epic cross-links.

## Invariants
- The proxy API token is NEVER clear-text in compose, ansible, git, or logs — vault only.
- No new container; account-factory reuses its TASK-137 service definition.
- No API/schema change → openapi-drift green.
- compose dev + release both validate.

## Edge cases
- Token unset in vault → provider stays unconfigured → factory uses the static pool / no-op
  (139 default) — deploy still valid, no crash.
- Operator sets provider=mobileproxy but no token → `FactoryError` fail-fast at runtime (139),
  documented as the expected misconfig signal.

## Test plan
- `make` compose config validate (dev + release).
- `make ansible-unpack` dry-run / template lint → token from vault, no literal.
- openapi-drift check green (no API change).
- doc review: enable-proxy section present + accurate.

## Checkpoints
current_step: 6
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: gsd/epic-proxy-autoprovision
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (infra: compose dev+release, ansible vault, docs, ADR)
- [x] 4 verify (compose env refs; no backend → openapi-drift unaffected)
- [x] 5 review (orchestrator: mirrors TASK-137 exactly)
- [x] 5.5 security (orchestrator-verified: token vault-only, no literal anywhere, prod off-by-default)
- [ ] 6 ship (epic PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)

## Details
- Done (orchestrator-finalized after the do-agent stalled on watchdog at the bookkeeping step; infra work was complete + verified, only the commit/checkpoint update remained).
- compose dev+release: 4 env vars on account-factory (ACCOUNT_FACTORY_PROXY_PROVIDER, MOBILEPROXY_API_TOKEN, ACCOUNT_FACTORY_PROXY_PRICE_USD, ACCOUNT_FACTORY_HEALTH_PROBE_CHANNEL) as `${VAR:-default}` refs — no literals; visible in `docker compose config`.
- ansible: MOBILEPROXY_API_TOKEN rendered from vault via `{{ vault_mobileproxy_api_token | default('') }}` in sensitive.env.j2 (mirrors vault_smspva_api_key); non-secret proxy settings in deploy.env.j2 + group_vars (dev=fake, prod=off).
- ADR adr-proxy-autoprovision.md (Accepted) links the research doc + related ADRs; SECURITY: token vault-only verified via `rg` — literal appears NOWHERE in compose/ansible/git.
- No backend/src/migration touched → openapi-drift unaffected (stays green from TASK-141 state).
