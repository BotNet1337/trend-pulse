---
id: TASK-102
title: Persist TG session quarantine across worker restarts (Redis, by fingerprint)
status: in-progress
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "d2fad96"
branch: "task/102-persistent-session-quarantine"
tags: [reliability, collector, telegram, quarantine, redis, restart]
---

# TASK-102 — Persistent session quarantine

> Track A (reliability) #6 (audit FM-2). The dead-session quarantine (`_Account.quarantined`,
> TASK-087) is IN-MEMORY only. A worker restart (crash, deploy, or — now more frequent —
> `worker_max_tasks_per_child` recycling from TASK-099) rebuilds the pool with every session
> un-quarantined, so a known-dead session is re-acquired and re-tried, and the pool reports an
> inaccurate `healthy` count at boot (which feeds the pool-health / degraded alerts). Persist the
> quarantine in Redis keyed by a NON-SECRET session fingerprint so it survives restarts.

## Context
The `auth_dead:{idx}` ops alert is already throttled across restarts by `notify_ops`'s Redis key,
so the residual FM-2 cost is (a) re-trying a dead session each restart and (b) a wrong boot-time
`healthy` count. Persistence fixes both. The session STRING is never stored (overview §7); the
fingerprint is `sha256(session)[:16]` — one-way, non-secret, stable per session, and CHANGES when
the owner re-mints (so a re-minted session is automatically NOT loaded as quarantined → auto-recovery).

## Discussion
<!-- durable record -->
- Q: Fingerprint vs pool index as the persistent key? → A: **fingerprint** (`sha256(session)[:16]`).
  Index is unstable: re-minting the dead slot would wrongly load the NEW session as quarantined.
  A session-hash changes on re-mint → recovery is automatic; stale hashes for replaced sessions are
  harmless and TTL-expire.
- Q: Storage? → A: a Redis SET `pool:quarantined_fingerprints`, refreshed with a 30-day TTL on each
  write (bounded — ≤ pool size entries; TTL clears truly-abandoned sets; expiry just means a still-dead
  session is retried once more after >30d idle — acceptable).
- Q: Redis down at pool construction? → A: **fail-open** — log a warning and build the pool with no
  persisted quarantine (pool init must never crash on a Redis blip). Persisting a quarantine is also
  best-effort (in-memory quarantine still holds for the process even if the SADD fails).
- Q: Secret-safety? → A: a truncated sha256 is not a secret and cannot recover the session; the
  "never store/log the session string" invariant is preserved (only the hash is stored).
- Decision (owner-gated): effective on prod after `make deploy`. Batched.

## Scope
- `backend/src/collector/telegram/account_pool.py` — `_Account.session_fingerprint`; `_fingerprint()`;
  optional `_redis` on the pool; `from_sessions(..., redis=None)` computes fingerprints + loads the
  persisted quarantine set (fail-open); `quarantine_current()` persists the fingerprint (best-effort).
- `backend/src/collector/constants.py` — `QUARANTINE_REDIS_KEY`, `QUARANTINE_PERSIST_TTL_SECONDS`.
- `backend/src/collector/registry.py` — thread the existing `get_redis_client()` into `from_sessions`.
- `backend/tests/unit/collector/` — fingerprint, load-from-redis, persist-on-quarantine, fail-open, re-mint.

Touch ONLY the above. Do NOT touch: acquire/rotation/cooldown logic, the alert path, POOL_MIN.
Blast radius: pool construction + quarantine persistence. No schema/API. Redis SET (TTL'd).

## Acceptance Criteria
- [ ] **AC1 — fingerprint.** Each `_Account` carries `session_fingerprint = sha256(session)[:16]`;
  it never equals or contains the session string.
- [ ] **AC2 — load on init.** `from_sessions(redis=r)` marks accounts whose fingerprint is in
  `pool:quarantined_fingerprints` as `quarantined=True` at construction.
- [ ] **AC3 — persist on quarantine.** `quarantine_current()` SADDs the current account's fingerprint
  to the set (best-effort) and refreshes its TTL.
- [ ] **AC4 — fail-open.** A Redis error during load (or persist) logs a warning and does NOT crash
  pool construction (or quarantine); behavior degrades to in-memory-only.
- [ ] **AC5 — re-mint recovery.** A session whose fingerprint is NOT in the set loads as live (a
  re-minted session is never wrongly quarantined).
- [ ] **AC6 — backward compatible.** `from_sessions` without `redis` (default None) = today's
  in-memory-only behavior; existing tests/conftest unchanged. `make ci-fast` green.

## Plan
1. (RED) tests: fingerprint determinism+non-secret; load marks quarantined; quarantine persists
   (SADD + ttl); redis-error fail-open; re-mint not quarantined.
2. (GREEN) `_fingerprint`, `_Account.session_fingerprint`, pool `_redis`, load+persist (best-effort);
   constants; registry wiring.
3. verify (`make ci-fast`); review.

## Invariants
- Session strings are NEVER stored or logged — only the sha256 fingerprint.
- Pool construction never raises on a Redis error (fail-open to in-memory).
- In-memory quarantine semantics unchanged (acquire never hands out a quarantined account).

## Edge cases
- Redis empty / key absent → no accounts quarantined on load (normal cold start).
- Redis down at init → fail-open, warning, in-memory-only.
- Re-minted session → new fingerprint → live; stale old fingerprint TTL-expires.
- `redis=None` (tests/dev) → no persistence, current behavior.

## Test plan
- Unit (fakeredis): fingerprint; load-quarantines-matching; persist-on-quarantine (SADD+TTL>0);
  redis-error fail-open (load + persist); re-mint-not-quarantined; `redis=None` unchanged.
- `make ci-fast` green.
- Prod (post owner-deploy, batched): quarantine a session, restart worker → it stays quarantined
  (no re-try, accurate healthy count); `redis-cli SMEMBERS pool:quarantined_fingerprints`.

## Review (adversarial code + security, fresh-context) — resolved
- **Security: PASS.** Fingerprint `sha256(session)[:16]` is one-way/non-reversible (preimage 2^256
  regardless of truncation; session strings are ~2048-bit), no path leaks the raw session string to
  Redis/logs/alerts/exceptions, collision P≈2.4e-18 for a ≤10 pool, Redis is internal (poisoning not
  a new surface). Added the optional fingerprint-format guard on read (defense-in-depth).
- **Code review: 2 MEDIUM fixed in-PR:** (1) SADD+EXPIRE made ATOMIC via a Redis pipeline (no
  no-TTL window on partial failure); (2) load now handles BOTH bytes and str members (a
  `decode_responses=True` deployment can no longer crash pool boot with AttributeError). **2 LOW
  fixed:** renamed `_SESSION_FINGERPRINT_LEN`→`SESSION_FINGERPRINT_LEN` (cross-module import);
  added the malformed-member-ignored test. Owner feedback: real types (cast to `set[bytes | str]`,
  no Any; isinstance narrowing), runtime guard `_is_valid_fingerprint`.

## Checkpoints
current_step: 6
baseline_commit: "d2fad96"
branch: "task/102-persistent-session-quarantine"
lock: "reliability-loop"
- [x] 1 locate (account_pool + registry redis + TASK-087 quarantine)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: 9 persistence tests — fingerprint/load/persist/fail-open/re-mint/malformed/no-redis)
- [x] 4 verify (G2 — 971 unit pass, mypy clean, ruff clean)
- [x] 5 review (adversarial — 2 MEDIUM + 2 LOW fixed)
- [x] 5.5 security (PASS — non-secret fingerprint, no session leak; format guard added)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (batched, owner cycle)
