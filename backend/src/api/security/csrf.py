"""CSRF/Origin-check middleware for state-changing cookie-auth requests (TASK-032).

Approach: Origin/Referer header validation (app-middleware, not nginx `if`).
Chosen over double-submit token because:
  - Transferable: no per-form token management needed.
  - Testable: integration tests can set/omit Origin directly.
  - Sufficient: combined with SameSite=Lax cookies it covers the relevant
    attack surface (top-level POST from cross-origin is the gap SameSite=Lax
    leaves; this middleware closes it).

Exemptions (by design, must not block legitimate traffic):
  1. Safe methods: GET / HEAD / OPTIONS — no state change, never blocked.
  2. /billing/ipn path: NOWPayments sends server-side webhooks without an
     Origin header; the IPN is HMAC-verified separately (billing/router.py).
  3. Requests without a session cookie: unauthenticated requests carry no
     session so there is nothing to CSRF. We only inspect cookie-auth.
  4. X-API-Key authenticated requests WITHOUT a session cookie: machine
     clients are not browser CSRF targets. However, a request carrying BOTH
     a session cookie AND an X-API-Key header is still subject to the Origin
     check — the session cookie is the CSRF attack surface, not the API key.

Allow-list: `allowed_origins` from Settings (env ALLOWED_ORIGINS, comma-sep).
  Dev default includes http://localhost so local development works.
  Origin: header is checked first; Referer is used as fallback when Origin is
  absent but Referer is present (some older browsers / form submissions).
  Origin: null is explicitly rejected — it is sent by sandboxed iframes and
  data: URIs and must never be treated as a same-origin indicator.

Failure: HTTP 403 with the unified error envelope (ErrorCode.FORBIDDEN).
"""

import logging
from urllib.parse import urlparse

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from api.auth.backend import cookie_transport
from api.errors import ErrorCode, build_error_response

logger = logging.getLogger(__name__)

# HTTP methods that mutate state — only these are subject to the Origin check.
# Safe methods (RFC 7231 §4.2.1) are explicitly skipped.
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Path prefix for the IPN webhook — must be exempt (server-side callback, no
# browser Origin; HMAC-verified in billing/router.py).
_IPN_PATH_SUFFIX = "/billing/ipn"

# Header used by machine clients authenticated via API key (not cookie-session).
# Presence of this header exempts the request ONLY when no session cookie is
# present — a request with both is still subject to the Origin check (the
# session cookie is the CSRF attack surface).
_API_KEY_HEADER = "x-api-key"


def _extract_origin_host(request: Request) -> str | None:
    """Return the scheme+host from the Origin (or Referer fallback) header.

    Returns None when:
      - Neither header is present.
      - Origin: null is present (sandboxed iframe / data: URI — always rejected).
      - The header value cannot be parsed into a valid scheme+host.

    The "null" origin is explicitly rejected: RFC 6454 §7.3 allows browsers
    to send `Origin: null` for sandboxed iframes; accepting it would bypass
    the check for any cross-origin attacker that can embed a sandboxed iframe.
    """
    origin = request.headers.get("origin")
    if origin is not None:
        # Explicit null origin — sandboxed context, always reject.
        if origin == "null":
            return None
        # Origin value is already scheme+host (e.g. "http://localhost:3000").
        parsed = urlparse(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return None

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _has_session_cookie(request: Request) -> bool:
    """Return True when the request carries the fastapi-users auth cookie.

    We only enforce CSRF on cookie-authenticated requests; unauthenticated
    or purely API-key-authenticated requests are exempt.
    The cookie name is imported from cookie_transport (api/auth/backend) so
    this stays in sync with the actual transport configuration rather than
    relying on a hardcoded literal.
    """
    return cookie_transport.cookie_name in request.cookies


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Origin/Referer allow-list on cookie-auth mutations.

    Register AFTER SlowAPIMiddleware and BEFORE application routers in main.py.
    The allowed_origins set is passed at construction time from Settings so it
    is resolved once at startup (no per-request settings lookup).

    Invariants (TASK-032):
      - Safe methods: always pass.
      - Requests without the session cookie: always pass (not cookie-auth).
      - Requests with X-API-Key AND WITHOUT session cookie: always pass
        (genuine machine client — not a browser CSRF target).
      - Requests with X-API-Key AND WITH session cookie: Origin-checked
        (the session cookie is the attack surface; the API key is irrelevant).
      - IPN path suffix: always pass (NOWPayments webhook, HMAC-verified).
      - Origin: null: always 403 (sandboxed iframe — never a valid origin).
      - Mutation + cookie-auth + unknown/absent Origin: 403.
      - Mutation + cookie-auth + Origin in allow-list: pass.
    """

    def __init__(self, app: object, *, allowed_origins: frozenset[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._allowed_origins = allowed_origins

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Check Origin on state-changing cookie-auth requests."""
        # 1. Safe methods — never block (RFC 7231 §4.2.1).
        if request.method not in _MUTATION_METHODS:
            return await call_next(request)

        # 2. IPN path — exempt (server-side webhook, no browser Origin).
        if request.url.path.endswith(_IPN_PATH_SUFFIX):
            return await call_next(request)

        # 3. No session cookie → not a cookie-auth request, nothing to CSRF.
        #    This must be checked BEFORE the API-key exemption: a cookieless
        #    request (whether or not it has X-API-Key) cannot be CSRF'd.
        if not _has_session_cookie(request):
            return await call_next(request)

        # 4. Cookie-auth request. Check if it is a pure machine-client call:
        #    X-API-Key present WITHOUT session cookie was handled above (step 3).
        #    Here the session cookie IS present — the API key does not exempt
        #    the request from the Origin check; proceed to validation.
        #    (A genuine machine client should never carry a browser session cookie.)

        # 5. Cookie-auth mutation: validate Origin/Referer.
        request_origin = _extract_origin_host(request)
        if request_origin is None:
            # No Origin or Referer on a cookie-auth mutation → reject.
            # Covers both "Origin: null" (sandboxed iframe) and absent headers.
            # A legitimate browser always sends Origin on cross-origin POSTs and
            # usually on same-origin POSTs too; absence on a cookie-auth mutation
            # is suspicious. We choose strict: reject rather than allow unknown.
            logger.warning(
                "csrf_origin_missing method=%s path=%s",
                request.method,
                request.url.path,
            )
            return _csrf_forbidden("Missing Origin or Referer on cookie-auth mutation.")

        if request_origin not in self._allowed_origins:
            logger.warning(
                "csrf_origin_mismatch method=%s path=%s origin=%r allowed=%r",
                request.method,
                request.url.path,
                request_origin,
                self._allowed_origins,
            )
            return _csrf_forbidden(f"Origin '{request_origin}' is not in the allowed-origin list.")

        return await call_next(request)


def _csrf_forbidden(detail: str) -> JSONResponse:
    """Build a 403 response using the unified error envelope (ADR-007 §1)."""
    return build_error_response(
        code=ErrorCode.FORBIDDEN,
        message=detail,
        status=status.HTTP_403_FORBIDDEN,
    )
