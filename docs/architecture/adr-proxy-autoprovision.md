# ADR — proxy auto-provisioning: Mobileproxy.space per factory account

- Status: **Accepted**
- Date: 2026-06-20
- Context: TASK-139..142, EPIC-PROXY-AUTOPROVISION,
  [adr-account-factory-provisioning.md](./adr-account-factory-provisioning.md),
  [adr-005-infra-provisioning-and-secrets.md](./adr-005-infra-provisioning-and-secrets.md),
  [adr-008-at-rest-field-encryption.md](./adr-008-at-rest-field-encryption.md)

## Context

EPIC-ACCOUNT-AUTOPROVISION shipped: buy→register→probation→promote works on fakes
(TASK-132..137). A real SMSPVA number ($0.10) was purchased and Telegram rejected it with
`PhoneNumberInvalidError` at `send_code` — the structural ban-risk the epic always flagged.
Telegram blocks SMS-relay/VoIP numbers, especially when the request arrives from a datacenter
egress IP. A **country-matched mobile/residential SOCKS5 proxy per account** (mobile carrier
IP = lowest Telegram ban rate) is the proven mitigation approach for this class of problem.

Research summary in [`docs/research/proxy-provider-comparison.md`](../research/proxy-provider-comparison.md).

## Decision

### 1. Mobileproxy.space — dedicated mobile IP, unlimited sticky, programmatic API

**Selected vendor**: Mobileproxy.space (mobile dedicated, per-port GSM IP).

Decisive criteria (from the research doc, 12 providers compared):

| Criterion | Mobileproxy.space | Runner-up: IPRoyal |
|---|---|---|
| API: alloc / release | `buyProxy` / `refundProxy` / `getBalance` | `POST /access/generate-proxy-list` / `DELETE /sessions` |
| Sticky duration | **Unlimited** (rented port, IP changes only on `changeIp`) | 7 days (residential) / unlimited (dedicated mobile) |
| SOCKS5 | Yes | Yes (:32325) |
| Geo | country / city / operator | country / city / state / ISP |
| Price entry | **$33–169/IP/month**, unlimited traffic | ~$117–130/mo (dedicated mobile) |
| Auth | Bearer token | Bearer token |
| TG ban rating | **Lowest** (real GSM SIM, mobile carrier IP) | Clean, mature |

**Why over IPRoyal (runner-up):** IPRoyal's residential sticky caps at **7 days < our
14-day probation** window — this forces the more expensive dedicated mobile tier.
On a mobile-vs-mobile comparison Mobileproxy.space is both cheaper ($33 entry) and
provides better sticky guarantees. IPRoyal remains the documented swappable alternative
(set `ACCOUNT_FACTORY_PROXY_PROVIDER=iproyal`; requires adapting the HTTP client).

**Why mobile over residential rotating pools (ASocks, Decodo, Oxylabs…):** rotating
residential pools cap sticky at minutes to 24 hours — far below the 14-day probation
window. Only dedicated/rented-per-port IPs (mobile dedicated or ISP/static) satisfy
"same IP for weeks." Mobile carrier IPs additionally have the lowest Telegram ban
rate in practice, per industry consensus.

### 2. `ProxyProvider` abstraction (TASK-139) — swappable, env-selected

The `ProxyProvider` Protocol (`factory/proxy/base.py`) mirrors the `SmsProvider` design:

```python
class ProxyProvider(Protocol):
    async def allocate(self, country: str) -> ProxyLease: ...
    async def release(self, lease_id: str) -> None: ...
    async def balance(self) -> Decimal: ...
```

`ProxyLease` DTO carries `lease_id`, `socks5_uri` (encrypted at rest), `cost_usd`.

Provider selection via `ACCOUNT_FACTORY_PROXY_PROVIDER`:

| Value | Behaviour |
|---|---|
| `""` / unset | **Static pool / no dynamic proxy** — `ACCOUNT_FACTORY_PROXY_POOL` used as-is. Default in prod. |
| `fake` | **Dev mode** — deterministic leases, zero network calls, zero spend. Default in dev. |
| `mobileproxy` | **Mobileproxy.space** — Bearer token auth, `buyProxy`/`refundProxy`; requires `MOBILEPROXY_API_TOKEN` in vault. |

Provider-driven activation (not a separate `ENABLED=true/false`) mirrors the SMS provider
gating in `adr-account-factory-provisioning.md §2`. Empty string is the intuitive "off"
switch; `fake` enables CI coverage without live credentials; `mobileproxy` is the live path.

### 3. Allocate-per-buy → register THROUGH proxy → release-on-failure (TASK-140)

The `factory_tick` wiring:

1. If `ProxyProvider` is configured: call `allocate(country)` → receive `ProxyLease`.
2. Register the new account **THROUGH** the leased SOCKS5 proxy (Telethon `proxy=` arg).
3. On registration failure or Telegram ban: call `release(lease_id)` (best-effort, non-fatal).
4. On success: persist `proxy` (encrypted, `EncryptedString`/ADR-008) + `proxy_lease_id`
   in `factory_accounts` (migration 0029).
5. Promote to live pool — `pool_sessions.proxy` (migration 0026, TASK-129) carries the
   same SOCKS5 URI so the live collector uses the same IP.

`changeIp` is **never called** — the IP must remain stable for the account's entire
lifetime. IP change mid-session would break the MTProto session and defeat stickiness.

### 4. Honest health-probe before promote (TASK-141)

`_health_check_ok` stub replaced with a REAL gate: read a public Telegram channel
through the account's session + proxy (typed `HealthProbe` — `FakeHealthProbe` in dev,
`TelethonHealthProbe` in prod). Failure → mark account `failed`, release proxy, skip
promote. The probe channel is configurable via `ACCOUNT_FACTORY_HEALTH_PROBE_CHANNEL`
(empty = skip / use fake-provider behaviour).

This prevents "connected but not reading" accounts (the root cause of the TASK-118
ingest outage) from entering the live pool.

### 5. MOBILEPROXY_API_TOKEN — vault only, never clear-text (TASK-142)

The Bearer token is stored exclusively in `ops/ansible/vault/sensitive.vault.yml`
(`vault_mobileproxy_api_token`), rendered into `sensitive.env` via:

```jinja2
MOBILEPROXY_API_TOKEN={{ vault_mobileproxy_api_token | default('') }}
```

`default('')` keeps `make ansible-unpack` working on hosts where the vault key is not
yet set. An empty value causes the `mobileproxy` provider to fail fast at the first
`allocate()` call with a clear error (fail-fast > silent no-op on misconfig).

The `socks5_uri` in `factory_accounts.proxy` and `pool_sessions.proxy` is encrypted at
rest via `EncryptedString` (ADR-008 / Fernet) — the raw proxy credentials never appear
in the database, Redis, logs, or API responses.

**Rotate-after-exposure**: if the Bearer token is compromised — immediately revoke it in
the Mobileproxy.space dashboard, generate a new token, update the vault, redeploy.
Existing leases remain valid until their rental period expires; release them via the API.

### 6. SMSPVA rental follow-up (out of scope for this epic)

`docs.smspva.com` exposes a rental API (`rent.php`, `dtype=week|month`) that would allow
the same SMSPVA number to receive many SMS over a multi-day window — valuable for
accounts that need re-login / 2FA. At `~$1.10/day ($7.70/wk)` for service `opt29`
(Telegram) vs `~$0.10` one-time activation it is an economic upsell for high-value
sessions. This is a **follow-up task**, not part of this epic. The existing SMS provider
code uses the `get_number`/`finish_number` one-time path only.

## Consequences

- (+) Factory accounts are registered through a dedicated country-matched mobile IP →
  lower `PhoneNumberInvalidError` / ban rate vs datacenter egress.
- (+) Sticky IP for the account's full lifetime (probation + live pool) — MTProto session
  does not break mid-probation from IP change.
- (+) `fake` proxy provider gives CI coverage (zero spend, deterministic) — no real
  credentials needed in tests or CI.
- (+) No new container; proxy logic runs inside the existing `account-factory` worker.
- (+) `ProxyProvider` abstraction enables swapping to IPRoyal or another vendor by
  setting a single env var (`ACCOUNT_FACTORY_PROXY_PROVIDER=iproyal`).
- (+) `MOBILEPROXY_API_TOKEN` is vault-only; compose never carries the literal; git
  history is clean (verified by `rg 'MOBILEPROXY_API_TOKEN' --glob '!ops/ansible/vault'`
  returning only var-name references, never the value).
- (−) Mobileproxy.space REST auth wire format was partially UNVERIFIED in public docs at
  research time. Mitigated: (a) configurable base URL + auth header constants; (b)
  mocked-httpx unit tests (vendor-format-independent); (c) free 2h trial confirmation
  with owner key before real measurement. Exact wire format is a live-verify open item.
- (−) Mobile proxy ($33 entry) adds a per-account fixed cost. At budget "0.00" (default)
  no proxy is allocated even if the provider is set — the USD guard always applies.
- (−) Activating the proxy provider requires three explicit steps (prod.yml + vault +
  deploy) — intentional protection against accidental spend.
- (−) SMSPVA rental (re-login / 2FA resilience) is a follow-up task; not in this epic.

Влияет на: **TASK-139..142** (proxy backend + infra), **TASK-134** (factory_tick),
**TASK-129** (pool_sessions.proxy column), **ADR-005** (secrets / env-split),
**ADR-008** (at-rest field encryption for socks5_uri + API token).
