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
current_step: 3
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + lint + typecheck)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (touches secrets/auth — REQUIRED)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
