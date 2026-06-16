# ADR — Dynamic pool session store + safe single-slot QR revive

- Status: accepted
- Date: 2026-06-16
- Epic: EPIC-POOL-HEALTH-REVIVE
- Supersedes (in part): [adr-tg-qr-session-persistence.md](./adr-tg-qr-session-persistence.md)
- Related: [ADR-008 at-rest field encryption](./adr-008-at-rest-field-encryption.md), [TASK-087](../tasks/task-087-tg-authkey-quarantine.md), [TASK-102](../tasks/task-102-persistent-session-quarantine.md), [TASK-107](../tasks/task-107-deploy-vault-guard.md)

## Context

A real prod incident (2026-06-16) exposed two gaps in the technical-account pool.

1. **Dishonest health.** The `/admin/pool` UI showed the pool as `healthy=2 / Connected`
   while ingest had been dead ~16h. Evidence: `collect_tick collected posts=0 refs=108`
   every tick, plus `"Server replied with a wrong session ID" ×207`. That Telethon error is
   the symptom of the SAME session being used concurrently from another place (the
   AuthKeyDuplicated incident class) — but it is **not** classified as a permanent-auth error
   by `auth_errors.is_permanent_auth_error`, so the account is never quarantined. It keeps
   `connecting` successfully (the auth key still exists), so `account_statuses()` reports it
   `healthy`, so the UI says `Connected` — while every read returns 0 posts. Health that only
   tracks *connect + permanent-auth-death* is blind to a *connected-but-not-reading* account.

2. **No revive path.** [adr-tg-qr-session-persistence.md](./adr-tg-qr-session-persistence.md)
   decided a QR-minted session is merely *returned to the admin to paste into the vault and
   redeploy*; the running pool is never hot-mutated. That is operationally heavy and does not
   match the owner's desired UX: *"когда уже есть такой аккаунт или его сессия истекла/кикнута —
   я сканирую QR и эта сессия просто возрождается, тот же аккаунт имеет другой статус"* — i.e.
   scanning a QR for an account already in the pool should **revive that same slot in place**,
   not require a manual vault edit + full redeploy.

The prior ADR rejected hot-swap because "hot-swapping the in-worker pool requires cross-process
signalling + rebuilding clients, which reconnects sessions — exactly the manoeuvre that triggered
the AuthKeyDuplicated incident." That objection is real but is about the *unbounded* hot-swap
(rebuild the whole pool, reconnect every session). It does **not** apply to a *single-slot,
disconnect-then-connect* revive, which is what this ADR makes safe.

## Decision

### 1. A DB-backed dynamic pool session store (encrypted at rest)

Add a `pool_sessions` table. Each row is one technical account, keyed by its **Telegram account
identity** (`tg_user_id`, obtained from `client.get_me()` after a successful QR login). The
session string is stored in an `EncryptedString` column (ADR-008 Fernet TypeDecorator) — never
plaintext, never in Redis, never in an API response except the existing one-shot superuser
copy-field. A non-secret `session_fingerprint` (sha256[:16], TASK-102) and a non-secret display
label (masked id / `@username`) are stored alongside for quarantine-clearing and UI identity.

Upsert semantics keyed by `tg_user_id`:
- **revive** — a row already exists for this `tg_user_id` → replace its session string (+ fingerprint),
  clear `revoked_at`, and clear the persisted quarantine fingerprint (TASK-102) for the OLD
  fingerprint so the worker does not reload the slot as dead.
- **add** — no row for this `tg_user_id` → insert (respecting `POOL_MAX`; reject over cap).

### 2. The worker pool loads from (DB store ∪ env `TELEGRAM_POOL_SESSIONS`)

`from_sessions` is extended so the worker builds its pool from the union of env sessions and the
DB store. Env stays the bootstrap floor (works with the DB empty); the DB store is the dynamic
overlay. De-dup by fingerprint so an account present in both is one slot.

### 3. Safe **single-slot** live revive (disconnect-then-connect)

When the worker observes (via a Redis revive-signal written by the API on a successful QR
revive) that a slot's session changed, it performs, on the next tick, for **that one slot only**:

1. `await old_client.disconnect()` — the dead/old session's client is fully torn down FIRST.
2. build a fresh client over the NEW session string and connect it.
3. swap the single `_Account.client` in place; clear that account's `quarantined`/cooldown/
   `last_error_reason`; the slot's `tg_user_id`/fingerprint are updated.

The invariant that makes this safe: **a session is never connected by two clients at once.** The
old client is disconnected before the new client connects, and only the one affected slot is
touched — the rest of the pool is never reconnected. This is categorically different from the
whole-pool rebuild the prior ADR feared.

## Rationale

- **Single-slot disconnect-then-connect cannot cause AuthKeyDuplicated**: the AuthKey conflict
  arises from *two live clients on one session*. We guarantee one-at-a-time per slot and never
  reconnect untouched slots, so no other session is disturbed.
- **Identity-keyed upsert delivers the owner's exact UX**: re-scanning revives the same row
  (status flips dead/expired → connected) instead of creating a duplicate or rejecting.
- **Encrypted-at-rest reuses ADR-008** (already audited Fernet TypeDecorator + lazy key) — no new
  crypto, no plaintext secret store, zero secret in Redis/logs/API.
- **Env path stays the floor** so a DB outage degrades to the current static behaviour (fail-open).

## Consequences

- New DB table + migration (`pool_sessions`); new revive-signal Redis key (non-secret: fingerprint
  + slot only). The QR-login flow now calls `get_me()` and persists the minted session.
- The API invariant from EPIC-TG-QR-POOL still holds: the QR registry is in-process (single uvicorn
  worker). The revive is communicated to the worker via the DB store + a Redis signal, never by the
  API mutating the live pool directly.
- **`--workers>1`** on the API is still forbidden without moving the QR registry off-process.
- Manual vault editing is no longer required to grow/revive the pool; the env vault remains the
  bootstrap source of truth and a disaster-recovery floor.
- A future hardening could add a generation counter / lease so a revive and a concurrent
  quarantine cannot race on the same slot (noted as an edge case in TASK-119).

## What this does NOT change

- Rotation / cooldown / FLOOD_WAIT / permanent-quarantine semantics (TASK-087/102) are unchanged;
  the "failing" state (TASK-118) is additive and never gates `acquire()`.
- We still NEVER reuse a pool session for backfill, and NEVER deploy from a worktree with an
  uncommitted vault (TASK-107).
