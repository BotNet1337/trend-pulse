"""FastAPI application entrypoint.

The `/health` endpoint is intentionally pure (no DB/Redis call) so it answers
before infra/provisioning is ready and is safe for the nginx edge healthcheck.

Auth routes are mounted from fastapi-users (register / JWT login-logout / Google
OAuth); user-facing routes sit behind the `current_user` dependency (ADR-002).
"""

from typing import Literal, TypedDict

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from api.auth import (
    UserCreate,
    UserRead,
    auth_backend,
    build_google_oauth_client,
    current_user,
    fastapi_users,
)
from api.deps import get_tenant_user_id
from api.watchlist import router as watchlist_router
from billing.deps import BillingNotConfiguredError
from billing.limits import PlanLimitExceeded
from billing.router import router as billing_router
from config import get_settings
from storage.models.users import User

app = FastAPI(title="TrendPulse API")


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


# --- Watchlist CRUD (tenant-scoped, behind current_user). ---
app.include_router(watchlist_router)

# --- Billing (invoice behind current_user; IPN raw-body, no auth). ---
app.include_router(billing_router)
