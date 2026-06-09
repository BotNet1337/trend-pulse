"""User-database adapter + UserManager — fastapi-users config (no hand-rolled auth).

`get_user_db` binds the async SQLAlchemy session to the single `User`/`OAuthAccount`
models. `UserManager` subclasses `IntegerIDMixin` (integer PK) + `BaseUserManager`;
password hashing (argon2 via the default `PasswordHelper`), token issuing and the
register/verify/reset flows are all the library's — we only supply the secrets
(from settings) and the on_after_* hooks that deliver branded emails.

TASK-026: on_after_register triggers email-verification automatically; hooks for
on_after_request_verify and on_after_forgot_password send deeplinks to the frontend
pages via the templates service + SMTP (notifications.email, task-025).

Security invariants (TASK-026 / CONVENTIONS):
  - No tokens, emails, or passwords are written to logs (only user.id).
  - Email delivery is best-effort: failures are caught + logged without re-raising
    so that registration and password-reset HTTP responses are never blocked.
  - Deeplinks use settings.frontend_base_url (HTTPS in prod, overridable via env).
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, IntegerIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from notifications.email import send_templated_email
from storage.database import get_async_session
from storage.models.users import OAuthAccount, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Named constants — CONVENTIONS: no magic literals.
# ---------------------------------------------------------------------------

# Frontend deeplink paths (must match router.ts paths.auth.*).
_CONFIRM_EMAIL_PATH = "/auth/email/confirm"
_RESET_PASSWORD_PATH = "/auth/password/reset"

# Email subjects.
_VERIFY_SUBJECT = "Verify your TrendPulse email"
_RESET_SUBJECT = "Reset your TrendPulse password"

# Display string for the token TTL shown in email bodies.
# fastapi-users defaults: verification_token_lifetime_seconds=3600,
# reset_password_token_lifetime_seconds=3600.
_TOKEN_TTL_LABEL = "1 hour"


# ---------------------------------------------------------------------------
# DB adapter
# ---------------------------------------------------------------------------


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    """Yield the SQLAlchemy user-db adapter bound to `User` + `OAuthAccount`."""
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


# ---------------------------------------------------------------------------
# UserManager
# ---------------------------------------------------------------------------


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    """fastapi-users manager for an integer-id `User`.

    The reset/verification token secrets reuse `jwt_secret` (single server secret,
    sourced from sensitive.env), set on the instance so a missing env still fails
    fast at construction. Hashing/token mechanics are inherited from the library —
    we do NOT implement them.
    """

    def __init__(self, user_db: SQLAlchemyUserDatabase[User, int]) -> None:
        super().__init__(user_db)
        secret = get_settings().jwt_secret
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Audit hook — log the new user id (never email/password), then trigger
        email verification automatically so the user receives the verify email
        immediately after registration without a separate action.
        """
        logger.info("user registered: id=%s", user.id)
        # Trigger email verification automatically (TASK-026 AC1).
        # on_after_request_verify will be called by the library with the token.
        try:
            await self.request_verify(user, request)
        except Exception:
            # request_verify may raise if the user is already verified or if the
            # library has a guard. Treat as best-effort — do not block register.
            logger.warning("auto request_verify failed for user id=%s (already verified?)", user.id)

    async def on_after_request_verify(
        self,
        user: User,
        token: str,
        request: Request | None = None,
    ) -> None:
        """Send a branded verify-email deeplink.

        Security: token is embedded in the URL only — NEVER passed to logger.*
        (CONVENTIONS / task-026 invariants).  Email delivery is best-effort.
        """
        settings = get_settings()
        # Build deeplink: frontend confirm-email page with token + encoded email.
        verify_url = (
            f"{settings.frontend_base_url}{_CONFIRM_EMAIL_PATH}"
            f"?token={token}&email={quote(user.email)}"
        )
        await _send_email_best_effort(
            user_id=user.id,
            to=user.email,
            template="auth/verify-email",
            subject=_VERIFY_SUBJECT,
            props={
                "userName": user.email,
                "verifyUrl": verify_url,
                "expiresAt": _TOKEN_TTL_LABEL,
            },
        )

    async def on_after_forgot_password(
        self,
        user: User,
        token: str,
        request: Request | None = None,
    ) -> None:
        """Send a branded reset-password deeplink.

        Security: token is embedded in the URL only — NEVER passed to logger.*
        (CONVENTIONS / task-026 invariants).  Email delivery is best-effort.
        no-enumeration: fastapi-users always returns the same HTTP response for
        forgot-password regardless of whether the user exists; this hook is only
        called for real users, keeping the response uniform externally.
        """
        settings = get_settings()
        reset_url = f"{settings.frontend_base_url}{_RESET_PASSWORD_PATH}?token={token}"
        await _send_email_best_effort(
            user_id=user.id,
            to=user.email,
            template="auth/reset-password",
            subject=_RESET_SUBJECT,
            props={
                "userName": user.email,
                "resetUrl": reset_url,
                "expiresAt": _TOKEN_TTL_LABEL,
            },
        )


async def _send_email_best_effort(
    *,
    user_id: int,
    to: str,
    template: str,
    subject: str,
    props: dict[str, object],
) -> None:
    """Dispatch send_templated_email in a thread (sync I/O) — best-effort.

    Failures are caught and logged with only the user id (no email/token/URL
    in the log line) so the caller's flow is never blocked by email infra.
    """
    try:
        await asyncio.to_thread(
            send_templated_email,
            to=to,
            template=template,
            props=props,
            subject=subject,
        )
    except Exception:
        # Log only the user id — NEVER the token, email address, or full URL.
        logger.warning("email send failed for user id=%s (template=%r)", user_id, template)


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, int] = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Yield a `UserManager` bound to the request-scoped user-db."""
    yield UserManager(user_db)
