"""Renewal notification sender (task-027) — email-first channel.

Design decision (task-027):
  Channel: EMAIL-FIRST.  `user.email` is always present (fastapi-users mandate).
  task-025 SMTP infra is reliable and already in use for auth emails.
  Telegram requires `chat_id` which most users have not configured → follow-up task.

  This module calls `send_templated_email` from `notifications.email` (task-025),
  which renders via the templates service and delivers via SMTP.

Security / PII:
  - Logs carry only `subscription_id` and `user_id`, NEVER email addresses.
  - `renewUrl` is constructed from `settings.frontend_base_url` (non-secret).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from billing.constants import _BILLING_PATH, _RENEWAL_SUBJECT, _RENEWAL_TEMPLATE
from config import get_settings
from notifications.email import send_templated_email

if TYPE_CHECKING:
    from storage.models.subscriptions import Subscription
    from storage.models.users import User

logger = logging.getLogger(__name__)


def send_renewal_reminder(
    *,
    subscription: Subscription,
    user: User,
    window_days: int,
) -> None:
    """Send a renewal-reminder email to the subscription owner.

    Args:
        subscription: The expiring :class:`~storage.models.subscriptions.Subscription`.
        user:         The owning :class:`~storage.models.users.User`; the email
                      is read from ``user.email``.
        window_days:  The reminder window in days (1, 3, or 7) — used in the
                      email copy to communicate urgency.

    Raises:
        EmailRenderError: If the templates service is unreachable or returns
            a non-2xx response.
        EmailSendError: If the SMTP server rejects or fails the send.

    Note:
        Errors are intentionally **not** caught here; the caller
        (``billing.tasks._check_expiring_subscriptions``) catches and logs them
        so that a single-subscription failure does not abort the whole sweep.
        The idempotency flag is set by the caller ONLY on success.
    """
    cfg = get_settings()
    renew_url: str = f"{cfg.frontend_base_url}{_BILLING_PATH}"

    props: dict[str, object] = {
        "userName": user.email,
        "planName": subscription.plan,
        "daysLeft": window_days,
        "renewUrl": renew_url,
    }

    logger.info(
        "sending renewal reminder subscription_id=%s user_id=%s window_days=%s",
        subscription.id,
        user.id,
        window_days,
    )

    send_templated_email(
        to=user.email,
        template=_RENEWAL_TEMPLATE,
        subject=_RENEWAL_SUBJECT,
        props=props,
    )

    logger.info(
        "renewal reminder sent subscription_id=%s user_id=%s window_days=%s",
        subscription.id,
        user.id,
        window_days,
    )
