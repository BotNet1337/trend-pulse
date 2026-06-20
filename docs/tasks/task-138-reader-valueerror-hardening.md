---
id: TASK-138
title: TG read-path ValueError hardening — one bad ref can't blackhole an account; culprit visible
status: review
owner: backend
created: 2026-06-20
updated: 2026-06-20
baseline_commit: e1d4992
branch: "gsd/phase-138-reader-valueerror-hardening"
tags: [collector, reader, reliability, valueerror, pool-health]
---

# TASK-138 — TG read-path ValueError hardening

> Prod incident (2026-06-20 /admin/pool): `@hart_1337 #0` is `Connected` but
> `last_error_reason="ValueError"` with `read_failure_count=104` — a single ref/message
> deterministically raises `ValueError` on EVERY collect tick. The account is wasted on
> the same bad input ~104× and that channel's ingest is black-holed, while health stays
> green-ish. The exact `ValueError` (message/traceback/offending input) is NOT in the
> health snapshot (`last_error_reason` stores only the exception CLASS name, by design).

## Context
This is **trace-independent defensive hardening** (the prod trace requires host log access
that is owner-gated; this task does NOT need it). Read path:
`collector/telegram/reader.py::_read_one` → `pool.acquire()` → `client.iter_messages(handle, …)`
→ map each message to `RawPost`. A `ValueError` can arise from (a) Telethon entity/peer
resolution of a bad/empty handle, (b) an `iter_messages` arg, or (c) our message→`RawPost`
mapping (a field coerced to int/datetime). The transient catch site (TASK-118) already
records non-permanent errors as read failures + rotates, but it (1) does NOT make the
offending **handle** visible (only the class name), and (2) does NOT stop a deterministically
-failing ref from being retried every tick (104×), so the bad channel keeps wasting the slot.

## Goal
A single bad ref/message must NOT blackhole an account or recur silently 104×:
1. **Make the culprit visible:** when a read raises `ValueError` (or any non-permanent
   read error), log the **channel handle** + the exception class (NO secrets) at the catch
   site, so the owner can see WHICH channel is bad from logs (today only the class is kept).
2. **Stop the deterministic waste:** track per-ref consecutive failures; after a named
   threshold of consecutive `ValueError`/data failures on the SAME ref, **skip that ref for
   a TTL window** (named constant) so it stops being retried every tick — other refs on the
   account keep reading normally. Skip is observable (logged once when tripped).
3. **Honest health:** confirm the account is reflected as `failing` (TASK-118 state) while it
   accumulates read failures, and that skipping a bad ref lets the account recover to
   `healthy` for its remaining refs.

## Scope
- Touch ONLY: `collector/telegram/reader.py` (log handle at the non-permanent catch site;
  per-ref consecutive-failure tracking + TTL skip-set), `collector/constants.py`
  (`READ_REF_FAILURE_SKIP_THRESHOLD`, `READ_REF_SKIP_TTL_SECONDS` — named, no magic literals).
- Do NOT touch: pool rotation/quarantine semantics, schema, API, UI, permanent-auth handling.
- Blast radius: collector read path only (internal). No schema/API change.

## Acceptance Criteria
- [ ] Given a ref whose read raises `ValueError`, When it is caught, Then the log line includes
      the channel handle + class (asserted via a FakeClient that raises ValueError on a handle).
- [ ] Given the SAME ref raises `ValueError` ≥ `READ_REF_FAILURE_SKIP_THRESHOLD` consecutive
      ticks, When the next tick runs, Then that ref is SKIPPED (not read) for `READ_REF_SKIP_TTL_SECONDS`
      and a single skip log is emitted; OTHER refs on the account still read.
- [ ] Given a ref recovers (no longer raises), When read again after the TTL, Then it is read
      normally and its failure counter resets.
- [ ] Existing rotation/quarantine/flood tests stay green (no regression); a permanent-auth
      error still quarantines as before (unchanged).
- [ ] `make ci-fast` green.

## Invariants
- One bad ref never blocks an account's other refs; permanent-auth handling unchanged.
- No secret in logs (handle is non-secret; never the session/proxy).
- Deterministic skip (named TTL + threshold, no magic literals, no randomness).

## Edge cases
- All refs on an account bad → account honestly `failing` (no crash; behaves like today minus the waste).
- A ref that raises then recovers within TTL → still skipped until TTL elapses (acceptable; bounded).

## Test plan
- unit (FakeClient in `tests/unit/collector/conftest.py`): handle logged on ValueError; ref skipped
  after threshold; other refs unaffected; recovery resets; permanent-auth still quarantines.

## Checkpoints
current_step: 6
baseline_commit: e1d4992
branch: "gsd/phase-138-reader-valueerror-hardening"
lock: "executor-run-138-opus"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — ValueError hardening + no rotation/quarantine regression)
- [x] 5 review (auto, adversarial — 0 blocking, invariants hold, secret-safe)
- [x] 5.5 security (N/A — collector-internal, non-secret logging + in-memory dicts only)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
**Trace-independent.** Ships the defensive fix that makes the `@hart_1337 #0` symptom self-heal
(bad ref auto-skipped + culprit visible) WITHOUT the prod trace. A precise root-cause of the
exact `ValueError` (which field/handle) is a FOLLOW-UP once the owner pulls the worker log
traceback (`make logs` on host / SSH — agent has no prod access). Takes prod effect only after a
**deploy** (owner-gated, vault-guard).
(initial)

### Execution (2026-06-20)
**Changed files (scope-exact):**
- `backend/src/collector/constants.py` — `READ_REF_FAILURE_SKIP_THRESHOLD=5`, `READ_REF_SKIP_TTL_SECONDS=600` (named `Final`, Why+bound comments).
- `backend/src/collector/telegram/reader.py` — injectable `clock` param (defaults `time.monotonic`); per-ref `_ref_consecutive_failures: dict[str,int]` + `_ref_skip_until: dict[str,float]` keyed by NORMALIZED handle; `_increment_ref_failure` helper (trips skip + single warning at `count == THRESHOLD`); skip-guard at top of `_read_one` (clean no-op `return` before client acquire while within TTL); `logger.warning(handle + exc class)` at BOTH transient catch sites; counter increment in both transient branches AFTER the permanent-auth check; counter+deadline reset on clean read.
- `backend/tests/unit/collector/test_reader_ref_skip.py` — NEW, 6 tests (handle logged on ValueError mid-iter + entity-resolve; ref skipped after threshold; good ref unaffected; recovery after TTL resets; permanent-auth quarantines without touching skip counter).

**Verify (G2):** `make ci-fast` GREEN → `1361 passed, 338 deselected, 23 warnings`; ruff format+check + mypy clean. New behaviours all confirmed (a/b/c/d). Guardrails green: `test_account_pool_rotation.py` + `test_auth_quarantine.py` + `test_reader_read_outcome.py` (39 passed). Secret-safety: logs only `ref.handle` (non-secret) + `type(exc).__name__` + int constants — never session/proxy/tg_user_id.

**Review (opus, adversarial):** PASS, 0 blocking. Invariants held: one-bad-ref-isolated (skip = clean return, not raise), permanent-auth-unchanged (quarantine before increment; FLOOD_WAIT not counted), threshold has no off-by-one (`==` trips, guard prevents blow-past), recovery bounded. 2 LOW cosmetic notes (underscore locals; bounded stale-entry growth ~108 refs/tick) — left as-is to keep diff surgical.

**Security:** N/A — collector-internal, non-secret logging + in-memory dicts only; no auth/input/secret/public-API surface touched.

**Decision:** per-ref skip-state lives in the reader (in-memory, per-worker), NOT the pool — the pool tracks per-ACCOUNT outcome (TASK-118); per-REF skip is a distinct mechanism that must isolate a ref without touching account rotation/quarantine. Named TTL + threshold (no randomness) → deterministic, owner-tunable.

**Prod effect requires a deploy (owner-gated, vault-guard).** The EXACT `ValueError` root-cause (which field/handle) remains a FOLLOW-UP needing the prod worker traceback (`make logs` on host) — this task is the trace-independent defensive fix that makes the symptom self-heal.
