"""GET/PATCH /users/me/delivery-config — delivery configuration for the current user.

Read and update the authenticated user's Telegram bot token, chat ID, and webhook
URL. Security constraints (TASK-017 invariants):

- `telegram_bot_token` is write-only from the client's perspective: GET returns only
  a masked representation (last 4 chars); the full token is NEVER returned.
- `webhook_url` requires the Pro+ plan (feature-gate via `assert_within_limit`
  with `Resource.WEBHOOK_DELIVERY` → `PlanLimitExceeded(code=403)` on Free plan).
- `webhook_url` is validated against the SSRF guard from task-009
  (`validate_webhook_url`) before persisting; a private/localhost/non-https URL
  raises `WebhookValidationError` → 422 Unprocessable Entity.
- Telegram bot token and chat_id are available on all plans (no feature-gate).
- All operations are tenant-scoped: only the current user's data is read/written.

Follows the router pattern from `api/alerts/router.py` and `api/watchlist/router.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from alerts.errors import WebhookValidationError
from alerts.security import validate_webhook_url
from api.account.schemas import DeliveryConfigRead, DeliveryConfigUpdate, mask_bot_token
from api.deps import current_user
from api.watchlist.deps import get_db_session
from billing import Resource, assert_within_limit
from storage.models.users import User

router = APIRouter(prefix="/users/me", tags=["delivery-config"])

# Human-readable error messages — no magic strings at call sites.
_WEBHOOK_SSRF_ERROR = "webhook_url is invalid or resolves to a non-public address"


@router.get("/delivery-config", response_model=DeliveryConfigRead)
def get_delivery_config(
    user: User = Depends(current_user),
) -> DeliveryConfigRead:
    """Return the authenticated user's delivery configuration (token masked).

    `telegram_bot_token` is never returned as the full value — only a masked
    representation showing the last 4 characters (or None if not set).
    Tenant-scoped: reads only `current_user` data.
    """
    return DeliveryConfigRead(
        telegram_bot_token_masked=mask_bot_token(user.telegram_bot_token),
        telegram_chat_id=user.telegram_chat_id,
        webhook_url=user.webhook_url,
    )


@router.patch("/delivery-config", response_model=DeliveryConfigRead)
def patch_delivery_config(
    data: DeliveryConfigUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> DeliveryConfigRead:
    """Partial-update the authenticated user's delivery configuration.

    - `webhook_url`: requires Pro+ plan (feature-gate → 403 on Free);
      SSRF-validated via task-009 guard (private/localhost/non-https → 422).
    - `telegram_bot_token`/`telegram_chat_id`: available on all plans.
    - Only provided fields are updated (partial PATCH semantics).
    - Returns the updated config with the bot token masked.
    """
    # Reload user from the sync session for accurate plan/mutation.
    # current_user is resolved via an async session; we need the sync session
    # for (a) accurate plan gating and (b) in-transaction mutation + commit.
    # .unique() required: User has lazy="joined" on oauth_accounts collection.
    from sqlalchemy import select

    from storage.models.users import User as UserModel

    db_user = session.scalars(select(UserModel).where(UserModel.id == user.id)).unique().one()

    # Feature-gate: webhook_url requires Pro+ plan (FEATURE_RESOURCES check).
    # assert_within_limit raises PlanLimitExceeded(code=403) for boolean features
    # that are False on the current plan. The app-level exception handler in
    # main.py maps PlanLimitExceeded → its .code (403) automatically.
    # Use db_user (sync-session loaded) so the plan reflects any in-flight
    # changes (e.g. IPN upgrades visible to the sync pool).
    if data.webhook_url is not None:
        assert_within_limit(session, db_user, Resource.WEBHOOK_DELIVERY)

    # SSRF guard: validate the webhook URL using the task-009 implementation.
    # validate_webhook_url raises WebhookValidationError if the URL is unsafe.
    if data.webhook_url is not None:
        try:
            validate_webhook_url(data.webhook_url)
        except WebhookValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_WEBHOOK_SSRF_ERROR,
            ) from exc

    # Partial update: only set fields that were explicitly provided in the request.
    if data.telegram_bot_token is not None:
        db_user.telegram_bot_token = data.telegram_bot_token
    if data.telegram_chat_id is not None:
        db_user.telegram_chat_id = data.telegram_chat_id
    if data.webhook_url is not None:
        db_user.webhook_url = data.webhook_url

    session.commit()
    session.refresh(db_user)

    return DeliveryConfigRead(
        telegram_bot_token_masked=mask_bot_token(db_user.telegram_bot_token),
        telegram_chat_id=db_user.telegram_chat_id,
        webhook_url=db_user.webhook_url,
    )
