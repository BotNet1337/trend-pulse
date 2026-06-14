"""FastAPI application entrypoint (TASK-030: unified error-envelope + /v1 versioning).

The `/health` endpoint is intentionally at root (no /v1 prefix) — it answers before
infra/provisioning is ready and is used directly by the nginx/compose healthcheck
(ADR-007 §4). Similarly `/ready` stays at root for the same reason.

All other routes are mounted under `/v1` (ADR-007 §3). nginx strips `/api/` so
clients reach them at `/api/v1/...`.

Error contract (ADR-007 §1):
    Every 4xx/5xx response follows the unified envelope:
        {"error": {"code": "<ErrorCode>", "message": str, "details?": [...]}}
    Enforced by the exception-handlers below via `build_error_response` (api.errors).
    No handler emits `{"detail": ...}` — the legacy shape is gone.

Auth routes are mounted from fastapi-users (register / JWT login-logout / Google
OAuth); user-facing routes sit behind the `current_user` dependency (ADR-002).
"""

import logging
from typing import Literal, TypedDict

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.account import delivery_config_router
from api.alerts import router as alerts_router
from api.api_keys import router as api_keys_router
from api.auth import (
    UserCreate,
    UserRead,
    auth_backend,
    build_google_oauth_client,
    current_user,
    fastapi_users,
)
from api.auth.me import router as users_me_router
from api.cases.router import router as cases_router
from api.deps import get_tenant_user_id
from api.errors import (
    ErrorCode,
    build_error_response,
    http_status_to_code,
    normalize_validation_details,
)
from api.feedback.router import router as feedback_router
from api.packs.router import router as packs_router
from api.rate_limit import limiter, rate_limit_handler
from api.referral import router as referral_router
from api.routes import account_router, ops_router
from api.routes.email_unsubscribe import router as email_unsubscribe_router
from api.routes.ops_business import router as ops_business_router
from api.security.csrf import CSRFOriginMiddleware
from api.signals.router import router as signals_router
from api.trending.router import router as trending_router
from api.watchlist import router as watchlist_router
from billing.deps import BillingNotConfiguredError
from billing.limits import PlanLimitExceeded
from billing.router import router as billing_router
from config import get_settings
from observability.logging import configure_logging
from observability.middleware import log_requests
from observability.sentry import init_sentry
from storage.models.users import User

logger = logging.getLogger(__name__)

# Docs paths — named constants (CONVENTIONS: no magic literals).  Used both by
# the _docs_urls helper and by tests that verify the gating behaviour.
# Under /v1 versioning these are served at /v1/openapi.json (per ADR-007 §5).
_DOCS_URL = "/docs"
_REDOC_URL = "/redoc"
_OPENAPI_URL = "/openapi.json"

# Version prefix for all API routes (ADR-007 §3). nginx strips /api/ so
# the client-facing path is /api/v1/... → backend sees /v1/...
_API_VERSION_PREFIX = "/v1"


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

    When enabled the OpenAPI JSON is served at /v1/openapi.json (version prefix
    prepended) so the dump script and frontend gen:api align with the mount point.
    """
    if swagger_enable:
        return {
            "docs_url": _API_VERSION_PREFIX + _DOCS_URL,
            "redoc_url": _API_VERSION_PREFIX + _REDOC_URL,
            "openapi_url": _API_VERSION_PREFIX + _OPENAPI_URL,
        }
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


# Structured JSON logging across the api process (task-011): emit machine-parseable
# logs for ops consumers; the hygiene helper guarantees no raw content is logged.
configure_logging()
# Sentry error-tracking (TASK-024): no-op when SENTRY_DSN is empty (dev default).
init_sentry("api")
# At-rest field encryption (TASK-032 Block C): EncryptedString resolves the key
# lazily from get_settings() on each ORM operation — no explicit configure() call
# needed. This ensures the Celery worker path also decrypts correctly without
# importing api.main. Key is validated at Settings construction (validate_fernet_key).

# Public brand name (TASK-072): user-facing docs show «Foresignal»; internal
# package/env identifiers remain `trendpulse`.
app = FastAPI(title="Foresignal API", **_docs_urls(get_settings().swagger_enable))

# --- Rate limiting (task-011): Redis-backed slowapi, key = user_id|IP, default
# limit from settings. The limiter is attached to app.state (slowapi contract),
# the middleware enforces the default limit on every request, and the breach
# handler maps RateLimitExceeded -> 429 JSON. ---
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Request-logging middleware (aggregate-only: method/path/status/duration). Added
# after SlowAPIMiddleware so it wraps the outermost request lifecycle.
app.middleware("http")(log_requests)

# CSRF/Origin-check middleware (TASK-032, Block B): enforces that state-changing
# requests on cookie-auth sessions include an Origin/Referer from the allow-list.
# Registered after SlowAPIMiddleware (rate-limit fires first) and before routers.
# Exempt: safe methods, X-API-Key requests, /billing/ipn path, unauthenticated.
app.add_middleware(
    CSRFOriginMiddleware,
    allowed_origins=get_settings().allowed_origins_set,
)


# ---------------------------------------------------------------------------
# Exception handlers — unified error-envelope (ADR-007 §1/§2)
# ---------------------------------------------------------------------------


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Map a rate-limit breach (slowapi) to a 429 envelope (no leakage)."""
    return rate_limit_handler(request, exc)


@app.exception_handler(PlanLimitExceeded)
async def _plan_limit_handler(_: Request, exc: PlanLimitExceeded) -> JSONResponse:
    """Map a plan-limit breach to the envelope with the right code.

    PlanLimitExceeded.code == 402 → PLAN_LIMIT_EXCEEDED (over quota → upgrade).
    PlanLimitExceeded.code == 403 → FEATURE_NOT_AVAILABLE (boolean feature gate).
    """
    if exc.code == status.HTTP_402_PAYMENT_REQUIRED:
        code = ErrorCode.PLAN_LIMIT_EXCEEDED
        message = "Plan limit exceeded. Upgrade your plan to continue."
    else:
        code = ErrorCode.FEATURE_NOT_AVAILABLE
        message = "This feature is not available on your current plan."
    return build_error_response(code=code, message=message, status=exc.code)


@app.exception_handler(BillingNotConfiguredError)
async def _billing_unconfigured_handler(_: Request, exc: BillingNotConfiguredError) -> JSONResponse:
    """Billing endpoints hit without NOWPayments credentials → 503 envelope."""
    return build_error_response(
        code=ErrorCode.BILLING_NOT_CONFIGURED,
        message="Billing service is not configured.",
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic RequestValidationError → 422 envelope with normalised field details.

    Strips the Pydantic `body` prefix from `loc` so field paths are clean
    (e.g. `channel.handle` not `body.channel.handle`). AC4.
    """
    details = normalize_validation_details(exc.errors())
    return build_error_response(
        code=ErrorCode.VALIDATION,
        message="Request validation failed.",
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details=details,
    )


@app.exception_handler(Exception)
async def _generic_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected exceptions → sterile 500 envelope.

    Logs the full exception server-side (for ops / Sentry); the response body
    carries only the INTERNAL code and a generic message — no stack/SQL/paths
    (AC7 security invariant).
    """
    logger.error("unhandled exception", exc_info=exc)
    return build_error_response(
        code=ErrorCode.INTERNAL,
        message="Internal error.",
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


from fastapi import HTTPException  # noqa: E402 — after handlers to avoid circular
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Map FastAPI/Starlette HTTPException to the unified envelope.

    Registered for BOTH the FastAPI subclass and the Starlette base class:
    routing misses (unknown path → 404, wrong method → 405) raise the Starlette
    base before the request reaches the application layer — without the second
    registration they would bypass the envelope and return legacy {"detail"}.
    Status → ErrorCode mapping is centralised in `http_status_to_code`.
    Unmapped statuses (5xx from library code etc.) fall through to INTERNAL.
    The `exc.detail` string is passed as `message` but must not leak internals —
    library exceptions (fastapi-users login failure etc.) emit only safe messages.
    """
    code = http_status_to_code(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else "An error occurred."
    return build_error_response(code=code, message=message, status=exc.status_code)


# ---------------------------------------------------------------------------
# Unversioned endpoints (root, per ADR-007 §4)
# ---------------------------------------------------------------------------


class HealthResponse(TypedDict):
    """Liveness payload returned by `GET /health`."""

    status: Literal["ok"]


class TenantResponse(TypedDict):
    """Tenant identity payload for the protected example route."""

    user_id: int


@app.get("/health")
def health() -> HealthResponse:
    """Liveness probe — returns 200 without touching any backing service.

    Intentionally at root (no /v1 prefix): the compose/nginx healthcheck probes
    `http://localhost:8000/health` directly, bypassing nginx (ADR-007 §4).
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /v1 aggregator router — all API routes mount here (ADR-007 §3)
# ---------------------------------------------------------------------------

v1_router = APIRouter(prefix=_API_VERSION_PREFIX)

# --- Auth routers (fastapi-users). ---
v1_router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
v1_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
v1_router.include_router(
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
# --- Email verification routers (TASK-026): POST /auth/request-verify-token +
# POST /auth/verify. Secrets already configured in UserManager.__init__.
# on_after_request_verify hook sends branded verify-email via notifications.email.
v1_router.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
# --- Reset-password routers (TASK-026): POST /auth/forgot-password +
# POST /auth/reset-password. on_after_forgot_password hook sends reset-email.
# no-enumeration: fastapi-users returns a uniform response for forgot-password
# regardless of whether the email exists (AC3 / security invariant).
v1_router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)


@v1_router.get("/users/me/tenant")
def read_my_tenant(user: User = Depends(current_user)) -> TenantResponse:
    """Protected example route (AC2): 401 without a token, tenant id with one."""
    return {"user_id": get_tenant_user_id(user)}


# --- Current-user profile (TASK-014 C2): GET /users/me — read-only, behind
# current_user, returns email/plan/is_verified.  Must be included BEFORE
# watchlist so the `/users/me` path is not shadowed by a more-specific prefix. ---
v1_router.include_router(users_me_router)

# --- API keys (Team plan, feature-gated; TASK-028). ---
v1_router.include_router(api_keys_router)

# --- Alerts read (tenant-scoped, read-only, behind current_user; TASK-016 C4). ---
v1_router.include_router(alerts_router)

# --- Curated channel packs (TASK-038): GET/POST/DELETE /packs. ---
v1_router.include_router(packs_router)

# --- Trending showcase (TASK-039): GET /trending?pack=&limit= (auth required). ---
v1_router.include_router(trending_router)
v1_router.include_router(signals_router)

# --- Watchlist CRUD (tenant-scoped, behind current_user). ---
v1_router.include_router(watchlist_router)

# --- Billing (invoice behind current_user; IPN raw-body, no auth). ---
v1_router.include_router(billing_router)

# --- Delivery-config read/patch (TASK-017 C5): GET/PATCH /users/me/delivery-config
# — behind current_user, feature-gated webhook_url (Pro+), SSRF-validated. ---
v1_router.include_router(delivery_config_router)

# --- GDPR account deletion (DELETE /account, behind current_user). ---
v1_router.include_router(account_router)

# --- Alert feedback (TASK-042): GET /feedback/{token} — unauthenticated,
# HMAC-signed token, rate-limited. Public; accessible via nginx /api/v1/feedback/. ---
v1_router.include_router(feedback_router)

# --- Proof-of-speed cases (TASK-045): GET /cases — public, no auth, read-only. ---
v1_router.include_router(cases_router)

# --- Referral program (TASK-046): GET /referral/me — auth-gated, lazy code gen. ---
v1_router.include_router(referral_router)

# --- Lifecycle-email unsubscribe (TASK-069): GET /email/unsubscribe — public,
# signed-token credential, idempotent opt-out, per-route rate-limit. ---
v1_router.include_router(email_unsubscribe_router)

# --- Business metrics dashboard (TASK-051): GET /ops/business-metrics — superuser-only. ---
v1_router.include_router(ops_business_router)

# Mount the versioned router on the app (all routes become /v1/...).
app.include_router(v1_router)

# Ops readiness probe (GET /ready) stays at ROOT (unversioned), same as /health.
# Infrastructure healthchecks probe it directly by container name/port without nginx.
# See ADR-007 §4.
app.include_router(ops_router)
