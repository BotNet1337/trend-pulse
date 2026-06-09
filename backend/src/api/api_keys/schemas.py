"""Pydantic boundary schemas for the API-keys feature (TASK-028).

`ApiKeyCreated` is the ONLY schema that carries the plaintext `key` field.
It is returned exactly once (POST /api-keys response). All subsequent reads
use `ApiKeyRead` which omits key/key_hash (no plaintext exposure after creation).

`extra="forbid"` rejects unknown fields (CONVENTIONS: validate at boundary).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from api.api_keys.constants import _NAME_MAX_LEN, _NAME_MIN_LEN


class ApiKeyCreate(BaseModel):
    """Request body for POST /api-keys — only the human-readable name."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=_NAME_MIN_LEN,
        max_length=_NAME_MAX_LEN,
        description="Human-readable label for the key (e.g. 'prod-integration').",
    )


class ApiKeyCreated(BaseModel):
    """Response for POST /api-keys — includes the plaintext key EXACTLY ONCE.

    The `key` field is the plaintext. After this response the plaintext is gone;
    it is not stored in the DB. The user must copy it immediately.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    prefix: str
    # Plaintext key — shown once on creation, never again.
    key: str
    created_at: datetime


class ApiKeyRead(BaseModel):
    """Read-only view of an API key (list / detail) — NO plaintext or key_hash.

    Exposes only the prefix (for recognition), name, and timestamps. Safe to
    return in list responses without exposing sensitive material.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
