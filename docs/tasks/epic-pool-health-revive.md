---
id: EPIC-POOL-HEALTH-REVIVE
title: Pool health honesty + dynamic session store + QR in-place revive
status: planned
owner: backend+frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 98bd84c834fb58f266e4837a54783d508f129070
branch: feat/pool-health-revive
tags: [telegram, pool, observability, qr-login, session-store, revive, reliability]
---

# EPIC — Pool health honesty + dynamic session store + QR in-place revive

> A prod incident showed the `/admin/pool` UI as `healthy=2 / Connected` while ingest had been
> dead ~16h. This epic makes pool health HONEST (a "Connected" row means the account is actually
> reading), and lets the owner REVIVE a dead/expired account in place by scanning a QR — the same
> account, new session, status flips dead → connected, no duplicate row, no manual vault edit.

## Gap analysis (root-caused — do not re-derive)

The pool lives in the Celery worker; the API reads a Redis snapshot (EPIC-TG-QR-POOL, TASK-115/116).

1. **Health is dishonest.** An account can connect fine yet read nothing. Prod evidence:
   `collect_tick collected posts=0 refs=108` every tick + `"Server replied with a wrong session ID"
   ×207`. That Telethon error is the symptom of the SAME session used concurrently elsewhere (the
   AuthKeyDuplicated incident class), but it is **NOT** a permanent-auth error
   (`auth_errors.is_permanent_auth_error` → False), so the account is never quarantined. It keeps
   `connecting` → `account_statuses()` reports `healthy` → the UI says `Connected`. The current
   health model only knows {healthy, cooling, quarantined}; it has no notion of
   *connected-but-not-reading*. The non-permanent error is swallowed at the reader catch sites
   without being recorded.

2. **No revive path.** [adr-tg-qr-session-persistence.md](../architecture/adr-tg-qr-session-persistence.md)
   said a QR-minted session is returned to the admin to paste into the vault + redeploy; the pool is
   never hot-mutated. That does not match the owner's ask: re-scanning a QR for an account already in
   the pool should revive that same slot in place.

3. **No emit cadence discipline.** The collector emits `pool_health` far more often than once per
   tick in some paths (prod logs ~1/sec). It should be once per tick where reasonable.

## Stories

| Story | Scope (1-liner) | Depends on |
|---|---|---|
| [TASK-118](./task-118-pool-health-honesty.md) | Track per-account READ OUTCOME on `_Account`; add a `failing` state + reason; surface the all-healthy-but-ingest-stale contradiction; fix emit cadence; FE renders `failing` + relabels `healthy/target`. | 115, 116, 117, 100 |
| [TASK-119](./task-119-dynamic-session-store-revive.md) | DB `pool_sessions` table (session ENCRYPTED at rest, keyed by `tg_user_id`); QR login calls `get_me()`; worker loads (DB ∪ env); SAFE single-slot disconnect-then-connect live revive; clear persisted quarantine on revive. | 118, 114, 115 |
| [TASK-120](./task-120-revive-api-and-ui.md) | API: QR poll returns identity + REVIVE/ADD; pool-health exposes per-account non-secret identity. FE: "Add / re-connect account"; revived row flips to Connected; show per-account identity. | 119, 116, 117 |

Execution graph: `118 → 119 → 120 → gap-check → local + prod verify` (118 is the honesty
foundation the revive UI relies on to *show* the status flip; 119 is the riskiest — the live
single-slot swap; 120 is the thin API+FE surface over it).

## Hard constraints (carried into every story)

- **NEVER run the same TG session concurrently from two clients** (AuthKeyDuplicated — see
  [adr-dynamic-pool-session-store.md](../architecture/adr-dynamic-pool-session-store.md) and the
  2026-06-15 deploy-vault / tg-session-incident memories). A revive MUST `disconnect()` the old
  client for that slot BEFORE connecting the new session, and MUST touch only that one slot.
- **Session strings are SECRETS**: encrypted at rest in the DB via the existing `EncryptedString`
  TypeDecorator (ADR-008); NEVER logged; never in Redis plaintext; never in an API response except
  the existing one-shot superuser copy-field.
- Full type hints, domain errors, pydantic at the boundary, named constants (no magic literals),
  surgical diffs. `make test` + ruff + mypy strict green.
- **Do NOT deploy from this worktree** — a sibling worktree may have an uncommitted vault
  (TASK-107 / deploy-vault-hazard). Live verify is owner-gated.

## ADR

This epic writes [adr-dynamic-pool-session-store.md](../architecture/adr-dynamic-pool-session-store.md),
which supersedes (in part) [adr-tg-qr-session-persistence.md](../architecture/adr-tg-qr-session-persistence.md):
the dynamic store + safe single-slot disconnect-then-connect revive is now allowed because it never
double-connects a session and never reconnects untouched slots.

## Definition of done (epic)

- The owner opens `/admin/pool`; an account that connects but never reads shows **Failing** (with the
  "wrong session ID" reason), not Connected; an all-healthy snapshot that contradicts ingest
  staleness is visibly flagged.
- The owner clicks "Add / re-connect account", scans the QR for an account ALREADY in the pool, and
  that same row's status flips dead/expired → Connected — no duplicate row, no manual vault edit.
- No session string is ever logged or stored in plaintext; no AuthKeyDuplicated regression.

## Open owner decisions (flagged, not blocking — defaults chosen)

- Failing thresholds (consecutive failures / zero-read window) — defaults in TASK-118.
- `pool_sessions` row retention on revoke (soft `revoked_at` vs hard delete) — default soft, TASK-119.
- Whether the worker revive polls a Redis signal each tick or also reloads the DB on a fixed interval
  — default: Redis revive-signal each tick + DB load at pool build, TASK-119.
