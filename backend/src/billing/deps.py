"""Billing dependencies: the configured gateway + a request DB session.

The NOWPayments gateway is built from settings (API key / IPN secret from
sensitive.env, ADR-005). Billing endpoints error cleanly if the secret is unset
rather than failing at startup, so the app boots without billing configured.
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from billing.gateway.nowpayments import NowPaymentsGateway
from config import Settings, get_settings
from storage.database import get_session


class BillingNotConfiguredError(Exception):
    """A billing endpoint was hit but NOWPayments credentials are unset."""


def get_gateway() -> NowPaymentsGateway:
    """Build the NOWPayments gateway from settings (raises if unconfigured)."""
    settings: Settings = get_settings()
    if not settings.nowpayments_api_key or not settings.nowpayments_ipn_secret:
        raise BillingNotConfiguredError("NOWPayments credentials are not configured")
    return NowPaymentsGateway(
        api_key=settings.nowpayments_api_key,
        ipn_secret=settings.nowpayments_ipn_secret,
        base_url=settings.nowpayments_base_url,
    )


def get_ipn_gateway() -> NowPaymentsGateway:
    """Gateway for the IPN route — needs only the IPN secret (no API key)."""
    settings: Settings = get_settings()
    if not settings.nowpayments_ipn_secret:
        raise BillingNotConfiguredError("NOWPayments IPN secret is not configured")
    return NowPaymentsGateway(
        api_key=settings.nowpayments_api_key,
        ipn_secret=settings.nowpayments_ipn_secret,
        base_url=settings.nowpayments_base_url,
    )


def get_db_session() -> Iterator[Session]:
    """Yield a committing sync session for one request (see `storage.get_session`)."""
    with get_session() as session:
        yield session
