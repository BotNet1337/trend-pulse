---
id: TASK-139
title: ProxyProvider abstraction (base + Fake + Mobileproxy.space + env-select)
status: planned
owner: backend
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: ""
tags: [account-factory, proxy, socks5, abstraction, mobileproxy, layer-b]
---

# TASK-139 — ProxyProvider abstraction (B-proxy/1)

> Mirror the `SmsProvider` abstraction (TASK-133) for proxies: a `ProxyProvider` Protocol +
> `ProxyLease` DTO, a deterministic `FakeProxyProvider`, a real `MobileProxyProvider` over
> httpx, and env-based selection — so `factory_tick` (TASK-140) depends ONLY on the interface.

## Context
The factory currently assigns proxies from a STATIC env pool
(`config.account_factory_proxy_pool_list` → pure `factory.service.assign_proxy`). This task adds
a DYNAMIC allocate/release provider behind an interface, leaving the static path as the default
no-provider fallback. Mirror exactly:
- `backend/src/factory/providers/base.py` (`SmsProvider` Protocol + `PurchasedNumber` DTO),
- `backend/src/factory/providers/fake.py`, `.../smspva.py` (httpx, secret-redaction),
- `backend/src/factory/providers/factory.py` (`get_sms_provider` env-select + fail-fast).
Provider chosen in `docs/research/proxy-provider-comparison.md` → Mobileproxy.space.
Money is `Decimal` (budget precision). Secrets (proxy URI, API token) are NEVER logged.

## Goal
New package `backend/src/factory/proxy/` exposing a `ProxyProvider` interface + `ProxyLease`
DTO, a `FakeProxyProvider` (no network), a `MobileProxyProvider` (httpx), and a
`get_proxy_provider(settings)` env-selector. Default (`ACCOUNT_FACTORY_PROXY_PROVIDER` unset)
→ `None` (caller keeps today's static-pool path). `fake` → `FakeProxyProvider`. `mobileproxy`
→ requires `MOBILEPROXY_API_TOKEN` else `FactoryError` (fail fast, never silent fallback).
No network in CI.

## Discussion
- Q: Default activation? → A: provider-driven, mirror SMS → Decision:
  `account_factory_proxy_provider: str = ""`; unset/empty → `get_proxy_provider` returns
  `None` = "no dynamic provider, use static pool" (zero behavior change). `fake` = test
  provider (used by the integration test in 140). `mobileproxy` = live.
- Q: `ProxyLease` fields? → A: minimum the caller needs to use + release + budget + sticky →
  Decision: frozen dataclass `ProxyLease(lease_id: str, uri: str, country: str | None,
  expires_at: datetime | None)`. `uri` (socks5://user:pass@host:port) is a SECRET; `lease_id`
  is the opaque provider port id (non-secret) used by `release` + persisted for later release.
- Q: Which provider, and the unverified-wire-format risk? → A: Mobileproxy.space (only one
  natively weeks-sticky + mobile = lowest ban; see research) → Decision: implement against the
  documented SDK semantics with **configurable base_url + Bearer auth**; deterministic mocked-
  httpx unit tests make correctness vendor-format-independent; the exact wire format is
  confirmed on the free 2h trial at the final gate. IPRoyal kept as documented alternative.
- Q: `release` error behavior? → A: best-effort, mirror `SmsProvider.cancel`/`finish` →
  Decision: `release` never raises (logs a warning) — releasing a dead proxy must not mask the
  surrounding registration outcome.
- Q: Rotate API? → A: not needed — stickiness = never rotate → Decision: NO `rotate` on the
  interface (out of scope; would only add a foot-gun against the sticky invariant).

## Scope
- Touch ONLY:
  - `backend/src/factory/proxy/__init__.py` (new)
  - `backend/src/factory/proxy/base.py` (new — `ProxyProvider` Protocol + `ProxyLease`)
  - `backend/src/factory/proxy/fake.py` (new — `FakeProxyProvider`)
  - `backend/src/factory/proxy/mobileproxy.py` (new — `MobileProxyProvider` + `build_*`)
  - `backend/src/factory/proxy/factory.py` (new — `get_proxy_provider`)
  - `backend/src/factory/errors.py` (add `ProxyProviderError` + subclasses)
  - `backend/src/factory/constants.py` (add `ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE/MOBILEPROXY`,
    `MOBILEPROXY_*` base-url/endpoint/field/timeout/http-ok constants, `FAKE_PROXY_*`)
  - `backend/src/config.py` (add `account_factory_proxy_provider: str = ""`,
    `mobileproxy_api_token: str = ""`)
  - tests: `backend/tests/unit/factory/test_fake_proxy_provider.py`,
    `.../test_mobileproxy_provider.py`, `.../test_proxy_provider_factory.py`
- Do NOT touch: `factory/tasks.py` (TASK-140), `factory/service.py`, the `factory_accounts`
  model/store (TASK-140 migration), the static-pool helpers, API/UI/compose.
- Blast radius: new package + 2 config fields + new error/constants. NO schema, NO API, NO
  Celery change. `factory_tick` is wired in TASK-140, so this task ships with the provider
  unused by the runtime (interface + tests only) — verified by unit tests, no drift.

## Acceptance Criteria
- [ ] Given `ACCOUNT_FACTORY_PROXY_PROVIDER` unset, When `get_proxy_provider(settings)`, Then it
      returns `None` (caller falls back to the static pool — zero behavior change).
- [ ] Given `=fake`, When `get_proxy_provider`, Then a `FakeProxyProvider`; `allocate("KE")`
      returns a `ProxyLease` with a `socks5://` `uri`, a non-empty `lease_id`, `country=="KE"`;
      `release(lease_id)` records the release and never raises; `balance()` returns a `Decimal`.
- [ ] Given `=mobileproxy` and empty `MOBILEPROXY_API_TOKEN`, When `get_proxy_provider`, Then
      `FactoryError` (fail fast, no silent fallback to fake).
- [ ] Given `=mobileproxy` + token + a mocked httpx ok buyProxy body, When `allocate("KE")`,
      Then a `ProxyLease` is built (socks5 uri from host:port:user:pass, lease_id from the port
      id, country/expires parsed) and the api token never appears in any log/error/exception.
- [ ] Given a mocked httpx error/non-ok body, When `allocate`, Then a typed `ProxyProviderError`
      subclass (auth/unavailable/response) is raised with NO secret in the message; When
      `release` hits an error body, Then it logs + returns (never raises).
- [ ] `make ci-fast` green; mypy strict clean (no `Any`, no `type: ignore`); no network in CI.

## Plan
1. `factory/errors.py` — add `ProxyProviderError(FactoryError)` + `ProxyProviderAuthError`,
   `ProxyUnavailableError`, `ProxyProviderResponseError` (mirror the `SmsProvider*` hierarchy).
2. `factory/constants.py` — `ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE="fake"`,
   `ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY="mobileproxy"`; `MOBILEPROXY_BASE_URL`,
   `MOBILEPROXY_HTTP_TIMEOUT_SECONDS`, http-ok floor/ceil, endpoint paths + JSON field names
   for buyProxy/refundProxy/getBalance, `MOBILEPROXY_PROXY_SCHEME="socks5"`; `FAKE_PROXY_*`
   deterministic host/port/creds.
3. `factory/proxy/base.py` — `@dataclass(frozen=True) ProxyLease`; `@runtime_checkable`
   `ProxyProvider` Protocol: `allocate(country: str | None) -> ProxyLease`,
   `release(lease_id: str) -> None`, `balance() -> Decimal`, `aclose() -> None`.
4. `factory/proxy/fake.py` — `FakeProxyProvider`: deterministic lease (uri from `FAKE_PROXY_*`
   + a counter/country-derived id), tracks released ids in a set, `balance()` constant Decimal.
5. `factory/proxy/mobileproxy.py` — `MobileProxyProvider(api_key, client, base_url)` over httpx
   (mirror `smspva.py`): `_call` GET/POST with Bearer header; `allocate`→buyProxy (build
   socks5 uri + lease_id), `release`→refundProxy (best-effort, never raises), `balance`→
   getBalance (Decimal). Redact: suppress httpx `__cause__` (`from None`), never echo body/uri/
   token; errors name the endpoint only. `build_mobileproxy_provider(api_key, base_url, timeout)`
   lazy factory (no network at import).
6. `factory/proxy/factory.py` — `get_proxy_provider(settings) -> ProxyProvider | None`:
   match `settings.account_factory_proxy_provider` → `""`/unknown-default → `None`; `fake` →
   `FakeProxyProvider()`; `mobileproxy` → token-or-`FactoryError` → `build_mobileproxy_provider`.
7. `config.py` — add the two fields (documented comments mirroring the SMS ones).
8. Tests — fake (allocate/release/balance/geo), mobileproxy (mocked httpx ok/err + redaction),
   provider-factory (selection + fail-fast).

## Invariants
- Default (provider unset) → `get_proxy_provider` returns `None`; runtime behavior unchanged.
- `release` NEVER raises. `allocate`/`balance` raise ONLY typed `ProxyProviderError` subclasses.
- The proxy URI and API token are NEVER logged, echoed in errors, or chained via `__cause__`.
- `ProxyLease` is immutable (`frozen=True`). Money is `Decimal`.
- No `Any`, no `# type: ignore`; all constants named; no network in unit tests.

## Edge cases
- Empty/whitespace token with `=mobileproxy` → `FactoryError` (treated as unconfigured).
- buyProxy body missing host/port/id → `ProxyProviderResponseError` (no secret leaked).
- refundProxy on an already-released/expired lease → best-effort log, return.
- Unknown provider string → `None` (static-pool fallback), not a crash.
- httpx transport error → `ProxyProviderResponseError` with `from None` (no URL/token in cause).

## Test plan
- unit `test_fake_proxy_provider.py`: allocate returns socks5 lease + country; release no-raise +
  recorded; balance Decimal.
- unit `test_mobileproxy_provider.py`: mocked `httpx.AsyncClient` (MockTransport) — allocate ok
  builds lease; auth/non-ok → typed error; transport error → response error; release error body →
  no raise; **assert token/uri absent** from `str(exc)` and caplog.
- unit `test_proxy_provider_factory.py`: unset→None; fake→Fake; mobileproxy+token→Mobile;
  mobileproxy+empty→FactoryError.

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
- [ ] 5.5 security (touches secrets/proxy creds → YES)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
