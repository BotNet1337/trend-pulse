# TASK-119 notes — dynamic encrypted pool session store + safe single-slot revive

Branch `feat/pool-health-revive`, baseline `98bd84c` (HEAD includes TASK-118).
Part of EPIC-POOL-HEALTH-REVIVE. This is the SECURITY-CRITICAL core; TASK-120 (API/FE) builds on it.

## DB table `pool_sessions` (model + migration 0024 ← 0023)
`backend/src/storage/models/pool_sessions.py` → `PoolSession`:
- `id` PK, `tg_user_id BIGINT UNIQUE` (the account identity from `get_me()` — the upsert key),
- `session_string EncryptedString(1024)` — Fernet-encrypted AT REST (ADR-008 TypeDecorator). The DB
  column holds a `gAA…` token; the ORM auto-decrypts on read. NEVER plaintext, NEVER logged, NEVER Redis.
- `session_fingerprint VARCHAR(16)` — non-secret sha256[:16] (TASK-102), the persistent-quarantine key,
- `display_label VARCHAR(64)` — non-secret masked id / `@username` (for the UI),
- `created_at` / `updated_at` (onupdate) / `revoked_at` (NULL = active, soft-revoke).
Unique constraint `uq_pool_sessions_tg_user_id`; indexes on `tg_user_id` + `revoked_at`.
Migration round-trip (up/down/re-up) verified on `pgvector/pgvector:pg16`.

## Store API — `backend/src/storage/pool_session_store.py` (all take a caller-owned `Session`)
- `upsert_revive_or_add(session, *, tg_user_id, session_string, display_label, pool_max,
   env_floor_size=0) -> UpsertResult`
  - row exists for `tg_user_id` → **REVIVE**: replace `session_string`+`fingerprint`, refresh
    `display_label`/`updated_at`, clear `revoked_at`. Returns `previous_fingerprint` (the OLD fp).
  - no row → **ADD**: insert, but only if active-row count < the EFFECTIVE cap
    `max(0, pool_max − env_floor_size)`, else `PoolCapacityExceededError` (`collector/errors.py`).
    A revive NEVER trips the cap.
  - **`env_floor_size` (review HIGH fix)**: the count of distinct env `TELEGRAM_POOL_SESSIONS` slots the
    worker ALSO unions into the pool. The ADD cap reserves room for them so active DB rows + env can
    never exceed `POOL_MAX` → `from_sessions` never raises on size. Default 0 = bare DB-only cap.
    **TASK-120 MUST pass `env_floor_size=len(set(telegram_pool_sessions(settings)))`** on the
    revive/add endpoint.
  - `UpsertResult{outcome: ReviveOutcome.REVIVE|ADD, tg_user_id, fingerprint, display_label,
    previous_fingerprint}` — carries NO secret (safe to log/return to the API).
- `active_sessions(session) -> list[StoredSession]` — active (`revoked_at IS NULL`) rows, ordered by
  `tg_user_id`. `StoredSession{tg_user_id, fingerprint, display_label, session_string(repr=False)}`
  carries the DECRYPTED secret — ONLY the worker loader consumes this.
- `find_active_by_tg_user_id(session, tg_user_id) -> StoredSession | None` — the worker revive lookup.
- `revoke(session, *, tg_user_id) -> bool` — idempotent soft-revoke (kept for audit).
- `clear_quarantine_for(redis, fingerprint)` — SREM the OLD fp from `pool:quarantined_fingerprints`
  (best-effort, fail-open, malformed-fp guarded). Call on REVIVE with `UpsertResult.previous_fingerprint`.

## Identity (QR login) — `collector/telegram/qr_login.py`
- `get_me()` added to `QRLoginClientProtocol` + `_RawTelethonClient` + `_RealClientAdapter`
  (returns `QRLoginIdentity{tg_user_id, display_label}`; telethon stays lazy).
- success `poll()` now calls `get_me()` → `QRLoginPoll` gains `tg_user_id` + `display_label`
  (non-secret). If `get_me()` fails → ERROR status (class name only; the session is NOT handed back).
- `display_label` = `@username` or `id:***NNNN` (last 4 digits). `session_string` stays `repr=False`.

## Worker pool loads (DB ∪ env) — `collector/registry.py`
- `_build_telegram_collector` → `_union_pool_sessions(env_sessions, fingerprint)` returns positional
  `(sessions, tg_user_ids)`: DB store rows first (carry their `tg_user_id`), then env sessions
  (`tg_user_id=None`), de-duped by fingerprint (DB wins). FAIL-OPEN: any DB error → env-only (logged).
- **JOINT POOL_MAX cap (review HIGH fix)**: the de-duped union is TRUNCATED to `POOL_MAX`, **DB-first**
  (live identity-keyed slots survive; env-floor overflow dropped, logged) so `from_sessions` can never
  raise `PoolConfigError` on size → ingest never fully stops. This is the worker-side hard guarantee;
  the store's `env_floor_size` ADD cap is the producer-side guarantee (both implemented).
- `AccountPool.from_sessions(... tg_user_ids=, )` is additive; the pool retains the `factory` for revive.

## Safe single-slot revive — `account_pool.py` + `reader.py`
- `AccountPool.find_slot_index(*, tg_user_id, fingerprint) -> int | None` — locate by identity then fp.
- `AccountPool.revive_slot(*, slot_index, tg_user_id, session_string)` — **the safety case**:
  1. `await old_client.disconnect()` FIRST (best-effort; a dead-socket failure does not block),
  2. build a fresh client via the factory + `connect()`,
  3. swap `account.client` in place; reset that slot's `quarantined`/`cooldown_until`/`flood_strikes`/
     read-outcome fields/`last_error_reason`; update `fingerprint`+`tg_user_id`.
  4. **(review MEDIUM fix)** SREM the swapped-out OLD fingerprint from `pool:quarantined_fingerprints`
     (`_clear_persisted_quarantine`, best-effort/fail-open, malformed-fp guarded) — belt-and-suspenders
     so a worker recycle after the revive can't reload the slot as dead even if the producer's
     `clear_quarantine_for` was skipped/failed. (Producer `clear_quarantine_for` is still called by
     TASK-120; this is the worker-side redundant clear.)
  INVARIANT (unit-asserted): a session is NEVER on two clients (old disconnect < new connect); only the
  one slot churns (siblings untouched).
- **Revive applied ONCE per tick (review LOW fix)**: the check moved out of `read()` (which is called
  per ref, ~108×/tick → ~108 GETs) into `TelegramCollector.apply_pending_revive()`, driven ONCE by the
  tick wrapper `collector.tasks._collect_refs` before the per-ref loop (via `runtime_checkable`
  `_SupportsPendingRevive` — generic `SourceCollector` + Twitter/Reddit untouched). `_apply_revive_best_effort`
  reads the non-secret signal, `find_slot_index`, loads the NEW session from the store
  (`find_active_by_tg_user_id` — secret from DB, not Redis), `revive_slot`, clears the signal. Single
  Redis GET per tick; tick-boundary disconnect-before-connect single-slot invariant unchanged. Never
  crashes the tick (mirrors `_emit_health_best_effort`).

## Redis revive-signal (cross-process, NON-SECRET) — `collector/constants.py`
- Key `POOL_REVIVE_SIGNAL_REDIS_KEY = "pool:revive:signal"`, TTL `POOL_REVIVE_SIGNAL_TTL_SECONDS = 600`.
- Payload = small JSON `{"tg_user_id": int, "fingerprint": "<sha256[:16]>"}` — the affected slot ONLY,
  NEVER the session string. The worker parser validates the fp shape (defense-in-depth).

## How TASK-120 (revive API + UI) consumes this
1. The QR-poll success result already carries `tg_user_id` + `display_label` (TASK-119). On the
   revive/add endpoint: open a `get_session()` UoW, call
   `upsert_revive_or_add(db, tg_user_id=poll.tg_user_id, session_string=poll.session_string,
   display_label=poll.display_label, pool_max=POOL_MAX)`. Map `PoolCapacityExceededError` → 4xx.
2. On a **REVIVE** outcome, also `clear_quarantine_for(redis, result.previous_fingerprint)` AND write the
   revive-signal `redis.set(POOL_REVIVE_SIGNAL_REDIS_KEY, json.dumps({"tg_user_id": ...,
   "fingerprint": result.fingerprint}), ex=POOL_REVIVE_SIGNAL_TTL_SECONDS)` so the worker swaps the live
   slot on its next tick. On an **ADD**, the account appears on the next full pool build (no live signal
   needed — there is no existing slot to swap).
3. NEVER put the session string in the API response (except the existing one-shot superuser copy-field)
   or in Redis. The store row is the source of truth; the worker reads the secret from the DB only.
4. For a pool-admin list/revoke UI: read `active_sessions(db)` (use the non-secret fields — NEVER render
   `session_string`); `revoke(db, tg_user_id=...)` soft-revokes (the worker drops it on the next build).
   The TASK-118 `failing`/`ingest_contradiction` badges are the UI the revive flow flips to `healthy`.

## Gate evidence
`make fmt/lint/typecheck` green (mypy strict, 189 files, no Any/ignore). `make test` = 1144 passed.
Integration on throwaway pgvector:pg16 (port 55432): migrations 4, pool_session_store 3,
at_rest_encryption+repositories 12 — all passed; container torn down. New tests: store(11), revive(7),
reader-revive(7), qr identity(+3), migration round-trip(+1), models expected-set(+1).
