---
id: TASK-141
title: Honest pre-promote health-probe (read public channel through session+proxy) + warming
status: done
owner: backend
created: 2026-06-20
updated: 2026-06-20
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: ""
tags: [account-factory, proxy, health-check, telethon, promote, layer-b]
---

# TASK-141 — honest health-probe + warming (B-proxy/3)

> Replace the `_health_check_ok` stub ("has session + tg_user_id") with a REAL gate: the
> account must actually READ a public channel through its OWN session + proxy before promotion.
> Plus a light warming touch. Keeps the fake path deterministic (no network in CI).

## Context
`factory/tasks.py::_health_check_ok` is a stub (TASK-134 left a real probe as a follow-up — this
is it). Promotion currently passes any registered, non-banned account. The Telethon read seam +
SOCKS5 parse already exist: `collector.telegram.client.parse_socks5_proxy`, and the registrar
(`registrar/telethon.py`) shows the client-over-proxy pattern. We mirror the registrar's
interface+fake+telethon split so the probe is unit-testable with no network.

## Goal
A typed `HealthProbe` seam: `FakeHealthProbe` (deterministic) + `TelethonHealthProbe` (real,
config-gated) that connects a `StringSession` over the account's proxy and reads a known public
channel (e.g. resolves + fetches ≥1 message). `_promote_phase` promotes ONLY when the probe
confirms a real read; failure → `failed` off-ramp + proxy released (140). Optional light
warming (a small bounded read/idle) before the probation gate. Provider-/creds-gated; the fake
registrar path stays a deterministic pass.

## Discussion
- Q: How honest must the probe be without breaking CI? → A: real read only when configured →
  Decision: a `HealthProbe` Protocol selected like the registrar — `TelethonHealthProbe` only
  when telegram creds + a real provider are set; else `FakeHealthProbe` (deterministic OK for a
  registered, non-banned row). The integration test uses the fake; the real probe runs only at
  the live gate.
- Q: Which channel to read? → A: a configurable public test channel → Decision:
  `account_factory_health_probe_channel: str` (default a well-known public handle); the probe
  resolves it + reads ≥1 message; empty/unset → skip the network read (fake-equivalent pass) so
  misconfig can't blackhole promotion.
- Q: Warming scope? → A: keep surgical → Decision: warming = the probe read itself (a gentle
  authenticated action over the sticky proxy) counts as the warm-up; a richer multi-day warming
  schedule is a documented follow-up, NOT in this task (avoid scope creep).
- Q: Probe failure semantics? → A: non-fatal, off-ramp → Decision: probe fail → row → `failed`
  (last_error="health probe failed") + release proxy (140 path) — never crashes the tick.

## Scope
- Touch ONLY:
  - `backend/src/factory/health/__init__.py` (new)
  - `backend/src/factory/health/base.py` (new — `HealthProbe` Protocol + result)
  - `backend/src/factory/health/fake.py` (new — `FakeHealthProbe`)
  - `backend/src/factory/health/telethon.py` (new — `TelethonHealthProbe`, lazy telethon import)
  - `backend/src/factory/health/factory.py` (new — `get_health_probe(settings)`)
  - `backend/src/factory/tasks.py` (`_health_check_ok` → call the probe; wire selection)
  - `backend/src/factory/constants.py` (probe channel default, read limit)
  - `backend/src/config.py` (`account_factory_health_probe_channel`)
  - tests: `backend/tests/unit/factory/test_health_probe.py`,
    `backend/tests/integration/test_factory_tick.py` (extend: probe gate)
- Do NOT touch: the proxy provider (139), the buy/allocate flow (140), API/UI/compose (142).
- Blast radius: promotion gate logic only; new health package. NO schema, NO API, NO migration.

## Acceptance Criteria
- [ ] Given a probation row past its gate and a `FakeHealthProbe` returning ok, When promote
      runs, Then the account is promoted (source=auto, proxy carried) — unchanged happy path.
- [ ] Given the probe returns NOT ok, When promote runs, Then the row → `failed`
      (last_error set), it is NOT promoted, and its proxy is released (140 path).
- [ ] Given telegram creds + a real provider + a probe channel, When promotion evaluates an
      account, Then `TelethonHealthProbe` connects the session OVER the account's proxy and
      reads ≥1 message from the public channel before promoting (real read, not a stub).
- [ ] Given the probe channel is unset, When promotion evaluates, Then the probe is a
      deterministic pass (no network) so misconfig can't blackhole the pool.
- [ ] The session string + proxy URI are never logged by the probe. `make ci-fast` green; no
      network in CI; mypy strict (no `Any`/`type: ignore`).

## Plan
1. `factory/health/base.py` — `@dataclass(frozen=True) HealthResult(ok: bool, reason: str|None)`;
   `@runtime_checkable HealthProbe` Protocol: `async check(*, session_string: str, proxy: str|None)
   -> HealthResult`.
2. `factory/health/fake.py` — `FakeHealthProbe(ok: bool = True)` deterministic.
3. `factory/health/telethon.py` — `TelethonHealthProbe(api_id, api_hash, channel, read_limit)`:
   lazy telethon import; build client with `parse_socks5_proxy(proxy)` when proxy set; connect →
   `get_entity(channel)` → read ≥1 message (`get_messages(limit=read_limit)`); ok iff a message
   is read; always disconnect; map errors → `HealthResult(ok=False, reason=<class>)` (no secret).
4. `factory/health/factory.py` — `get_health_probe(settings)`: real iff creds+provider+channel,
   else `FakeHealthProbe()`.
5. `factory/tasks.py` — `_health_check_ok(record, probe)` runs `probe.check(session, proxy)` via
   `asyncio.run`; wire `get_health_probe(settings)` into `_promote_phase`; on not-ok → existing
   `failed` transition + release the proxy (call the 140 release helper).
6. `constants.py` + `config.py` — `account_factory_health_probe_channel: str = ""`,
   `FACTORY_HEALTH_READ_LIMIT: Final = 1`, default channel const (used only if channel unset?—no:
   default empty → skip; a named public default is documented but opt-in).
7. Tests — unit probe (fake ok/fail; telethon mapped via injected fake client); integration
   promote gated by probe (ok→promote, fail→failed+release).

## Invariants
- Probe failure is non-fatal: account → `failed`, proxy released, tick never crashes.
- Real network read ONLY when fully configured; CI/fake path is deterministic + offline.
- Session string + proxy URI never logged. Probe always disconnects its client (no leak).
- Promotion still never co-connects a LIVE pool session (probe uses the factory row's own
  not-yet-live session) — no AuthKeyDuplicated.
- No `Any`/`type: ignore`; named constants.

## Edge cases
- Probe channel resolves but is empty/unreadable → ok=False → failed off-ramp.
- Proxy dead at probe time → connect fails → ok=False (account correctly not promoted).
- Telethon flood/timeout → ok=False with a class-name reason (no secret).
- Probe channel unset → deterministic pass (documented; avoids blackhole).

## Test plan
- unit `test_health_probe.py`: FakeHealthProbe ok/fail; TelethonHealthProbe with an injected
  fake client (read→ok; no-message→fail; raise→fail+reason; asserts disconnect + no secret log).
- integration (`test_factory_tick`): promote with FakeHealthProbe ok → promoted; with fail →
  `failed` + proxy released; provider-unset path unaffected.

## Checkpoints
current_step: 5
baseline_commit: 9251a0471369f3bda60eeda44be544267ee22b33
branch: gsd/epic-proxy-autoprovision
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (session/proxy secrets in probe → YES)
- [ ] 6 ship (confirm plan done → PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### What shipped (TDD, RED→GREEN)
New package `backend/src/factory/health/` (mirrors `registrar/` split):
- `base.py` — `@dataclass(frozen=True) HealthResult(ok, reason)` + `@runtime_checkable
  HealthProbe` Protocol (`async check(*, session_string, proxy) -> HealthResult`). The
  `reason` is documented secret-free (an exception class name only).
- `fake.py` — `FakeHealthProbe(ok=True)`: deterministic, no network, no session/proxy read.
- `telethon.py` — `TelethonHealthProbe(api_id, api_hash, channel, read_limit)`: lazy
  telethon import; `TelegramClient(StringSession(session), api_id, api_hash,
  proxy=parse_socks5_proxy(proxy) if proxy else None)`; `connect → get_entity(channel)
  → get_messages(channel, read_limit)`; `ok` iff ≥1 message; ALWAYS disconnects
  (best-effort, `contextlib.suppress`); maps any exception → `reason=type(exc).__name__`
  (no `str(exc)` → no wrapped-transport secret leak). The `Any` telethon boundary is
  pinned to `_TelethonClientProtocol` (no bare `Any`, no `type: ignore` in prod).
- `factory.py` — `get_health_probe(settings)`: real `TelethonHealthProbe` ONLY when
  `account_factory_provider == smspva` AND telegram creds present AND a non-empty
  `account_factory_health_probe_channel`; else `FakeHealthProbe()` (mirrors `get_registrar`).

Wiring (`factory/tasks.py`):
- `_health_check_ok(record, probe)`: keeps the "must have session+tg_user_id" precondition
  (a None session is unprobeable → not ok, no network), else `asyncio.run(probe.check(...))`
  and returns `.ok`.
- `_promote_phase(redis, session, settings, now)`: builds `probe = get_health_probe(settings)`
  once; on probe NOT ok → existing `failed` transition (`last_error="health probe failed"`)
  + `_release_record_proxy` (reconstructs a minimal `ProxyLease` from
  `record.proxy_lease_id`/`record.proxy` and reuses the 140 `_release_lease` /
  `get_proxy_provider` path — only acts when a lease id + a dynamic provider exist).
- `constants.py`: `FACTORY_HEALTH_READ_LIMIT: Final = 1`,
  `FACTORY_HEALTH_PROBE_CHANNEL_SUGGESTED: Final = "@telegram"` (opt-in doc default).
- `config.py`: `account_factory_health_probe_channel: str = ""` (empty → fake-pass, so a
  misconfig can't blackhole promotion).

### Warming
The authenticated channel read over the sticky proxy IS the warm-up (one gentle action).
A richer multi-day warming scheduler is intentionally OUT of scope — **follow-up**: a
dedicated warming phase (periodic small reads/joins over several days before the probation
gate) would slot in as a separate task; this task keeps the touch surgical.

### Verify (G2)
- `make ci-fast` equivalent GREEN: `ruff format --check` (443 files), `ruff check`
  (all passed), `mypy` (192 src files, 0 issues), `mypy scripts/dump_openapi.py` (0),
  `pytest -m 'not integration'` → **1410 passed**. New unit `test_health_probe.py` → 12 passed
  (Fake ok/fail; Telethon read≥1→ok, zero→fail, raise→fail+exc-class reason, disconnect
  always called, session+proxy ABSENT from caplog and reason; `get_health_probe` gating).
- Integration `tests/integration/test_factory_tick.py` against a throwaway
  `pgvector/pgvector:pg16` on :55432 → **12 passed** (9 prior + 3 new: probe-ok→promoted,
  probe-fail→`failed`+no pool row, probe-fail on a dynamic-proxy row→`failed`+lease released
  once; provider-unset/static paths unaffected). Container removed after.
- Offline/deterministic: the `fake` provider selects `FakeHealthProbe(ok=True)`; no network
  in CI; the real probe is exercised only at the live gate. Secret-safe: probe never logs or
  echoes the session string / proxy URI (asserted).
- No `Any` / `type: ignore` in prod; the telethon boundary is a structural Protocol.
