# TASK-114 — QR-login core service: notes / public API

Branch `feat/tg-qr-login`. Module `backend/src/collector/telegram/qr_login.py`.
Standalone service (not wired into collect-tick). Consumed by TASK-116 (API).

## Public API (what TASK-116 calls)

- `QRLoginService.from_settings_values(*, api_id, api_hash, timeout_seconds, now=time) -> QRLoginService`
  — production constructor; telethon `SessionPasswordNeededError` imported lazily here.
- `await svc.start() -> QRLoginStarted(token, qr_url, expires_at)` — fresh client over an EMPTY
  StringSession, connect, `qr_login()`, register under `secrets.token_urlsafe(32)`.
  Raise paths:
    - `QRLoginNotConfiguredError` — api creds missing (map to 503).
    - `QRLoginCapacityError` — registry at `MAX_CONCURRENT_QR_LOGINS` (20) even after reaping
      expired logins (map to 429/503; retry once an in-flight login finishes or expires). **NEW
      in debug/fix pass.**
- `await svc.poll(token) -> QRLoginPoll(status, expires_at, session_string|None, reason|None)` —
  `QRLoginStatus.{PENDING,SUCCESS,EXPIRED,PASSWORD_NEEDED,ERROR}`; unknown/expired → EXPIRED
  (never KeyError). On SUCCESS the NEW session string is returned + client disconnected/evicted.
  `session_string` field is `repr=False` (secret kept out of reprs/tracebacks).
- `await svc.cancel(token) -> None` (no-op if unknown); `await svc.reap_expired() -> int`
  (best-effort janitor for `QR_LOGIN_REAP_INTERVAL_SECONDS` sweeps).

## Security invariants (hardened in debug/fix pass)

- ERROR `reason` is the exception CLASS NAME only — never the message (may echo session/api_hash).
- EVERY eviction path drains the background `wait()` task (`_drain_wait_task`): a
  finished-with-exception task's exception is retrieved-and-discarded so CPython never logs
  "Task exception was never retrieved" with the raw (secret-bearing) exception at GC time.
- `session_string` is `field(repr=False)`; never logged.
- DoS belt: `MAX_CONCURRENT_QR_LOGINS = 20` bounds the in-process registry.
- Pre-registration socket leak closed: a failure after `connect()` but before registration
  disconnects the client best-effort before re-raising.

## Constants (collector/constants.py)
- `QR_LOGIN_REAP_INTERVAL_SECONDS = 60`
- `MAX_CONCURRENT_QR_LOGINS = 20` (NEW)
- timeout: `config.qr_login_timeout_seconds` (default 300).
