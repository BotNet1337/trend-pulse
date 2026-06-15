# ADR — TG QR-login session persistence

- Status: accepted
- Date: 2026-06-16
- Epic: EPIC-TG-QR-POOL

## Context
The technical-account pool (`collector/telegram/account_pool.py`) is built ONCE per Celery worker
process from the env string `TELEGRAM_POOL_SESSIONS` (`config.telegram_pool_sessions`). The QR-login
feature mints NEW `StringSession` strings in the API process. The API and the worker are separate
processes, so the API cannot inject a new session into the live in-worker pool without a
cross-process reload and a client reconnect.

## Decision
A QR-minted session is **returned to the admin** (via the poll endpoint / UI) to add to the vault
(`TELEGRAM_POOL_SESSIONS`) and redeploy. The running pool is **NOT hot-mutated** at runtime.

## Rationale
- Hot-swapping the in-worker pool requires cross-process signalling + rebuilding clients, which
  reconnects sessions — exactly the manoeuvre that triggered the AuthKeyDuplicated incident
  (memory: TG session incident, deploy-vault hazard, TASK-087).
- Minting (new auth key) is safe and isolated; persisting via the existing env path reuses the
  already-audited `AccountPool.from_sessions` boot wiring with zero new failure modes.
- Keeps the epic surgical: no DB schema, no runtime pool-mutation machinery.

## Consequences
- New sessions become live only after the owner updates the vault and redeploys (owner-gated, as
  all session changes already are).
- A future epic may add a DB-backed dynamic pool with safe reload; explicitly out of scope here.
