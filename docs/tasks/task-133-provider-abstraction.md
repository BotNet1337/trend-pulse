---
id: TASK-133
title: SMS provider + Telegram registrar abstraction (SMSPVA + fakes)
status: planned
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [account-factory, smspva, provider, telethon, di, layer-b]
---

# TASK-133 — Provider abstraction (Layer B2)

> Pluggable `SmsProvider` (buy number / poll code / finish / balance) and `TelegramRegistrar`
> (register/login → session) behind interfaces, with a real SMSPVA + real Telethon impl and
> deterministic fakes. Provider chosen by env. This is the DI seam that keeps the factory testable.

## Context
Reuse the existing DI pattern: `collector/telegram/client.py` builds Telethon lazily behind
`TelegramClientProtocol`; tests use `FakeClient` (`tests/unit/collector/conftest.py`). SMSPVA REST+JSON
API (`docs.smspva.com`): API-key auth, buy number, poll for SMS code, finish/cancel, balance; real-SIM
+ rental. The real path is **config-gated** and never runs in CI/this env (epic honesty constraint).

## Goal
- `factory/providers/base.py` — `SmsProvider` Protocol: `balance()->Decimal`, `buy_number(country,
  service)->PurchasedNumber`, `poll_code(order_id, timeout)->str`, `finish(order_id)`, `cancel(order_id)`.
- `factory/providers/smspva.py` — `SmsPvaProvider` over httpx (REST+JSON, API-key, named-constant
  endpoints/timeouts; typed responses; domain errors on non-OK).
- `factory/providers/fake.py` — `FakeSmsProvider` (deterministic numbers/codes, scripted failures).
- `factory/registrar/base.py` — `TelegramRegistrar` Protocol: `register(phone, code_cb, proxy)->RegisteredSession`.
- `factory/registrar/telethon.py` — real registrar (Telethon `send_code_request` + `sign_in`/`sign_up`,
  over the assigned proxy, returns StringSession + `tg_user_id` from `get_me()`).
- `factory/registrar/fake.py` — `FakeRegistrar` (returns a deterministic fake session).
- `factory/providers/factory.py` — `get_sms_provider(settings)` / `get_registrar(settings)` choose impl by
  `ACCOUNT_FACTORY_PROVIDER` (`smspva`|`fake`); default `fake`.

## Discussion
- Q: HTTP client? → A: httpx → Decision: already a dep; lazy import inside smspva module like telethon.
- Q: Money type? → A: Decimal → Decision: never float for USD (budget accounting precision).
- Q: How does fake simulate ban / no-code? → A: scripted → Decision: `FakeSmsProvider(scenario=...)`
  supports `ok|no_code|banned` so TASK-134 can test each branch deterministically.

## Scope
- Touch ONLY: new `factory/providers/*`, `factory/registrar/*`, `factory/constants.py` (endpoints,
  timeouts, default country/service), `config.py` (env: `ACCOUNT_FACTORY_PROVIDER`, `SMSPVA_API_KEY`).
- Do NOT touch: pool/collector/API/UI; no orchestration yet (TASK-134).
- Blast radius: new package; two new config fields.

## Acceptance Criteria
- [ ] `FakeSmsProvider` returns deterministic number+code; `ok|no_code|banned` scenarios behave as scripted.
- [ ] `SmsPvaProvider` builds correct authed requests + parses balance/buy/poll (asserted with mocked httpx);
      non-OK response → typed domain error (no silent swallow).
- [ ] `FakeRegistrar` returns a deterministic session + tg_user_id.
- [ ] `get_sms_provider`/`get_registrar` return fake by default, smspva when env set; real path never
      invoked without `SMSPVA_API_KEY`.
- [ ] Full type hints, no `Any`; secrets (`SMSPVA_API_KEY`, session) never logged.
- [ ] **Real connectivity smoke (owner key):** with `SMSPVA_API_KEY` from `.env`, `SmsPvaProvider.balance()`
      returns a real balance from the live SMSPVA API (read-only, **no spend**) — proves the real path works.
      (Captured as verify evidence; not a CI test — CI uses the fake.)

## Plan
1. `factory/constants.py` — SMSPVA base URL/endpoints, `SMS_CODE_POLL_TIMEOUT_SECONDS`, default country/service.
2. `factory/providers/base.py` + `fake.py` + `smspva.py` (httpx, mocked in tests).
3. `factory/registrar/base.py` + `fake.py` + `telethon.py` (lazy telethon).
4. `factory/providers/factory.py` — env-based selection.
5. `config.py` — `account_factory_provider` (default `fake`), `smspva_api_key` (secret, default "").

## Invariants
- Real SMSPVA/Telethon only when explicitly configured; default is fake (CI-safe).
- Decimal for money; domain errors at the HTTP boundary; secrets redacted.

## Edge cases
- SMSPVA balance too low / number unavailable → typed error → caller (134) handles.
- Code never arrives within timeout → `SmsCodeTimeoutError`.
- Telegram returns SESSION_PASSWORD_NEEDED / PHONE_NUMBER_BANNED → typed registrar errors.

## Test plan
- unit: fake scenarios; smspva request/parse with `respx`/mocked httpx; selection by env; error mapping.

## Checkpoints
current_step: 3
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — fake + mocked-httpx smspva + env selection)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (API-key + session secrets, external HTTP boundary)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
