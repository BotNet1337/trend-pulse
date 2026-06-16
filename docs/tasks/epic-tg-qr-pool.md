---
id: EPIC-TG-QR-POOL
title: TG session pool — QR-login onboarding + connection-status UI
status: review
owner: backend+frontend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: feat/tg-qr-login
tags: [telegram, pool, qr-login, admin-ui, reliability]
---

# EPIC — TG session pool: QR-login onboarding + connection-status UI

> Admin scans a QR code with the Telegram app → a NEW technical-account StringSession is
> minted ("набить пулл") → the admin UI shows per-account connection status (connected /
> flood-wait cooling / quarantined-dead) and the disconnect reason. Makes controlling the
> TG session pool observable and the pool easy to grow.

## Why
Today the pool is built ONLY from static `TELEGRAM_POOL_SESSIONS` env strings
(`collector/telegram/account_pool.py`, `client.py`). There is no way to:
1. Onboard a new account without manually minting a StringSession on the CLI.
2. See, from the product, whether each pool account is alive or why it died
   (AuthKeyDuplicated / SessionRevoked / FLOOD_WAIT — the TASK-087 incident class).

## Hard safety constraints (carried from memory / incidents)
- **NEVER touch existing live sessions.** QR-login only MINTS new sessions (fresh auth keys) →
  cannot cause AuthKeyDuplicated on existing pool sessions.
- **No hot-swap of the running pool.** A newly-minted session is RETURNED to the admin to add
  to the vault/env and redeploy. Hot-mutating the in-worker pool is out of scope (ADR below).
- **Do NOT deploy from this worktree.** The sibling `apps/trendPulse` worktree has an
  uncommitted vault — `make deploy` is FORBIDDEN here (TASK-107 vault-guard / deploy-vault-hazard).
- Secrets (session strings, api_hash) are NEVER logged.

## Architecture decisions
- **API and collector are SEPARATE processes** (`uvicorn api.main:app` vs Celery worker). The
  pool lives in the worker; the API cannot read it directly →
  - Pool-health is bridged through **Redis**: the collector emits a per-account snapshot each tick
    (TASK-115); the API reads the latest snapshot (TASK-116).
  - QR-login handshake state (a live Telethon `QRLogin`) CANNOT be serialized to Redis, so it
    lives **in-process** in the API. Safe because the API runs a SINGLE uvicorn worker (no
    `--workers` in `development/compose/api.yml` / `release/compose/api.yml`).
    **Invariant:** do NOT add `--workers>1` to the API without moving the QR registry to a
    sticky/Redis-backed store.

## Stories (each executed by its own executor agent + own memory file)
| Story | Scope | Depends on |
|---|---|---|
| [TASK-114](./task-114-qr-login-core.md) | BE core: Telethon QR-login service + in-process registry + domain errors | — |
| [TASK-115](./task-115-pool-health-snapshot.md) | BE worker: per-account status snapshot + last-error reason + Redis emit | — |
| [TASK-116](./task-116-pool-admin-api.md) | BE API: superuser `pool_admin` router (QR start/poll + pool-health read) | 114, 115 |
| [TASK-117](./task-117-pool-admin-ui.md) | FE: admin page — QR flow + pool-health dashboard | 116 |

Execution graph: `[114 ∥ 115] → 116 → 117 → gap-check → local+prod verify`.

## Definition of done (epic)
- Admin opens `/admin/pool`, sees every pool account with state + reason, clicks "Add account",
  scans the QR with Telegram, and on success the UI shows the connection succeeded and exposes the
  new session string to copy into the vault.
- Failures (timeout, 2FA-password-needed, dead account) show a clear reason in the UI.
- All backend changes: full type hints, domain errors, pydantic at the boundary, no secrets logged,
  `make test` + ruff + mypy strict green.

## ADR — session persistence (durable decision)
See `docs/architecture/adr-tg-qr-session-persistence.md`. Summary: minted sessions are returned to
the admin for manual vault/env addition + redeploy; the running pool is NOT hot-mutated. Rationale:
pool lives in a different process, hot-swap requires cross-process reload + client reconnect and
risks the AuthKeyDuplicated incident class. A DB-backed dynamic pool is a deliberate future epic.
