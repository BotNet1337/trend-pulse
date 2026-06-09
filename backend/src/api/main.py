"""FastAPI application entrypoint.

The `/health` endpoint is intentionally pure (no DB/Redis call) so it answers
before infra/provisioning is ready and is safe for the nginx edge healthcheck.

Auth routes are mounted from fastapi-users (register / JWT login-logout / Google
OAuth); user-facing routes sit behind the `current_user` dependency (ADR-002).
"""

from typing import Literal, TypedDict

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.account import delivery_config_router
from api.alerts import router as alerts_router
from api.auth import (
    UserCreate,
    UserRead,
    auth_backend,
    build_google_oauth_client,
    current_user,
    fastapi_users,
)
from api.auth.me import router as users_me_router
from api.deps import get_tenant_user_id
from api.rate_limit import limiter, rate_limit_handler
from api.routes import account_router, ops_router
from api.watchlist import router as watchlist_router
from billing.deps import BillingNotConfiguredError
from billing.limits import PlanLimitExceeded
from billing.router import router as billing_router
from config import get_settings
from observability.logging import configure_logging
from observability.middleware import log_requests
from storage.models.users import User

# Docs paths — named constants (CONVENTIONS: no magic literals).  Used both by
# the _docs_urls helper and by tests that verify the gating behaviour.
_DOCS_URL = "/docs"
_REDOC_URL = "/redoc"
_OPENAPI_URL = "/openapi.json"


class _DocsUrls(TypedDict):
    """FastAPI constructor kwargs that control interactive docs availability."""

    docs_url: str | None
    redoc_url: str | None
    openapi_url: str | None


def _docs_urls(swagger_enable: bool) -> _DocsUrls:
    """Return docs URL kwargs for the FastAPI constructor.

    Docs/Redoc/OpenAPI paths are enabled only when *swagger_enable* is True
    (dev default via SWAGGER_ENABLE=true).  Passing None to FastAPI disables the
    endpoint entirely → 404 (prod default — schema must not be exposed outside).
    """
    if swagger_enable:
        return {"docs_url": _DOCS_URL, "redoc_url": _REDOC_URL, "openapi_url": _OPENAPI_URL}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


# Structured JSON logging across the api process (task-011): emit machine-parseable
# logs for ops consumers; the hygiene helper guarantees no raw content is logged.
configure_logging()

app = FastAPI(title="TrendPulse API", **_docs_urls(get_settings().swagger_enable))

# --- Rate limiting (task-011): Redis-backed slowapi, key = user_id|IP, default
# limit from settings. The limiter is attached to app.state (slowapi contract),
# the middleware enforces the default limit on every request, and the breach
# handler maps RateLimitExceeded -> 429 JSON. ---
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Request-logging middleware (aggregate-only: method/path/status/duration). Added
# after SlowAPIMiddleware so it wraps the outermost request lifecycle.
app.middleware("http")(log_requests)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Map a rate-limit breach (slowapi) to a clear 429 JSON body (no leakage)."""
    return rate_limit_handler(request, exc)


@app.exception_handler(PlanLimitExceeded)
async def _plan_limit_handler(_: Request, exc: PlanLimitExceeded) -> JSONResponse:
    """Map a plan-limit breach to its HTTP code hint: 402 (quota) / 403 (feature)."""
    return JSONResponse(status_code=exc.code, content={"detail": str(exc)})


@app.exception_handler(BillingNotConfiguredError)
async def _billing_unconfigured_handler(_: Request, exc: BillingNotConfiguredError) -> JSONResponse:
    """Billing endpoints hit without NOWPayments credentials → 503 (not a 500)."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


class HealthResponse(TypedDict):
    """Liveness payload returned by `GET /health`."""

    status: Literal["ok"]


class TenantResponse(TypedDict):
    """Tenant identity payload for the protected example route."""

    user_id: int


@app.get("/health")
def health() -> HealthResponse:
    """Liveness probe — returns 200 without touching any backing service."""
    return {"status": "ok"}


# --- Auth routers (fastapi-users). ---
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_oauth_router(
        build_google_oauth_client(),
        auth_backend,
        get_settings().oauth_state_secret,
        associate_by_email=True,
        # CSRF double-submit cookie must follow the same Secure policy as the auth
        # cookie: False over local http (else it's never sent back on /callback and
        # the state check fails), True on prod HTTPS.
        csrf_token_cookie_secure=get_settings().auth_cookie_secure,
    ),
    prefix="/auth/google",
    tags=["auth"],
)


@app.get("/users/me/tenant")
def read_my_tenant(user: User = Depends(current_user)) -> TenantResponse:
    """Protected example route (AC2): 401 without a token, tenant id with one."""
    return {"user_id": get_tenant_user_id(user)}


# --- Current-user profile (TASK-014 C2): GET /users/me — read-only, behind
# current_user, returns email/plan/is_verified.  Must be mounted BEFORE
# watchlist so the `/users/me` path is not shadowed by a more-specific prefix. ---
app.include_router(users_me_router)

# --- Alerts read (tenant-scoped, read-only, behind current_user; TASK-016 C4). ---
app.include_router(alerts_router)

# --- Watchlist CRUD (tenant-scoped, behind current_user). ---
app.include_router(watchlist_router)

# --- Billing (invoice behind current_user; IPN raw-body, no auth). ---
app.include_router(billing_router)

# --- Delivery-config read/patch (TASK-017 C5): GET/PATCH /users/me/delivery-config
# — behind current_user, feature-gated webhook_url (Pro+), SSRF-validated. ---
app.include_router(delivery_config_router)

# --- GDPR account deletion (DELETE /account, behind current_user) + ops
# readiness probe (GET /ready), task-011. ---
app.include_router(account_router)
app.include_router(ops_router)
