# ADR-007 — API error-envelope format and versioning (`/api/v1`)

- Status: **Accepted**
- Date: 2026-06-11
- Context: [high-level-architecture.md](./high-level-architecture.md), [TASK-030](../tasks/task-030-api-hardening-errors-versioning.md)

## Context

TrendPulse backend (FastAPI) currently returns heterogeneous error bodies:

| Source | Body shape |
|---|---|
| `HTTPException` (fastapi built-in) | `{"detail": "<str>"}` |
| `PlanLimitExceeded` (402/403) | `{"detail": "<str>"}` |
| `BillingNotConfiguredError` (503) | `{"detail": "<str>"}` |
| `RateLimitExceeded` (slowapi, 429) | `{"detail": "<str>"}` |
| `RequestValidationError` (Pydantic 422) | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| Generic `Exception` (500) | FastAPI default (may leak internals) |

The frontend `backend-error.ts` discriminates errors by **HTTP status code** alone —
a fragile heuristic: status 403 can mean "feature not on plan" or "forbidden access",
and status 422 is ambiguous between Pydantic validation and domain errors.

Routes are mounted at the root (`/auth`, `/watchlists`, …); nginx strips `/api/` so
`/api/...` externally becomes `/...` on the backend. There is no versioning prefix.

## Decision

### 1 — Unified error envelope

Every 4xx/5xx response from the API MUST conform to:

```json
{
  "error": {
    "code": "<ErrorCode>",
    "message": "<human-readable string>",
    "details": [{"field": "<dot.path>", "message": "<str>"}]
  }
}
```

- `details` is present **only** for 422 validation errors; absent otherwise.
- The envelope is enforced by a single set of `@app.exception_handler` overrides in
  `api/main.py` and a shared builder `build_error_response` in `api/errors.py`.
- Legacy `{"detail": ...}` shape is **gone** from API responses (except proxy/CDN
  responses not under our control, handled by the frontend legacy-fallback).

### 2 — Machine-readable error codes (`ErrorCode`)

Codes live in `api/errors.py` as a `StrEnum` (no magic literals on call-sites):

| `ErrorCode` | HTTP status | Trigger |
|---|---|---|
| `UNAUTHORIZED` | 401 | Unauthenticated request |
| `FORBIDDEN` | 403 | Non-plan-limit access denial |
| `PLAN_LIMIT_EXCEEDED` | 402 | Over quantitative plan quota |
| `FEATURE_NOT_AVAILABLE` | 403 | Boolean feature not on plan |
| `NOT_FOUND` | 404 | Resource absent or tenant-hidden |
| `DUPLICATE` | 409 | Unique-constraint violation |
| `VALIDATION` | 422 | Pydantic / input validation failure |
| `RATE_LIMITED` | 429 | Rate-limit breach (slowapi) |
| `BILLING_NOT_CONFIGURED` | 503 | NOWPayments credentials missing |
| `INTERNAL` | 500 | Unexpected server error (sterile) |

The `403 FORBIDDEN` / `403 FEATURE_NOT_AVAILABLE` split:
- `PlanLimitExceeded(code=403)` → `FEATURE_NOT_AVAILABLE` (upsell / feature-gate).
- All other 403 `HTTPException` → `FORBIDDEN`.

The `500 INTERNAL` body MUST NOT contain stack traces, exception repr, SQL, or
internal paths. The full error is logged server-side with a structured log event.

### 3 — Versioning strategy: **v1-only, atomic switch**

**Decision:** mount all backend routers under the `/v1` prefix (via an aggregator
`APIRouter(prefix="/v1")`). Nginx continues to strip `/api/` exactly as before:

```
Client: GET /api/v1/watchlists
nginx:  strip /api/ → backend sees: GET /v1/watchlists
backend: /v1 prefix matched → handler executes
```

No backward-compatible root aliases are kept. The frontend `baseURL` and all
direct `/api/` calls in the e2e suite are updated **in the same PR** (atomic switch).

**Rationale for v1-only (no alias):** the nginx proxy is internal, and both the
frontend and backend are deployed as a single unit. A transitional alias would
permanently maintain two code paths with no consumer benefiting from the old path.
The atomic switch is safer given full ownership of all clients.

### 4 — Unversioned endpoints (health, readiness)

`GET /health` and `GET /ready` are **intentionally kept at the root** (no `/v1` prefix):

- The docker-compose healthcheck (`http://localhost:8000/health`) probes the backend
  directly by container name and port — it does not go through nginx. Changing the
  path breaks the healthcheck without a coordinated compose update.
- Infrastructure liveness/readiness probes must not be affected by API versioning.
- These endpoints return non-envelope bodies (`{"status": "ok"}`, per-dep markers)
  which is acceptable for infra probes (not consumed by API clients).

### 5 — OpenAPI schema endpoint

The OpenAPI JSON schema is exposed at `/v1/openapi.json` (under the versioned
sub-router) when `SWAGGER_ENABLE=true`. The `dump_openapi.py` script continues to
call `app.openapi()` directly (no HTTP request) so it is unaffected by the URL change.
The frontend `gen:api` script reads the committed `openapi.json` dump, not a live URL.

### 6 — OAuth callback path and Google Console redirect URI

The Google OAuth callback route (`/auth/google/callback`) moves from
`/auth/google/callback` to `/v1/auth/google/callback` (still stripped by nginx to
that path from `/api/v1/auth/google/callback`).

**Deploy note (manual action required):**
The `redirect_uri` registered in the Google Cloud Console (OAuth 2.0 client) must be
updated from:
```
https://<domain>/api/auth/google/callback
```
to:
```
https://<domain>/api/v1/auth/google/callback
```
This is a deploy-time configuration change in the Google Cloud Console.
Until the redirect URI is updated, Google OAuth will reject the callback with an
`invalid redirect_uri` error. The backend `build_google_oauth_client()` in
`api/auth/oauth.py` constructs the client from `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` settings only; the redirect_uri is computed dynamically by
`httpx-oauth` from the current request host. Nginx's strip-prefix is already
accounted for (the callback lands at `/v1/auth/google/callback` on the backend,
which is registered under the `/v1` prefix). **No code change needed** — the Google
Console registration is the only manual step.

### 7 — Feedback URL (TASK-042 `_FEEDBACK_API_PATH`)

The public feedback button URL builder in `alerts/formatting.py` uses:
```python
_FEEDBACK_API_PATH = "/api/feedback/"
```
This must be updated to `/api/v1/feedback/` to match the new nginx-exposed path
(`/api/v1/feedback/<token>` → backend `/v1/feedback/<token>`). The change is made
in the same PR. Existing signed tokens remain valid (the JWT payload does not encode
the URL).

## Consequences

**Positive:**
- Single error contract across all routes → frontend `switch(error.code)` is stable
  and unambiguous (no more 403-dual-meaning hack).
- Machine-readable codes enable typed SDK generation and structured monitoring.
- `/api/v1` prefix signals contract stability and enables future `/api/v2` without
  a flag-day migration.
- 500 responses are sterile by construction (AC7 / security 5.5).

**Negative / risks:**
- Blast radius: every existing integration test path changes from `/auth/...` to
  `/v1/auth/...` etc. → all integration tests updated in this PR.
- Google Console redirect URI must be updated before deploying to prod (deploy note
  above — human step).
- E2e specs use hardcoded `/api/...` paths and are updated synchronously.
- `_FEEDBACK_API_PATH` change invalidates old Telegram feedback buttons already sent
  (buttons contain the old URL). New alerts will use the correct path immediately.

## Invariants

- `GET /health` and `GET /ready` remain at root, return non-envelope bodies.
- All other routes live under `/v1/` on the backend (exposed as `/api/v1/` via nginx).
- No route returns `{"detail": ...}` — the single builder enforces the envelope.
- `ErrorCode` values are stable StrEnum members; no magic literals on call-sites.
