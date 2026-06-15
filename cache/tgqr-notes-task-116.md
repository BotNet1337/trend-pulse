# TASK-116 notes — superuser pool-admin API (for TASK-117 frontend)

Branch `feat/tg-qr-login`. Router `backend/src/api/routes/pool_admin.py`, wired in `api/main.py`.
All paths are under the `/v1` version prefix; nginx strips `/api/` so the browser path is
`/api/v1/pool-admin/...`. Every endpoint is SUPERUSER-ONLY (cookie session, `current_superuser`):
- unauthenticated → **401**
- authenticated non-superuser → **403**
- superuser → **200** (or the per-route error below)

Errors follow the unified envelope: `{"error": {"code": "<ErrorCode>", "message": str}}`.

## 1) POST /v1/pool-admin/qr-login/start

Begin a QR login. No request body.

200 response (`QRLoginStartResponse`, `extra="forbid"`):
```jsonc
{
  "token": "string",            // opaque handle — poll with this
  "qr_url": "tg://login?token=...", // render as a QR code
  "expires_at": 1700000000.0,   // epoch seconds (float, wall clock)
  "timeout_seconds": 300        // = settings.qr_login_timeout_seconds
}
```
Error mapping:
- **503** (`code: BILLING...`→ no; generic) when api creds missing — message
  `"QR login is not configured (telegram_api_id / telegram_api_hash missing)."` (no secret/stack leak).
- **429** when too many concurrent logins — message `"Too many concurrent QR logins in progress. Retry shortly."`

## 2) GET /v1/pool-admin/qr-login/{token}

Poll an in-progress login. Path param `token` (the value from `start`).

200 response (`QRLoginPollResponse`, `extra="forbid"`):
```jsonc
{
  "status": "pending" | "success" | "expired" | "password_needed" | "error",
  "expires_at": 1700000000.0,
  "session_string": "1Aa...",   // SECRET — present ONLY when status == "success"; else null
  "reason": "string" | null      // non-secret human note on password_needed/error; else null
}
```
- Unknown / expired / already-consumed token → `status: "expired"`, **200** (NOT 404/500 — safe to poll in a loop).
- On `"success"` the `session_string` is the NEWLY minted StringSession the admin copies to the vault.
  It is served only to a superuser over HTTPS and never logged. The frontend should show it once,
  let the admin copy it, and NOT persist/echo it.
- `"password_needed"` = the account has 2FA (cloud password) — not supported in QR-only login.
- `"error"` `reason` is an exception CLASS NAME only (never a secret-bearing message).

Suggested UI poll cadence: every ~2s until a terminal status (`success`/`expired`/`password_needed`/`error`).

## 3) GET /v1/pool-admin/pool-health

Read the latest pool-health snapshot (TASK-115 `pool:health:latest`). No params.

200 response (`PoolHealthResponse`, `extra="forbid"`):
```jsonc
{
  "size": 3,            // total accounts in the pool
  "cooling": 1,         // LIVE accounts in FLOOD_WAIT cooldown
  "quarantined": 0,     // permanently dead/quarantined accounts
  "healthy": 2,         // size - cooling - quarantined
  "target": 2,          // settings.pool_min_healthy
  "degraded": false,    // healthy < target
  "as_of": "2026-06-16T...+00:00" | null, // snapshot UTC ISO-8601; null when no snapshot
  "stale": false,       // true when snapshot missing/old (collector down/lagging)
  "accounts": [         // empty [] when stale/missing
    {
      "index": 0,                          // stable pool position — the ONLY per-account id
      "state": "healthy" | "cooling" | "quarantined",
      "cooldown_remaining_seconds": 42.0 | null, // >0 only when state=="cooling", else null
      "last_error_reason": ""               // "" | "FLOOD_WAIT" | error class name (last-known)
    }
  ]
}
```
- **`stale=true`** semantics: no/old/malformed snapshot → aggregates are zeroed and `accounts=[]`,
  `as_of=null`. Surface to the user as "no fresh data from collector" rather than an error. Always 200.
- **503** (`code: INTERNAL`/generic, message `"Pool-health store is unreachable."`) ONLY when Redis itself
  is unreachable. Never an unhandled 500.
- Staleness threshold = snapshot age > 2× `collect_interval_seconds`. No secrets in the body (per-account
  identity is the integer `index` only).

## OpenAPI / types
Routes appear in `/v1/openapi.json` under tag `pool-admin` with the `APIKeyCookie` security scheme.
TASK-117 regenerates frontend types from this schema (the response models above are the contract).

## Status codes summary
| Endpoint | success | auth | other |
|---|---|---|---|
| POST /pool-admin/qr-login/start | 200 | 401/403 | 503 (unconfigured), 429 (capacity) |
| GET /pool-admin/qr-login/{token} | 200 (incl. `expired`) | 401/403 | — |
| GET /pool-admin/pool-health | 200 (incl. `stale`) | 401/403 | 503 (redis down) |
