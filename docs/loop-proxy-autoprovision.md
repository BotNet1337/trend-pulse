# Loop runbook — EPIC-PROXY-AUTOPROVISION (auto proxy per factory account)

**Goal:** account-factory automatically allocates a fresh residential/mobile **SOCKS5**
proxy (country-matched, **sticky for the account's whole life**) for every new account via a
**proxy-as-a-service API**, registers + holds the account through that proxy (IP-affinity
across probation and in the live pool), and **releases** the proxy on rejection/revoke — to
raise registration-survival and cut Telegram bans. Mirrors the `SmsProvider` abstraction
(TASK-133) and wires into `factory_tick` (TASK-134).

**Why (proven live 2026-06-20):** real KE number bought ($0.10) but Telegram returned
`PhoneNumberInvalidError` on `send_code` — the structural ban-risk the epic flagged. A
country-matched residential/mobile proxy per account is the mitigation.

## Scope (this loop only) — tasks 139–142

| Task | Title | Layer |
|------|-------|-------|
| 139 | **Proxy provider abstraction** — `factory/proxy/{base,fake,<vendor>,factory}.py`: `ProxyProvider` Protocol (`allocate(country)→ProxyLease`, `release(lease_id)`, `balance()/usage()`), `ProxyLease` DTO (socks5 URI=secret, lease_id, country, expires_at); real vendor over httpx (mirror `smspva.py`); env-selected `ACCOUNT_FACTORY_PROXY_PROVIDER` (default `fake`/unset → static-pool/no-op as today). Unit tests fake + mocked httpx. | abstraction |
| 140 | **Wiring + release + budget** — in `_buy_phase`/`_provision`: when a proxy-provider is configured, `allocate(country=<number country>)` per buy, pass `lease.uri` to `registrar.register(proxy=)`, persist `proxy` (encrypted, exists) + new non-secret `proxy_lease_id` col (**migration 0029**); `release(lease_id)` best-effort on registration failure / banned / revoke (mirror number `cancel`, #213); proxy `cost_usd` into the budget accounting; carry proxy to promote (already wired). Integration test on fakes. | wiring |
| 141 | **Honest health-probe + warming** — `_health_check_ok` → real read of a public channel through the account's **session + proxy** (reuse `parse_socks5_proxy`); promotion only when the account actually reads over its proxy. Optional light warming pre-promote. Config-gated; fake path stays deterministic. | health |
| 142 | **Infra / docs / vault** — `ACCOUNT_FACTORY_PROXY_*` env in `config.py` + compose (dev+release) + ops/ansible (key via **vault**, no clear secret) + docs + ADR `adr-proxy-autoprovision`. | infra |

Provider choice (quality+price) is decided in **Phase 0 research** →
`docs/research/proxy-provider-comparison.md` (≥5 providers, comparison table, one
recommendation with proof links). SMSPVA Rent/rental API evaluated there as an alternative.

## Constraints (hard)
- **SOCKS5**; **one proxy per account**; **sticky the whole life**; secrets (URI, API key) =
  `EncryptedString`/vault, **never** in logs/Redis/API responses.
- **Provider-gated**: default `fake`/unset → **0 spend / 0 network** (exactly as today).
- Full type hints, **no `Any`/`type:ignore`**, named constants, domain errors.
- `make` only; branches `gsd/phase-*` (or `task/NNN-*`); **`make ci-fast` green**;
  **openapi-drift green** if API touched.

## Execution mechanism (per established epic pattern)
Orchestrator (main loop) advances ONE task at a time, sequentially (shared `factory/`,
`config.py`, `tasks.py`):
1. Plan via `/trendpulse-plan` (epic + task docs 139–142, `baseline_commit`, index updated).
2. For each task: run `/trendpulse-executor TASK-NNN` (real skill) → do(TDD)→verify→review→ship PR.
3. Auto-merge per [[trendpulse-loop-autonomy]]: `gh pr merge --squash --admin` (NO
   `--delete-branch` in multiworktree; delete remote ref via `gh api -X DELETE`). Perma-red
   non-blocking checks (depsec/openapi-drift when API untouched) → `--admin`.
4. Bookkeep: task status→done, update `tasks-index.md`.
5. Next task. Only do git ops in the shared tree when NO task agent is active.

## Verify (per task) + FINAL DoD gate
- Per task: `make ci-fast` + targeted unit/integration (real pgvector where needed) green.
- **Real proxy connectivity proof** (owner key, in budget): `allocate` a sticky country
  SOCKS5 via the chosen provider → prove SOCKS5 works (resolve egress IP through it) →
  `release`. Honest report.
- **Real e2e** (owner-approved, in budget): cheap number + country-matched proxy + register
  THROUGH the proxy → **honest** report whether Telegram accepted (metric: success-rate with
  proxy vs without). Refund number + release proxy on failure. **Never fabricate success.**
- Final DoD-validator: one check per acceptance criterion across 139–142.

## Honesty constraint
Real proxy/SMS spend is provider+key gated and **not** auto-run in CI. The full pipeline is
proven deterministically on **FakeProxyProvider + FakeSmsProvider + FakeRegistrar**. Live
proxy/number cycles run only with the owner-supplied key, within the USD budget, and are
reported **as-is** — Telegram may still reject; report the real outcome.
