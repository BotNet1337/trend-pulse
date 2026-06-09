"""Pydantic boundary models for delivery-config read/patch (TASK-017).

DeliveryConfigRead — response shape; telegram_bot_token is NEVER returned as the
full secret. Instead we return a `telegram_bot_token_masked` string showing only
the last 4 characters (e.g. ``***h1``) so the UI can confirm «token is set»
without leaking the full value. If no token is set the field is None.

DeliveryConfigUpdate — PATCH request body; all fields optional (partial update).
`webhook_url` is validated via the SSRF guard (task-009 `validate_webhook_url`)
inside the router before persisting. Feature-gate (Pro+ only) is enforced by
`assert_within_limit` / `PlanLimitExceeded` → 403 at the router level.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Number of trailing characters shown in the masked token.
_MASKED_SUFFIX_LEN = 4
# Mask prefix constant — no magic string inline.
_MASK_PREFIX = "***"


def mask_bot_token(token: str | None) -> str | None:
    """Return a masked representation of the bot token (last 4 chars only).

    If the token is None or too short to mask safely, return None so the UI
    knows no token is configured. The full token is NEVER returned.
    """
    if not token:
        return None
    if len(token) <= _MASKED_SUFFIX_LEN:
        # Token too short to mask without exposing it — treat as «set but hidden».
        return _MASK_PREFIX
    return f"{_MASK_PREFIX}{token[-_MASKED_SUFFIX_LEN:]}"


class DeliveryConfigRead(BaseModel):
    """Read projection of the user's delivery configuration.

    `telegram_bot_token_masked` is None if not set, or a masked string
    (e.g. ``***gh1``) if set. The full token is NEVER included.
    """

    model_config = ConfigDict(extra="forbid")

    telegram_bot_token_masked: str | None
    telegram_chat_id: str | None
    webhook_url: str | None


class DeliveryConfigUpdate(BaseModel):
    """Partial-update body for PATCH /users/me/delivery-config.

    All fields are optional; only provided fields are updated.
    `webhook_url` must pass the server-side SSRF guard (task-009) and the
    Pro+ feature-gate check before persisting.
    """

    model_config = ConfigDict(extra="forbid")

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    webhook_url: str | None = None
