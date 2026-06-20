---
id: EPIC-PROXY-AUTOPROVISION
title: Auto residential/mobile SOCKS5 proxy per factory account (proxy-as-a-service)
status: done
owner: backend+infra
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: "gsd/epic-proxy-autoprovision"
tags: [account-factory, proxy, socks5, anti-ban, mobileproxy, epic]
---

# EPIC-PROXY-AUTOPROVISION — auto proxy per factory account

> account-factory automatically allocates a fresh **SOCKS5** residential/mobile proxy
> (country-matched, **sticky for the account's whole life**) per new account via a
> proxy-as-a-service **API**, registers + holds the account through that proxy
> (IP-affinity across probation + live pool), and **releases** it on rejection/revoke —
> to raise registration-survival and cut Telegram bans.

## Why (proven live 2026-06-20)
EPIC-ACCOUNT-AUTOPROVISION shipped: buy→sign_up→probation→promote works on fakes; a REAL
KE number ($0.10) was bought but **Telegram rejected it: `PhoneNumberInvalidError` on
send_code** — the structural ban-risk the epic always flagged. Telegram blocks SMS-service
numbers, especially from datacenter egress. A **country-matched mobile/residential proxy per
account** (mobile carrier IP = lowest ban rate) is the mitigation.

## Phase 0 — research (DONE)
`docs/research/proxy-provider-comparison.md` — ≥10 providers compared. **Decision:
Mobileproxy.space** (dedicated GSM mobile, true weeks-sticky, programmatic
`buyProxy`/`refundProxy`/`getBalance`, SOCKS5, country geo, $33 entry / unlimited traffic,
lowest TG ban). Runner-up IPRoyal (clean Bearer REST; resi sticky caps 7d < 14d probation →
swappable alternative). SMSPVA Rent (`rent.php` opt29) documented as an economic follow-up
(weeks-long numbers for re-login), not in this epic.

## Stories (sequential — shared `factory/`, `config.py`, `tasks.py`)
| Task | Title | Owner |
|------|-------|-------|
| [TASK-139](./task-139-proxy-provider-abstraction.md) | `ProxyProvider` abstraction (`factory/proxy/{base,fake,mobileproxy,factory}.py`) + `ProxyLease` DTO + env-select (default unset → static pool) | backend |
| [TASK-140](./task-140-proxy-wiring-release-budget.md) | Wire dynamic provider into `factory_tick`: allocate-per-buy → register-through → persist + `proxy_lease_id` (mig 0029) → release-on-failure → proxy cost in budget | backend |
| [TASK-141](./task-141-proxy-health-probe-warming.md) | Honest pre-promote health-probe (real public-channel read through session+proxy) + light warming; replaces `_health_check_ok` stub | backend |
| [TASK-142](./task-142-proxy-infra-docs-vault.md) | Infra: `ACCOUNT_FACTORY_PROXY_*`/`MOBILEPROXY_API_TOKEN` via vault, compose dev+release, ops/ansible, docs, ADR | infra |

## Constraints (hard, all stories)
SOCKS5; **one proxy per account**, sticky whole life; secrets (URI, API token) =
`EncryptedString`/vault, never in logs/Redis/API; **provider-gated** (default unset/`fake` →
0 spend / 0 network — exactly as today); full type hints, **no `Any`/`type:ignore`**, named
constants, domain errors; `make` only; branches `gsd/phase-NNN-*`; `make ci-fast` green;
openapi-drift green if API touched.

## Final DoD gate (after 139–142 merged)
- `make ci-fast` + targeted unit/integration green; per-AC DoD-validator across all 4 tasks.
- **Real SOCKS5 connectivity proof** (owner key, in budget): `allocate` a sticky
  country-matched SOCKS5 → resolve egress IP through it → `release`. Honest report.
- **Real e2e** (owner-approved, in budget): cheap number + country-matched proxy + register
  THROUGH the proxy → **honest** outcome (Telegram accept y/n; metric: success-rate with vs
  without proxy). Refund number + release proxy on failure. **Never fabricate success.**

## Honesty constraint
Real proxy/SMS spend is provider+key gated, NOT auto-run in CI. Full pipeline proven
deterministically on Fake{Proxy,Sms}Provider + FakeRegistrar. Live cycles run only with the
owner key, within the USD budget, reported as-is — Telegram may still reject; report reality.

Runbook: `docs/loop-proxy-autoprovision.md`. Supersedes the static
`account_factory_proxy_pool` env path (kept as the default no-provider fallback).
