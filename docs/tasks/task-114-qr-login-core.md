---
id: TASK-114
title: Telethon QR-login core service + in-process registry
status: planned
owner: backend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
tags: [telegram, qr-login, collector]
---

# TASK-114 — Telethon QR-login core service

> Drive Telethon `client.qr_login()` to completion and export a NEW StringSession, behind a typed
> service with an in-process registry of in-progress logins.

## Context
Part of EPIC-TG-QR-POOL. Mirrors `collector/telegram/client.py` (lazy telethon import, typed
Protocol, factory) and `collector/errors.py` (domain errors). The minted session never touches the
live pool (see ADR). Consumed by the API in TASK-116.

## Goal
A `QRLoginService` that: (1) `start()` → creates a fresh Telethon client (empty StringSession +
`telegram_api_id`/`telegram_api_hash`), connects, calls `qr_login()`, stores the live login keyed by
an opaque token, and returns `(token, qr_url, expires_at)`; (2) `poll(token)` → reports
`pending | success(session_string) | expired | password_needed | error(reason)`; (3) a TTL reaper /
`cancel(token)` disconnects and drops stale clients. No telethon at import time.

## Discussion
- Q: Where does in-progress state live? → A: in-process module-level registry. Decision: API is a
  single uvicorn worker (no `--workers`), and a live `QRLogin` can't be serialized to Redis. Recorded
  as an epic invariant.
- Q: 2FA accounts? → A: when Telethon raises `SessionPasswordNeededError`, poll returns
  `password_needed` (not supported in QR-only MVP) with a clear reason — do NOT crash.
- Q: timeout? → A: `qr_login_timeout_seconds` pydantic-setting, default 300s, named constant.
- Q: who runs the asyncio? → A: FastAPI endpoints are async; the service is fully async and runs on
  the API event loop. No Celery involvement.

## Scope
- Touch ONLY:
  - NEW `backend/src/collector/telegram/qr_login.py` (service + registry + typed result types)
  - `backend/src/collector/errors.py` (add `QRLoginError` + subclasses)
  - `backend/src/collector/constants.py` (QR timeout / reap interval named constants, seconds)
  - `backend/src/config.py` (`qr_login_timeout_seconds` setting + module-level default const)
  - NEW `backend/tests/unit/test_qr_login.py`
- Do NOT touch: `account_pool.py`, `reader.py`, `registry.py`, the API, the running pool.
- Blast radius: none — new standalone service, not registered as a SourceCollector, not wired into
  collect-tick. Only TASK-116 will import it.

## Acceptance Criteria
- [ ] Given valid api creds, When `start()` is called, Then it returns a non-empty opaque `token`, a
      `qr_url` beginning with `tg://login?token=`, and `expires_at` ≈ now + timeout.
- [ ] Given a started login, When the underlying `QRLogin.wait()` resolves authorized, Then
      `poll(token)` returns `success` with a non-empty `session_string` (StringSession.save of the
      authorized client) and the client is disconnected + evicted from the registry.
- [ ] Given a started login that is not yet scanned, When `poll(token)` is called, Then it returns
      `pending` with `expires_at`.
- [ ] Given the wait raised `SessionPasswordNeededError`, When polled, Then status is
      `password_needed` with a human reason; given any other telethon error, status is `error` with
      the class name as reason (NEVER the session string / api_hash).
- [ ] Given a token past its expiry (or unknown), When polled, Then status is `expired` and any live
      client is disconnected.
- [ ] No telethon import at module import time (importing `qr_login` in a pure-unit context with
      telethon absent must not fail).

## Plan
1. `config.py` — add module-level `_DEFAULT_QR_LOGIN_TIMEOUT_SECONDS = 300` and Settings field
   `qr_login_timeout_seconds: int = _DEFAULT_QR_LOGIN_TIMEOUT_SECONDS` next to the telegram fields.
2. `collector/constants.py` — add `QR_LOGIN_REAP_INTERVAL_SECONDS` (and any other named seconds).
3. `collector/errors.py` — add `QRLoginError(CollectorError)` + `QRLoginNotConfiguredError`,
   `QRLoginExpiredError`, `QRLoginUnknownTokenError` (raise vs. status as fits the API contract;
   prefer returning a status enum from the service, raise only for misconfig/unknown-token).
4. `collector/telegram/qr_login.py` —
   - Typed result: a frozen dataclass / enum `QRLoginStatus` (`PENDING/SUCCESS/EXPIRED/PASSWORD_NEEDED/ERROR`)
     and `QRLoginPoll` (status, session_string|None, reason|None, expires_at).
   - `QRLoginService` holding `{token: _PendingLogin}` where `_PendingLogin` keeps the live client,
     the `QRLogin`, and `expires_at` (monotonic deadline + wall expires_at for the API).
   - Lazy telethon import inside methods (`TelegramClient`, `StringSession`,
     `errors.SessionPasswordNeededError`).
   - Injectable client factory + clock for tests (mirror `account_pool`'s `_now` pattern); a default
     factory builds a real Telethon client with an EMPTY `StringSession`.
   - `start()`, `poll()`, `cancel()`, and `_reap_expired()`; token via `secrets.token_urlsafe`.
5. `tests/unit/test_qr_login.py` — fake client/QRLogin (no network): cover all ACs incl. expiry,
   password_needed, error reason redaction, lazy-import.

## Invariants
- Session strings / api_hash NEVER appear in logs or error reasons.
- Service is import-clean without telethon (lazy import only).
- No mutation of any existing pool/session; `start` always creates a brand-new empty session.

## Edge cases
- Unknown/expired token → `expired` (poll) — never KeyError to the caller.
- `start()` with missing api creds → `QRLoginNotConfiguredError` (caught by API → 503/clear msg).
- Reaper disconnects clients best-effort (log, never raise) — mirror `AccountPool.aclose`.

## Test plan
- unit: `tests/unit/test_qr_login.py` — fake QRLogin (`wait()` returns/raises), fake client; assert
  status transitions, redaction, expiry reaping, lazy import. Target full coverage of the new module.

## Checkpoints
current_step: 6
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: "feat/tg-qr-login"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — 1089 tests + lint + mypy strict green)
- [x] 5 review (code-reviewer opus: 1 HIGH fixed)
- [x] 5.5 security (security-reviewer opus: MEDIUM cap + LOW repr/socket fixed)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

### Step 3 — do (TDD, RED→GREEN), 2026-06-16

**Files changed (exactly the declared scope):**
- NEW `backend/src/collector/telegram/qr_login.py` — service + registry + typed result types.
- NEW `backend/tests/unit/test_qr_login.py` — 15 tests covering every AC (no network, fake client/QRLogin).
- `backend/src/collector/errors.py` — `QRLoginError(CollectorError)` + `QRLoginNotConfiguredError`.
- `backend/src/collector/constants.py` — `QR_LOGIN_REAP_INTERVAL_SECONDS = 60`.
- `backend/src/config.py` — `_DEFAULT_QR_LOGIN_TIMEOUT_SECONDS = 300` + `Settings.qr_login_timeout_seconds`.

**Public API (what TASK-116 will call):**
- `QRLoginService.from_settings_values(*, api_id, api_hash, timeout_seconds, now=time) -> QRLoginService`
  — production constructor; telethon `SessionPasswordNeededError` imported lazily here.
- `await svc.start() -> QRLoginStarted(token, qr_url, expires_at)` — builds a FRESH client over an
  EMPTY StringSession, connects, drives `qr_login()`, registers under an opaque
  `secrets.token_urlsafe(32)` token. Raises `QRLoginNotConfiguredError` iff creds missing (only raise path).
- `await svc.poll(token) -> QRLoginPoll(status, expires_at, session_string|None, reason|None)` —
  `QRLoginStatus.{PENDING,SUCCESS,EXPIRED,PASSWORD_NEEDED,ERROR}`; unknown/expired token → EXPIRED
  (never KeyError); on SUCCESS the NEW session string is returned and the client disconnected+evicted.
- `await svc.cancel(token) -> None` (no-op if unknown); `await svc.reap_expired() -> int` (best-effort
  janitor for `QR_LOGIN_REAP_INTERVAL_SECONDS` sweeps).

**Key decisions:**
- In-process registry `{token: _PendingLogin}` (epic invariant: single uvicorn worker, live QRLogin
  not Redis-serializable).
- `wait()` is driven on a background `asyncio` task at `start()`; `poll()` is non-blocking
  (`await asyncio.sleep(0)` then read task state) so a real long-blocking scan never parks the endpoint.
- Lazy telethon import inside `from_settings_values`/factory only — module imports clean with telethon
  absent (proven by a test that blocks `import telethon` and re-imports the module).
- Redaction: an `ERROR` reason is the exception CLASS NAME (`type(e).__name__`), never the message;
  session string / api_hash never logged or returned in a reason.
- No `# type: ignore` / no `Any`: the untyped telethon client is pinned to `_RawTelethonClient`
  Protocol via a single `cast` at the factory boundary (mirrors `build_telethon_client`).

**Verification (G2):** `make fmt` clean; `make lint` → All checks passed; `make typecheck` → mypy strict
Success (186 files); `make test` → 1087 passed (15 new), 279 deselected.

### Step 5/5.5 — debug/fix (review + security findings), 2026-06-16

Review + security stages found 5 issues in commit `fe92187`; fixed minimally (no scope creep).

1. **[HIGH] Secret-redaction bypass via undrained task exception (GC leak).** `_evict` dropped a
   finished-with-exception `wait_task` WITHOUT retrieving its exception. CPython then logs
   `Task exception was never retrieved` with the FULL exception (message may echo the session
   string / api_hash) at GC time — defeating the class-name-only redaction in `_resolve_error`.
   FIX: new `_drain_wait_task` helper called from `_evict` (so EVERY eviction path — poll-success,
   poll-expiry, `_resolve_error`, `cancel`, `reap_expired` — is covered): if the task is `done()`
   and not cancelled, `_ = task.exception()` (retrieve-and-discard); else `task.cancel()`. New
   `caplog` test `test_reaping_unpolled_failed_login_does_not_leak_secret_to_logs` — proven by a
   negative control: against the old no-drain code the test FAILS with the exact
   `Task exception was never retrieved … SECRET-SESSION-STRING … api_hash=topsecret` log.
2. **[MEDIUM] Unbounded registry DoS.** Added `MAX_CONCURRENT_QR_LOGINS = 20`
   (`collector/constants.py`) + `QRLoginCapacityError(QRLoginError)` (`collector/errors.py`).
   `start()` now reaps expired logins first when at the cap and raises `QRLoginCapacityError` if
   still saturated by LIVE logins. New test `test_start_raises_capacity_error_when_registry_full`
   (fill→raise; after reap→succeeds).
3. **[LOW] Secret in dataclass repr.** `QRLoginPoll.session_string` → `field(default=None,
   repr=False)` so the minted session never appears in any `repr()` / traceback frame dump;
   equality/access unchanged.
4. **[LOW] Pre-registration socket leak.** `start()` now wraps the post-`connect()` section
   (`qr_login()` + `create_task`) so a failure before registration disconnects the connected
   client best-effort (logged, not swallowed) before re-raising.
5. **[LOW] Idiom + docstring.** `asyncio.ensure_future` → `asyncio.create_task`; module docstring
   tightened to state telethon is never imported at module load (`from_settings_values` imports
   `SessionPasswordNeededError` at construction; the factory imports `TelegramClient`/`StringSession`
   only on first `start()`).

**Re-verification (G2):** `make fmt` clean; `make lint` → All checks passed; `make typecheck` →
mypy Success (186 files); `make test` → 1089 passed (17 in test_qr_login.py, +2 new), 279 deselected.

**Public-API delta for TASK-116:** new raise path `QRLoginCapacityError` from `start()` (map to
429/503). All other signatures unchanged.
