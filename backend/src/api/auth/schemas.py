"""Pydantic schemas at the API boundary for the fastapi-users routers.

Thin subclasses of the library base schemas, parametrized for the integer user id
(`schemas.BaseUser[int]`). fastapi-users validates request/response bodies against
these, so we never trust unvalidated user input (CONVENTIONS).
"""

from fastapi_users import schemas


class UserRead(schemas.BaseUser[int]):
    """Public user representation returned by register / users routes."""


class UserCreate(schemas.BaseUserCreate):
    """Registration payload (email + password, validated by the library)."""


class UserUpdate(schemas.BaseUserUpdate):
    """Self-service update payload."""
