---
id: TASK-116
title: Superuser pool-admin API — QR login endpoints + pool-health read
status: planned
owner: backend
created: 2026-06-16
updated: 2026-06-16
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
tags: [api, telegram, qr-login, admin]
---

# TASK-116 — Superuser pool-admin API

> A superuser-gated router exposing: start a QR login, poll it, and read the latest pool-health
> snapshot. Wires TASK-114 (QR service) and TASK-115 (Redis snapshot) to the frontend.

## Context
Part of EPIC-TG-QR-POOL. Depends on TASK-114 (`collector/telegram/qr_login.py`) and TASK-115
(`pool:health:latest` Redis snapshot). Mirror an existing router for layout and the `current_superuser`
gate (`api/auth/backend.py:57`, already exported via `api/auth/__init__.py`). Routers are included in
`api/main.py`. Pydantic models at the boundary (`ConfigDict(extra="forbid")`). Errors via the unified
envelope (`api/errors.py`).

## Goal
New router (`api/routes/pool_admin.py` or `api/pool_admin/`) with:
- `POST /pool-admin/qr-login/start` → `{ token, qr_url, expires_at, timeout_seconds }`.
- `GET /pool-admin/qr-login/{token}` → `{ status, session_string?, reason?, expires_at }`
  (status ∈ pending/success/expired/password_needed/error).
- `GET /pool-admin/pool-health` → aggregates + per-account list + `stale: bool` + `as_of`, read from
  the Redis snapshot.
All endpoints `Depends(current_superuser)` (403 for non-admin, 401 unauthenticated).

## Discussion
- Q: how does the API hold the QR service singleton? → A: a module-level `QRLoginService` built from
  settings (api_id/api_hash), provided via a FastAPI dependency. One instance per process (matches the
  in-process registry design from TASK-114).
- Q: missing api creds? → A: `start` returns 503 with a clear "QR login not configured" message
  (catch `QRLoginNotConfiguredError`).
- Q: snapshot missing/stale in Redis? → A: pool-health returns `stale: true` (and empty/aggregate-only
  body) rather than erroring, so the UI can say "no fresh data from collector".
- Q: returning the session string over the API — safe? → A: superuser-only, HTTPS, never logged; it
  is the whole point (admin copies it to the vault). Mark the field clearly; do not log request/response
  bodies for this route.

## Scope
- Touch ONLY:
  - NEW `backend/src/api/routes/pool_admin.py` (router + pydantic models + QR-service dependency)
  - `backend/src/api/main.py` (include the router)
  - `backend/src/api/errors.py` ONLY if a new ErrorCode is genuinely needed (prefer reusing existing)
  - NEW `backend/tests/integration/test_pool_admin_api.py`
- Do NOT touch: the QR service internals (114), the pool/snapshot emit (115), auth backend.
- Blast radius: adds public API surface (3 admin endpoints) → triggers security stage. OpenAPI schema
  grows → frontend regenerates types in TASK-117.

## Acceptance Criteria
- [ ] Given a non-superuser (or anonymous), When hitting any `/pool-admin/*`, Then 403 (resp. 401).
- [ ] Given a superuser, When `POST /pool-admin/qr-login/start` with creds configured, Then 200 with
      `token`, `qr_url` (`tg://login?token=...`), `expires_at`, `timeout_seconds`.
- [ ] Given creds NOT configured, When start, Then 503 with a clear message (no stack/secret leak).
- [ ] Given a token, When `GET /pool-admin/qr-login/{token}`, Then it reflects the service status; on
      success the body includes `session_string`.
- [ ] Given a fresh snapshot in Redis, When `GET /pool-admin/pool-health`, Then 200 with aggregates +
      `accounts[]` + `stale=false` + `as_of`; given no/old snapshot, `stale=true`.
- [ ] Response/request bodies of `/pool-admin/*` are excluded from any body-logging middleware (or the
      route does not log them).

## Plan
1. Read the closest existing router (e.g. `api/routes/ops*.py`) for the exact APIRouter/model/gate
   idiom and the `api/main.py` include pattern.
2. `pool_admin.py` — pydantic response models (`extra="forbid"`); a `get_qr_login_service()`
   dependency returning a process-singleton built from settings; the 3 endpoints; map
   `QRLoginNotConfiguredError`→503, unknown token→`expired` status (not 500).
3. Pool-health read: parse `pool:health:latest` JSON from Redis (reuse the API's existing redis
   dependency), compute `stale` from snapshot age vs the TTL/as_of.
4. `main.py` — include the router with the same prefix/tags convention as neighbors.
5. Integration tests with an async client + a superuser fixture + fake QR service + fake redis: cover
   auth gating, start/poll happy + error paths, pool-health fresh/stale.

## Invariants
- Every route superuser-gated; unified error envelope on failures.
- No secret (session_string/api_hash) is logged anywhere on this router.
- Pydantic validates all inputs/outputs; no bare `Any` crosses the boundary.

## Edge cases
- Telethon/api creds absent → 503, never 500.
- Redis down → pool-health returns `stale=true` with a clear note (or 503 if reading is impossible),
  never an unhandled 500.
- Unknown/expired token → `expired` status, 200 (not 404 storm from UI polling).

## Test plan
- integration: `test_pool_admin_api.py` — auth matrix (anon/user/superuser), start/poll happy+error,
  pool-health fresh/stale, 503 when unconfigured.

## Checkpoints
current_step: 3
baseline_commit: 6949babd443c7bc0d3152a2f6cf097c72ec3f42f
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + lint + typecheck + real request)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (auth + secrets + public API — REQUIRED)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial)
