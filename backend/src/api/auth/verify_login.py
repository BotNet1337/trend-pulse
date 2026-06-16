"""Email-confirmation endpoint that auto-logs the user in.

fastapi-users' stock ``POST /auth/verify`` only flips ``is_verified`` and returns
the user — the client must then sign in again with email+password.  This router
adds ``POST /auth/email/confirm``: it verifies the token AND, on success, issues
the same httpOnly session cookie the login endpoint would, so the freshly-verified
user lands authenticated on the dashboard with no second step (items 3+4).

Security: identical auth backend (JWT-over-cookie) as ``/auth/jwt/login`` — no new
token transport, no token in the response body.  The verification token is never
logged. Already-verified tokens return 409 (the client routes those to sign-in).
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi_users import exceptions
from starlette.responses import Response

from api.auth.backend import auth_backend, get_jwt_strategy
from api.auth.users import UserManager, get_user_manager

router = APIRouter()


@router.post(
    "/email/confirm",
    name="auth:verify_and_login",
    summary="Verify an email token and start an authenticated session",
)
async def verify_and_login(
    request: Request,
    token: str = Body(..., embed=True),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    """Verify the email token and set the auth cookie (auto-login).

    - 204 + Set-Cookie on success (user is now verified AND logged in).
    - 400 when the token is invalid/expired or the user no longer exists.
    - 409 when the email was already verified — the client sends the user to
      sign-in (we cannot mint a session without re-authentication in that case).
    """
    try:
        user = await user_manager.verify(token, request)
    except (exceptions.InvalidVerifyToken, exceptions.UserNotExists) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link.",
        ) from exc
    except exceptions.UserAlreadyVerified as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already verified.",
        ) from exc

    # Issue the session cookie via the shared JWT-over-cookie backend — identical
    # transport to POST /auth/jwt/login. Returns a 204 Response with Set-Cookie.
    strategy = get_jwt_strategy()
    return await auth_backend.login(strategy, user)
