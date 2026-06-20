---
id: TASK-143
title: SmsPvaRentProvider — SMSPVA Rental (rent.php) real-SIM numbers (opt29) Telegram accepts
status: in-progress
owner: backend
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 4f53763
branch: gsd/phase-143-smspva-rent
tags: [account-factory, smspva, rental, sms-provider, telegram, layer-b]
---

# TASK-143 — SmsPvaRentProvider (rent.php, real-SIM opt29)

> The factory used SMSPVA **Activation** (`get_number`, service `opt1`) — live-proven that
> Telegram rejects those numbers (`PhoneNumberInvalid`) or they never receive the SMS. SMSPVA
> **Rental** (`/api/rent.php`, service `opt29`) leases long-lived REAL-SIM numbers Telegram
> accepts. Add a `SmsPvaRentProvider` satisfying the EXISTING `SmsProvider` Protocol so
> `factory_tick` is UNCHANGED — only a new provider impl + env-select.

## Goal
A new `SmsPvaRentProvider` (httpx, mirrors `smspva.py` structure + secret-redaction) that maps
the Rental create→activate→state-poll→sms flow onto the `SmsProvider` interface:
- `buy_number` → `create(dtype,dcount,country,service=opt29)` → `activate(id)` → poll `orders`
  until `state==1` (bounded) → `PurchasedNumber(id, ccode+pnumber)`.
- `poll_code` → poll `sms(id)`; take the max-`date` SmsList entry; regex (`RENT_CODE_REGEX`) the code.
- `finish` → **NO-OP** (a rented number is KEPT alive for re-login during probation).
- `cancel` → `delete(id)` best-effort (release a failed registration; never raises).
- `balance` → rent.php has no balance method → the activation `priemnik.php` endpoint.
- Env-select: `ACCOUNT_FACTORY_PROVIDER=smspva_rent` (+ non-empty `SMSPVA_API_KEY`, fail-fast).

## Scope (surgical, in-scope files only)
- `backend/src/factory/providers/smspva_rent.py` (new — `SmsPvaRentProvider` +
  `build_smspva_rent_provider`).
- `backend/src/factory/constants.py` (`ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT` + `RENT_*` block).
- `backend/src/config.py` (`account_factory_rent_dtype`/`_dcount`; reuses `smspva_api_key`).
- `backend/src/factory/providers/factory.py` (`get_sms_provider` `smspva_rent` branch, fail-fast).
- `backend/tests/unit/factory/test_smspva_rent_provider.py` (new, mocked httpx) +
  `test_provider_factory.py` (new branch).

`factory_tick` (`factory/tasks.py`), `smspva.py`, and the proxy module are UNTOUCHED.

## Notes
- The `service` arg of `buy_number` (the activation slug `opt1`) does NOT apply to rentals —
  `create` always uses the configured rental service (`opt29`). Documented in code.
- The envelope `status` is an INTEGER (1 ok / 0 fail-with-`msg`). `status:0` `msg` is matched
  against documented fragments → typed errors (no stock → `SmsNumberUnavailableError`, auth →
  `SmsProviderAuthError`, insufficient-balance/bad-id/duration → `SmsProviderResponseError`).
- Secret-redaction mirrors `smspva.py`: the `apikey` is a query param only; error messages name
  the method/status only and never echo the body/params/key; `from None` suppresses httpx
  `__cause__` (which carries the apikey-bearing URL).

## Checkpoints
current_step: 6

- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — make ci-fast green: ruff format/check, mypy, 1436 tests pass; 25 new/factory tests)
- [x] 5 review (auto, adversarial — fixes applied, see Details)
- [x] 5.5 security (apikey/secret redaction in the new provider → YES)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)

## Details

### Review fixes (2026-06-20)
- **[HIGH] Registrar gate (`factory.py`):** `get_registrar` previously wired the real
  `TelethonRegistrar` only for `smspva` (Activation), so `smspva_rent` fell through to
  `FakeRegistrar` even with telegram creds present — it would lease a real SIM then
  "register" against the fake, burning rental money with NO real Telegram account created.
  Fixed: the gate now accepts BOTH `ACCOUNT_FACTORY_PROVIDER_SMSPVA` and
  `ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT` (creds still required; absent → `FakeRegistrar`).
  Docstring updated; two new tests in `test_provider_factory.py` (rent+creds → Telethon,
  rent w/o creds → Fake).
- **[LOW] Code-extraction regex (`constants.py`):** `RENT_CODE_REGEX` tightened from
  `\d{4,7}` to `(?<!\d)\d{5,6}(?!\d)` so it can't partially match a longer digit run (e.g.
  a phone number in the SMS body); Telegram login codes are 5-6 digits. Bounded → ReDoS-safe.
  New test feeds a body with both a 10-digit phone number and the real 5-digit code.
- **[LOW] Auth-message matching (`smspva_rent.py`):** dropped the bare `"auth"`/`"apikey"`
  fragments (false-positive prone); kept specific `"invalid apikey"`, `"api key"`,
  `"unauthorized"`, `"invalid key"`. Existing auth test ("Invalid apikey") stays green.
