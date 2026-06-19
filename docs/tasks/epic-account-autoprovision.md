---
id: EPIC-ACCOUNT-AUTOPROVISION
title: Account auto-provisioning + pool durability (Layer A + account-factory service)
status: planned
owner: backend+frontend+infra
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [telegram, pool, account-factory, sms-provider, proxy, probation, source, reliability, autonomy]
---

# EPIC — Account auto-provisioning + pool durability

> Pool accounts must be added by hand (QR only), get kicked (AuthKeyDuplicated/ban → quarantine →
> manual re-mint), and are fragile under load (POOL_MIN=1, no proxy-per-session, no channel sharding).
> This epic makes the pool **self-healing**: a separate `account-factory` service buys a number,
> registers a Telegram account, **holds it on probation (1–2 weeks)**, and only then promotes the
> session into the live pool with `source='auto'` — within a hard USD budget cap. Manual QR add stays.
> The UI clearly shows **which accounts were added automatically vs by the owner** (`source` badge).

## Owner decision — supersedes prior gates (do not re-derive)

[TASK-059](./task-059-tg-pool-scaleout.md) Discussion previously **rejected** one-time SMS services
("accounts banned more often") and **deferred** per-account proxy to TASK-054. The owner has now
**reversed both**: proceed with SMS auto-provisioning (provider **SMSPVA** — real-SIM + rental,
`docs.smspva.com`) **plus** proxy-per-session as the durability layer that makes it viable. This
epic realises the deferred TASK-054 (fallback source / auto-warm) as the `account-factory` service.

> **ToS / risk (owner-accepted):** registering accounts via SMS providers and scraping public
> channels violate Telegram ToS; bans are a structural risk managed (not eliminated) by proxy +
> probation + aged behaviour. Accounts are **read-only collectors of public channels** only. This is
> the owner's informed business decision.

## Activation + real-key testing (owner update 2026-06-20)

- **No `ACCOUNT_FACTORY_ENABLED` flag.** Activation is **provider-driven**: `ACCOUNT_FACTORY_PROVIDER`
  unset/empty → factory tick is a no-op; `fake` → active with deterministic fakes (CI/local); `smspva`
  (+ `SMSPVA_API_KEY`) → live. The USD budget hard-cap always applies.
- **CI / unit tests** always use `FakeSmsProvider` + `FakeTelegramRegistrar` (deterministic, **zero
  spend**). The full scenario (buy → register → probation → promote → visible-in-UI `source=auto`) is
  verified on the fakes through **real API (curl)** + **real UI (Playwright)**. This reuses the DI seam
  (`TelegramClientProtocol`, injectable factories) — correct engineering, not a verification bypass.
- **Real provider testing (owner-authorised):** the owner supplied a real `SMSPVA_API_KEY` in the
  gitignored `apps/trendPulse/.env`. During verify of TASK-133/134 the real `SmsPvaProvider` is smoke-
  tested against the live SMSPVA API via **`balance()` (read-only, no spend)** to prove connectivity,
  and a **controlled, budget-capped real buy → register** may be attempted with outcomes reported
  **honestly** (Telegram often rejects VoIP/SMS-relay numbers — a real registration may fail at the
  Telegram side; that is reported as-is, not masked). The key is then **migrated into the ansible vault**
  (TASK-137); `.env` stays gitignored and is never committed.

## Stories

| Story | Layer | Scope (1-liner) | Depends on |
|---|---|---|---|
| [TASK-129](./task-129-proxy-per-session.md) | A1 | Encrypted `proxy` column on `pool_sessions` (mig 0026) + thread SOCKS5 proxy through the Telethon client factory (`account_pool` / `registry` / `qr_login`). No proxy → today's behaviour (fail-open). | 119 |
| [TASK-130](./task-130-pool-source-field.md) | A3 | `source` column on `pool_sessions` (mig 0027, enum `manual`\|`auto`, default `manual`) → carried into the `pool:health:latest` snapshot → `PoolHealthResponse` → **UI badge**. QR add stays `manual`. | 119 |
| [TASK-131](./task-131-pool-sizing-sharding.md) | A2 | Raise `POOL_MAX` (→20) and `pool_min_healthy` (→5) + **deterministic channel→slot sharding** in `reader.py` to multiply throughput / cut FLOOD_WAIT. No rotation/quarantine regression. | 119 |
| [TASK-132](./task-132-factory-accounts-store.md) | B3 | `factory_accounts` table (mig 0028) — state machine `purchased→registered→probation→promoted→failed`; encrypted `session_string`, masked `phone`, `provider`, `provider_order_id`, `proxy`, `tg_user_id`, `probation_until`, `last_error` + store service. | 119 |
| [TASK-133](./task-133-provider-abstraction.md) | B2 | `SmsProvider` interface (`buy_number`/`poll_code`/`finish`/`balance`) — `SmsPvaProvider` (REST+JSON) + `FakeSmsProvider`; `TelegramRegistrar` real (Telethon) + fake. Provider chosen by env. Pure, config-gated. | — |
| [TASK-134](./task-134-account-factory-core.md) | B1+B4+B5 | `account-factory` orchestration: buy→register→probation→**promote via `upsert_revive_or_add(source='auto')`** + relogin; **budget hard-cap** (`ACCOUNT_FACTORY_BUDGET_USD`); **probation gate** (not promoted until `probation_until` passed AND health-checks pass). Runs as a scheduled/loop service. | 129, 130, 132, 133 |
| [TASK-135](./task-135-factory-api.md) | B6 | Superuser `/factory` router: `POST /factory/accounts` (trigger N / auto), `GET /factory/accounts` (state/probation), `POST /factory/accounts/{id}/relogin`, `GET /factory/budget`. Registered in `api/main`; `make gen-openapi gen-types`. | 134 |
| [TASK-136](./task-136-factory-ui.md) | B7 | `/admin/pool` UI: factory-accounts panel (state + probation countdown), `source` badge (`manual`\|`auto`) on live pool rows, manual "Register account" trigger button. Manual QR add stays. | 135, 130 |
| [TASK-137](./task-137-factory-infra-docs.md) | infra | `development/compose/account-factory.yml` + `release/compose/account-factory.yml` (egress; postgres/redis nets; not edge) + include in both top compose; `ops/ansible` per-service config + env keys (vault, no secrets committed); `config.py` env; docs in `development/` + `release/`. | 134 |

Execution graph: `129 → 130 → 131 → 132 → 133 → 134 → 135 → 136 → 137`
(Layer A 129–131 are independent of each other and of B; 132→133→134 build the factory; 134 needs
proxy (129) + source (130) to promote with proxy+source set; 135 API over core; 136 UI over API +
source; 137 wires the service into infra/docs last.)

## Hard constraints (carried into every story)

- **NEVER run the same TG session concurrently from two clients** (AuthKeyDuplicated — see
  `adr-dynamic-pool-session-store.md` and the tg-session / deploy-vault incident memories). The
  factory registers on **fresh** sessions over their own proxy; promotion reuses the safe
  single-slot revive path; the factory never connects a session that is live in the worker pool.
- **Session strings & SMSPVA key are SECRETS** — encrypted at rest via `EncryptedString` (ADR-008),
  never logged, never in Redis plaintext, never in an API response (only masked identity / state).
- **Budget is a hard ceiling** — the factory must refuse to buy once spend would exceed
  `ACCOUNT_FACTORY_BUDGET_USD`; spend is persisted/accounted, not estimated.
- **Probation gate is mandatory** — no promotion before `probation_until` AND passing health checks.
- Full type hints, domain errors, Pydantic at the boundary, **named constants (no magic literals)**,
  surgical diffs. `make ci-fast` (ruff + mypy strict + pytest) green; `openapi-drift-check` green.
- `make` is the only entry point (no raw `docker compose`/`uv`/`pytest`). Branches `gsd/phase-{NNN}-{slug}`.
- **Compliance:** factory accounts read **public channels only**; no raw content persisted beyond 48h.
- **Do NOT deploy from this worktree** — live verify (real SMSPVA/Telegram) is owner-gated. Local +
  fake-provider verify is the DoD here.

## Verification model (real scenarios — "it builds" is not value)

Each story's `verify` stage runs **real behavioural checks**, not just a green build:

- **API via curl** against the running backend: `POST /factory/accounts` (fake provider) →
  `GET /factory/accounts` shows `registered`→`probation`; force `probation_until` into the past →
  promote → `GET /pool-admin/pool-health` shows the new account with `source=auto` and the budget
  decremented; the manual QR path still yields `source=manual`.
- **UI via Playwright**: `/admin/pool` renders factory accounts + `source` badges (manual/auto) +
  the manual register button works.
- Unit + integration on fake providers; migrations up **and** down; proxy-passthrough, sharding,
  budget hard-cap, and probation-gate each have a dedicated test.
- A final **DoD-validator agent** walks every Acceptance Criterion across the epic and returns a
  PASS/FAIL verdict with evidence (curl transcripts + Playwright artifacts).

## ADR

This epic writes `docs/architecture/adr-account-factory-provisioning.md` (the provider-abstraction +
probation + budget + proxy-per-session decision, superseding the TASK-059 "no SMS / no proxy" stance).

## Autonomy

Driven by `docs/loop-account-autoprovision.md` (a `/loop` runbook **scoped to TASK-129..137**) with an
auto-merge policy (per the established `trendpulse-loop-autonomy` memory: `--admin` when only the two
permanently-red checks remain) and a verify stage = `make ci-fast` + curl + Playwright. One task per
iteration, lowest actionable number first.
