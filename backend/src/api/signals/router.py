"""Public signals API router (T7).

GET /signals?limit=<int> — recent actionable signals (SignalPayload-shaped), strongest
first. Auth required (any plan). Aggregate-only (compliance §7). The data SOURCE is an
injectable dependency (`get_signal_source`) so the route is unit-testable without a DB
and so the DB-backed source can be wired in later (T6b) via dependency override.
"""

from fastapi import APIRouter, Depends, Query

from api.deps import current_user
from api.signals import service
from api.signals.schemas import SignalsResponse
from api.signals.service import EmptySignalSource, SignalSource
from storage.models.users import User

router = APIRouter(prefix="/signals", tags=["signals"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def get_signal_source() -> SignalSource:
    """Provide the signals data source. Defaults to empty; overridden when wired (T6b)."""
    return EmptySignalSource()


@router.get("", response_model=SignalsResponse)
def list_signals(
    limit: int = Query(
        default=_DEFAULT_LIMIT,
        ge=1,
        le=_MAX_LIMIT,
        description=f"Max signals to return (1..{_MAX_LIMIT}, default {_DEFAULT_LIMIT}).",
    ),
    source: SignalSource = Depends(get_signal_source),
    user: User = Depends(current_user),
) -> SignalsResponse:
    """Return recent actionable signals (independence-weighted, noise-excluded)."""
    return SignalsResponse(signals=service.recent_signals(source, limit))
