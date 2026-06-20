# ADR — Verdict: automated account auto-provisioning is infeasible; app development PAUSED

- Status: **Accepted (verdict)**
- Date: 2026-06-20
- Supersedes the active pursuit of: [adr-account-factory-provisioning.md](./adr-account-factory-provisioning.md),
  [adr-proxy-autoprovision.md](./adr-proxy-autoprovision.md)

## Context

TrendPulse needs a pool of Telegram accounts to read public channels. The "self-healing
account factory" line of work tried to **create fresh Telegram accounts automatically** from
purchased phone numbers (SMSPVA) — Activation, then a per-account residential/mobile **proxy**,
then SMSPVA **Rental** (real-SIM). Each was built, tested, and **verified live** (2026-06-20).

## What the live tests proved (honest)

1. **Proxy does not help.** A real Moldova **mobile** SOCKS5 proxy was proven to work (egress
   `mobile:true, proxy:false`), but Telegram rejects the numbers at the **number level**
   (`PhoneNumberInvalid`) — an IP-level mitigation cannot fix a number-level rejection. (A real
   runtime gap was found+fixed along the way: `python-socks` was missing, PR #219.)
2. **SMSPVA Activation numbers are blocked.** A 12-country scout (refundable, $0 net) returned
   `PhoneNumberInvalid` for KE/ID/US/UK/ES/RO/NL/FR (Telegram blocks the ranges), no stock for
   PH/KZ/UA, and one `SentCodeTypeApp` (dirty). **No clean number.**
3. **SMSPVA Rental real-SIM numbers are recycled/dirty.** A live RO rental ($4.20) was
   **accepted** (no `PhoneNumberInvalid`) but `send_code` returned **`SentCodeTypeApp`,
   `next_type=None`** — the login code is delivered to the **previous owner's app session**, with
   **no SMS fallback**, so the number cannot be registered. No SMS ever arrived.

**Root cause:** the bottleneck is **number quality** — obtaining phone numbers that are both
Telegram-accepted AND never-previously-used-on-Telegram. Affordable bulk SMS providers do not
supply these. Neither a proxy nor longer-lived rentals change this.

## Decision

**Automated fresh-Telegram-account creation is technically infeasible with available automated
number sources.** We will **not** keep iterating on it. **App development is PAUSED** and the
**production infrastructure is torn down** (`make destroy`).

## Consequences

- The proxy epic (TASK-139–142, PR #217) stays merged but **provider-gated OFF** (zero spend).
- The SMSPVA Rent provider (TASK-143) stays on branch `gsd/phase-143-smspva-rent`, **NOT merged**.
- The account-factory stays code-gated off (`ACCOUNT_FACTORY_PROVIDER` unset → no-op).
- Prod infra (Hetzner server + app + Cloudflare DNS + backup bucket) is destroyed via the new
  `make destroy` (and `make destroy-org` for the account-level zone/email/Sentry). IRREVERSIBLE —
  back up first (`make backup`).
- If account provisioning is ever revisited, the only viable directions are **a number source
  with genuinely clean, never-used-on-Telegram numbers** (a different vendor, or owner-controlled
  physical SIMs), or **buying aged accounts** — plus a registrar `SentCode`-type fail-fast
  (treat `App`/`Call` as a dirty number → release + retry the next number).
