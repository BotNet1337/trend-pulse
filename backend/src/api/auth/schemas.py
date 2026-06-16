"""Pydantic schemas at the API boundary for the fastapi-users routers.

Thin subclasses of the library base schemas, parametrized for the integer user id
(`schemas.BaseUser[int]`). fastapi-users validates request/response bodies against
these, so we never trust unvalidated user input (CONVENTIONS).
"""

from typing import cast

from fastapi_users import schemas
from pydantic import Field

# Referral code max length (must match _REF_CODE_MAX in storage/models/users.py).
_REF_CODE_MAX = 32

# Google reCAPTCHA v2 tokens are several hundred to 1000+ chars; cap generously to
# bound the request body without rejecting legitimate tokens.
_RECAPTCHA_TOKEN_MAX = 4096


class UserRead(schemas.BaseUser[int]):
    """Public user representation returned by register / users routes."""


class UserCreate(schemas.BaseUserCreate):
    """Registration payload (email + password + optional referrer_code).

    referrer_code: optional referral code supplied by the inviting user.  Passed
    at registration to bind referred_by on the new user.  Invalid/unknown codes
    are silently ignored (registration always succeeds — INVARIANT: referral
    errors must not block register).  Max length validated here.

    CRITICAL: the field is named 'referrer_code' (NOT 'ref_code') to avoid
    colliding with the User ORM column users.ref_code.  fastapi-users
    create_update_dict() passes the dict straight into User(**kwargs); if the
    field were named 'ref_code' it would overwrite the new user's own ref_code
    with the referrer's code string → UniqueViolation / pollution (TASK-046 G2).

    create_update_dict() is overridden here to exclude 'referrer_code' from the
    INSERT dict entirely — the referral binding is handled separately by
    UserManager._bind_referral() via the raw request body.
    """

    referrer_code: str | None = Field(default=None, max_length=_REF_CODE_MAX)

    # Google reCAPTCHA v2 client token (sign-up bot protection). Optional in the
    # schema because local dev has reCAPTCHA OFF and sends no token; in prod the
    # UserManager.create() override rejects sign-ups with a missing/invalid token
    # (see api.auth.captcha). Like referrer_code, this is NOT a User column and is
    # excluded from the INSERT dict below.
    recaptcha_token: str | None = Field(default=None, max_length=_RECAPTCHA_TOKEN_MAX)

    def create_update_dict(self) -> dict[str, object]:
        """Exclude referrer_code + recaptcha_token from the user INSERT dict.

        fastapi-users passes this dict to User(**create_dict) via the SQLAlchemy
        adapter.  User has no 'referrer_code'/'recaptcha_token' column, so passing
        either would raise a TypeError (unexpected keyword argument).  Excluding
        them here keeps the adapter clean and prevents column collisions.
        """
        d: dict[str, object] = cast(dict[str, object], super().create_update_dict())
        d.pop("referrer_code", None)
        d.pop("recaptcha_token", None)
        return d


class UserUpdate(schemas.BaseUserUpdate):
    """Self-service update payload."""
