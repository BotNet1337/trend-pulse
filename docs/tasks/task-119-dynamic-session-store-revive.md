---
id: TASK-119
title: Dynamic pool session store (encrypted) + SAFE single-slot QR revive
status: planned
owner: backend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: ""
tags: [telegram, pool, qr-login, session-store, encryption, revive, migration]
---

# TASK-119 — Dynamic pool session store + safe single-slot live revive

> Persist QR-minted sessions in a DB table (session string ENCRYPTED at rest, keyed by the Telegram
> account identity from `get_me()`). The worker pool loads from (DB store ∪ env). A revive replaces
> the session for an EXISTING account slot LIVE by disconnecting the old client BEFORE connecting the
> new session — never double-connecting a session, touching only that one slot. Clears the persisted
> quarantine for the revived account.

## Context
Part of EPIC-POOL-HEALTH-REVIVE; writes the new ADR
[adr-dynamic-pool-session-store.md](../architecture/adr-dynamic-pool-session-store.md) (supersedes the
"no hot-swap, manual vault paste" decision). Today the pool is built ONCE from env
`TELEGRAM_POOL_SESSIONS` (`collector/registry.py::_build_telegram_collector` →
`AccountPool.from_sessions`, `config.telegram_pool_sessions`). QR login
(`collector/telegram/qr_login.py`) mints a NEW StringSession in the API process and currently just
RETURNS it. Permanent quarantine is keyed by `session_fingerprint=sha256(session)[:16]` persisted to
Redis `pool:quarantined_fingerprints` (TASK-102), loaded in `from_sessions` and written by
`quarantine_current`. The encrypted-column mechanism is `storage/encryption.py::EncryptedString`
(Fernet TypeDecorator, ADR-008) — reused here for the session column. Models live in
`backend/src/storage/models/`; migrations in `backend/migrations/versions/` (latest 0023).

## Goal
1. **DB table `pool_sessions`** (model + Alembic migration 0024 ← 0023):
   - `tg_user_id: BigInteger` UNIQUE (the Telegram account identity — the upsert key).
   - `session_string: EncryptedString(...)` — the StringSession, ENCRYPTED at rest (ADR-008). NEVER
     plaintext, NEVER logged.
   - `session_fingerprint: String(16)` — non-secret sha256[:16] (TASK-102) for quarantine clearing.
   - `display_label: String(...)` — non-secret masked id / `@username` from `get_me()` for the UI.
   - `revoked_at: DateTime | None` (soft-revoke; NULL = active), `created_at`, `updated_at`.
2. **A typed `pool_session_store`** service (storage layer) with `upsert_revive_or_add(tg_user_id,
   session_string, fingerprint, label) -> ReviveOutcome` (revive vs add, respecting `POOL_MAX`),
   `active_sessions() -> list[StoredSession]`, `clear_quarantine_for(fingerprint)` coordination.
   Pydantic/dataclass DTOs at the boundary; never returns the raw secret outside the store except to
   the worker loader.
3. **QR login learns identity**: after a successful `qr_login()`/`wait()`, call `client.get_me()` to
   get the tg user id + username; thread `(tg_user_id, display_label)` into the success result so the
   API (TASK-120) can persist + decide revive/add. `get_me()` is added to the client protocol; telethon
   stays lazily imported; the masked label is non-secret.
4. **Worker pool loads (DB ∪ env)**: `_build_telegram_collector` builds the session list from
   `telegram_pool_sessions(settings)` UNION `pool_session_store.active_sessions()`, de-duped by
   fingerprint. Env stays the bootstrap floor (works with the DB empty); fail-open if the DB read
   fails (log + env-only).
5. **SAFE single-slot live revive**: on a revive the API writes a NON-SECRET revive-signal to Redis
   (`pool:revive:signal` — the fingerprint/`tg_user_id` of the affected slot only, never the session).
   The worker, each tick (best-effort, before/after the read cycle), checks the signal and for the ONE
   affected slot: `await old_client.disconnect()` FIRST, then build+connect a fresh client over the new
   session (loaded from the store), swap `_Account.client` in place, clear that account's
   `quarantined`/cooldown/`consecutive_read_failures`/`last_error_reason`, update its
   fingerprint/`tg_user_id`. The new session string is read from the encrypted store inside the worker
   — it never travels through Redis. Only that slot is touched; no other client is reconnected.
6. **Clear persisted quarantine on revive**: remove the OLD fingerprint from
   `pool:quarantined_fingerprints` (and add the new fingerprint is NOT quarantined) so the next pool
   build / load does not re-mark the revived account dead.

## Discussion
- **Q: How does the worker pick up a revive without rebuilding the whole pool (the feared
  AuthKeyDuplicated manoeuvre)?** → A: a SINGLE-SLOT disconnect-then-connect, gated on a Redis
  revive-signal carrying only the non-secret fingerprint. The session string is loaded from the
  encrypted DB store inside the worker (not via Redis). The old client is disconnected before the new
  one connects; no untouched slot is reconnected. This is the crux of the ADR — it is categorically
  safe vs a full rebuild because a session is never live on two clients and only one socket churns.
- **Q: revive vs add key?** → A: `tg_user_id` from `get_me()`. Same account re-scanned → row exists →
  revive (replace session, clear `revoked_at`, clear old quarantine fingerprint). New account → insert
  (reject if active rows + env floor would exceed `POOL_MAX`).
- **Q: secret never in Redis — confirmed.** Redis carries ONLY the revive-signal (fingerprint /
  tg_user_id) and the existing non-secret quarantine fingerprints. The session is in the DB,
  Fernet-encrypted, decrypted only at ORM read inside the worker.
- **Q: race — revive signal arrives while that slot is mid-read / being quarantined?** → A (default):
  apply the revive at a tick boundary (not mid-`iter_messages`); a revive CLEARS quarantine, so a
  revive-then-quarantine ordering self-heals on the next read outcome. **Owner-flag:** a generation
  counter / lease to make revive vs concurrent quarantine strictly ordered is a future hardening
  (noted in the ADR consequences); default is tick-boundary application + clear-on-revive.
- **Q: row retention on revoke?** → A (default): soft `revoked_at` (kept for audit, matches
  `api_keys`/`subscriptions` patterns); active loader filters `revoked_at IS NULL`. **Owner-flag** if
  they want hard delete.
- **Q: `POOL_MIN`/`POOL_MAX` interplay?** → A: env floor + active DB rows together must stay within
  `POOL_MIN..POOL_MAX`; `from_sessions` already enforces the bound — pass the unioned list to it.
- **Q: dev/test without telethon or DB?** → A: store is plain SQLAlchemy (works on the test sqlite/pg
  like other models); `get_me()` is behind the client protocol so tests fake it; the revive swap is
  unit-tested with a fake client factory + injected clock (mirror `AccountPool._now`).

## Scope
- Touch ONLY:
  - `backend/src/storage/models/pool_sessions.py` (NEW) — the ORM model (mirror `api_keys.py` style;
    `EncryptedString` for the secret column; named-constant widths).
  - `backend/src/storage/models/__init__.py` — register the new model.
  - `backend/migrations/versions/0024_pool_sessions.py` (NEW) — create table + indexes (mirror a
    recent migration, e.g. 0023 / 0019 for the EncryptedString width).
  - `backend/src/storage/pool_session_store.py` (NEW) — typed store service (upsert/active/clear).
  - `backend/src/collector/telegram/qr_login.py` — add `get_me()` to the client protocol/adapter;
    return identity in the success poll result (non-secret label only in logs).
  - `backend/src/collector/telegram/account_pool.py` — add a SAFE single-slot `revive_slot(...)`
    (disconnect-old → connect-new → swap one client → reset that account's state); needs a client
    factory available to the pool (thread it through `from_sessions`/store on the pool).
  - `backend/src/collector/telegram/reader.py` — at a tick boundary, check the Redis revive-signal and
    call `pool.revive_slot(...)` best-effort (never crash the tick).
  - `backend/src/collector/registry.py` — `_build_telegram_collector` unions env + store sessions;
    fail-open on DB error.
  - `backend/src/collector/constants.py` — `POOL_REVIVE_SIGNAL_REDIS_KEY`, its TTL, the
    `pool_sessions` column widths if not in the model.
  - `backend/src/collector/errors.py` — domain error(s) for over-cap add / store failure if needed.
  - tests: new `test_pool_session_store.py`, `test_pool_revive.py`, extend `test_account_pool.py`,
    qr_login identity test, migration round-trip test.
- Do NOT touch: the API routes / FE (TASK-120), rotation/cooldown/quarantine SEMANTICS (revive only
  CLEARS state for one slot), the honesty/failing logic (TASK-118 — consume it, don't change it),
  the env vault, deploy.
- Blast radius: NEW table + migration (forward-only create; downgrade drops it). `from_sessions`
  signature grows (factory/store optional, additive). QR success result gains identity fields
  (additive). The worker now reads the DB at pool build (fail-open). NO change to the API contract
  here (that is TASK-120).

## Acceptance Criteria
- [ ] Given a successful QR login for a tg account NOT in `pool_sessions`, When persisted via the
      store, Then a row is inserted with the session ENCRYPTED at rest (the DB column value is a Fernet
      token, not the plaintext StringSession) and the outcome is `ADD`.
- [ ] Given a successful QR login for a tg account ALREADY in `pool_sessions`, When persisted, Then the
      SAME row's `session_string`/`fingerprint` are replaced, `revoked_at` cleared, the OLD fingerprint
      removed from `pool:quarantined_fingerprints`, and the outcome is `REVIVE` (no duplicate row).
- [ ] Given the worker builds the pool, When the store has active rows, Then the pool sessions are the
      union of env + store (de-duped by fingerprint), within `POOL_MIN..POOL_MAX`; a DB read failure
      degrades to env-only (logged, no crash).
- [ ] Given a revive-signal for slot S with a dead/quarantined client, When the worker applies it,
      Then `old_client.disconnect()` is called BEFORE the new client connects, ONLY slot S's client is
      swapped, slot S's `quarantined`/cooldown/`consecutive_read_failures` are cleared, and NO other
      slot's client is reconnected (assert via the fake clients' connect/disconnect call order).
- [ ] No session string or api_hash is logged or written to Redis at any point (revive-signal carries
      only the non-secret fingerprint/tg_user_id).
- [ ] `make test` (incl. migration round-trip) + ruff + mypy strict green; no `Any` / `# type: ignore`.

## Plan (per-file, ordered)
1. `collector/constants.py` — `POOL_REVIVE_SIGNAL_REDIS_KEY = "pool:revive:signal"`, its TTL, and the
   `pool_sessions` column widths (or keep widths in the model as named constants).
2. `storage/models/pool_sessions.py` — ORM model (mirror `api_keys.py`): `tg_user_id` BigInteger
   unique-indexed, `session_string` `EncryptedString(width)`, `session_fingerprint` String(16),
   `display_label`, `revoked_at`, `created_at`, `updated_at`. Register in `models/__init__.py`.
3. `migrations/versions/0024_pool_sessions.py` — `create_table` + indexes; `downgrade` drops it.
   EncryptedString column is a VARCHAR (size like ADR-008's tokens — generous for a StringSession +
   Fernet overhead).
4. `storage/pool_session_store.py` — typed DTOs (`StoredSession`, `ReviveOutcome` enum); functions
   `upsert_revive_or_add(...)`, `active_sessions()`, `clear_quarantine_for(fingerprint, redis)`. The
   upsert uses `tg_user_id` to decide revive vs add and enforces `POOL_MAX` against active rows.
5. `collector/telegram/qr_login.py` — `get_me()` on the client protocol + `_RealClientAdapter`;
   `poll()` success path reads identity; `QRLoginPoll` gains `tg_user_id`/`display_label` (label is
   non-secret; never log the session). telethon stays lazy.
6. `collector/telegram/account_pool.py` — `revive_slot(*, tg_user_id, session_string, fingerprint)`:
   locate the slot by `tg_user_id`/old fingerprint, `await account.client.disconnect()`, build a new
   client via the pool's factory over the new session, connect, swap `account.client`, reset
   `quarantined=False`/`cooldown_until=0`/`consecutive_read_failures=0`/`last_error_reason=""`/update
   fingerprint+tg_user_id. Single-slot only; best-effort disconnect (log, never re-raise). Thread a
   factory + (optional) store into `from_sessions` so the pool can build the new client.
7. `collector/telegram/reader.py` — at a tick boundary in `read()` (not mid-channel), best-effort:
   read `POOL_REVIVE_SIGNAL_REDIS_KEY`; if a signal targets a slot, load the new session from the
   store and call `pool.revive_slot(...)`; clear the signal. Never crash the tick (mirror
   `_emit_health_best_effort`).
8. `collector/registry.py` — `_build_telegram_collector` unions env + `active_sessions()` (fail-open),
   passes the factory/store to `from_sessions`.
9. `collector/errors.py` — add `PoolSessionStoreError` / over-cap error if the existing ones don't fit.
10. Tests (TDD: failing test first) — see Test plan.

## Invariants
- **A session is NEVER live on two clients at once.** Revive disconnects the old client BEFORE
  connecting the new one, and touches exactly one slot.
- The session string is encrypted at rest (Fernet, ADR-008), never logged, never in Redis.
- Rotation / cooldown / permanent-quarantine SEMANTICS unchanged; revive only CLEARS one slot's state.
- Env `TELEGRAM_POOL_SESSIONS` remains a valid bootstrap floor and disaster-recovery path (DB outage →
  env-only pool).
- Self-observation / revive application never crashes the collect-tick (best-effort).

## Edge cases
- Revive-signal for a `tg_user_id` not in the live pool (account added since boot) → load it as a NEW
  slot if under `POOL_MAX`, else log + skip (no crash); default: revive applies to existing slots,
  brand-new accounts appear on the next pool build.
- `get_me()` fails after a successful auth (rare) → surface as an ERROR poll status (class name only,
  no secret); do NOT persist a session we can't identity-key.
- Over `POOL_MAX` on add → reject with a clear domain error (mapped to a 4xx by TASK-120's API).
- DB read failure at pool build → env-only pool (logged, fail-open).
- Old client `disconnect()` raises during revive → log + proceed to connect the new client (the old
  session is dead anyway; the point is to not double-connect, which a failed disconnect on a dead
  socket does not).
- Encryption key rotation → out of scope (ADR-008 covers it); the store reads via the TypeDecorator so
  it inherits the dual-read fallback.

## Test plan
- unit `test_pool_session_store.py`: add inserts encrypted (DB value != plaintext); revive replaces +
  clears `revoked_at` + clears quarantine fingerprint; over-cap add rejects; `active_sessions` filters
  revoked.
- unit `test_pool_revive.py`: `revive_slot` calls `disconnect` on the OLD client before `connect` on
  the NEW (assert call order on fakes); only the targeted slot's client changes; state cleared; other
  slots untouched (no connect/disconnect on them).
- unit qr_login: success result carries `tg_user_id`/`display_label`; the session string never appears
  in any log/repr; `get_me()` failure → ERROR status.
- integration/migration: 0024 round-trip on pgvector:pg16; model CRUD; union loader (env ∪ store).
- reader unit: revive-signal at a tick boundary triggers `revive_slot` best-effort; a store/redis
  error does not crash the tick.

## Checkpoints
current_step: 3
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — full suite + migration round-trip + ruff + mypy strict green)
- [ ] 5 review (code-reviewer)
- [ ] 5.5 security (MANDATORY — encrypted-at-rest secret + revive concurrency; security-reviewer)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details (initial)
This is the riskiest story — the live single-slot swap is the manoeuvre the prior ADR forbade. The
entire safety case rests on TWO guarantees, both unit-asserted: (1) a session is never connected by
two clients — the old client is `disconnect()`ed BEFORE the new client `connect()`s, proven by the
fake-client call-order test; (2) only the one affected slot churns — every other `_Account.client`
is untouched, proven by asserting no connect/disconnect on sibling fakes. The secret never leaves the
DB except into the worker's own process memory at ORM-read time; Redis only ever carries the
non-secret revive-signal (fingerprint/tg_user_id), exactly like the existing non-secret quarantine
fingerprints (TASK-102). Security checkpoint is MANDATORY here (encrypted secret column + a new
runtime mutation path).
