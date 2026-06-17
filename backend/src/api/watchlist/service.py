"""Watchlist domain service — tenant-scoped CRUD over the repository (ADR-002).

Every operation takes `user_id` mandatorily; CRUD-by-id filters `(id, user_id)`,
so a missing row and another tenant's row are indistinguishable (return None ->
router 404, no existence leak). create() runs the `validate_ref` and
`check_watchlist_limits` seams before inserting.

User decision: one row = one watchlist (single channel, numeric id); see
`schemas.py`. `threshold` (model, Float) is fed from `score_threshold` (API, int).
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.watchlist.exceptions import DuplicateWatchlistError, RefValidationError
from api.watchlist.limits import check_watchlist_limits
from api.watchlist.refs import to_storage_params, validate_ref
from api.watchlist.schemas import (
    AlertConfig,
    ChannelRef,
    WatchlistCreate,
    WatchlistRead,
    WatchlistSignal,
    WatchlistUpdate,
)
from storage.models.channels import Channel, SourceKind
from storage.models.users import User
from storage.models.watchlists import Watchlist
from storage.repositories import ChannelRepository, WatchlistRepository
from storage.repositories.signal_repo import (
    EMPTY_SIGNAL,
    WatchlistSignalData,
    aggregate_for_user,
)


def _to_signal(data: WatchlistSignalData) -> WatchlistSignal:
    """Map the repo's aggregation DTO onto the API signal model (TASK-096)."""
    return WatchlistSignal(
        live_velocity=data.live_velocity,
        live_score=data.live_score,
        sparkline_24h=list(data.sparkline_24h),
        last_alert_at=data.last_alert_at,
        effective_sources=data.effective_sources,
    )


def _to_read(
    row: Watchlist, channel: Channel, signal: WatchlistSignalData = EMPTY_SIGNAL
) -> WatchlistRead:
    """Build the response model from a persisted row + its (global) channel.

    `signal` (TASK-096) defaults to the empty signal so the CRUD write paths
    (create / update) return a graceful-empty signal without an extra query — the
    desk re-fetches the list (which carries the aggregated signal) after a mutation.
    """
    return WatchlistRead(
        id=row.id,
        user_id=row.user_id,
        topic=row.topic,
        channel=ChannelRef(handle=channel.handle, kind=channel.source_kind),
        alert_config=AlertConfig(
            score_threshold=int(row.threshold),
            min_channels=row.min_channels,
            notification_lang=row.lang,
        ),
        signal=_to_signal(signal),
    )


def _resolve_channel(session: Session, ref: ChannelRef) -> Channel:
    """Validate the ref (seam) and resolve it to a global channel (dedup)."""
    if not validate_ref(ref):
        raise RefValidationError(f"invalid channel reference: {ref.handle}")
    kind, handle = to_storage_params(ref)
    return ChannelRepository().get_or_create(session, source_kind=kind, handle=handle)


def _channel_for(session: Session, channel_id: int) -> Channel:
    """Load the global channel row referenced by a watchlist (always present)."""
    channel = session.get(Channel, channel_id)
    if channel is None:  # pragma: no cover - FK guarantees presence
        raise RefValidationError(f"channel {channel_id} not found")
    return channel


def create(session: Session, *, user: User, data: WatchlistCreate) -> WatchlistRead:
    """Create one watchlist for the user. Seams: limits (402), validate_ref (422).

    The per-plan channel cap is enforced via the single billing entry (ADR-003).
    """
    user_id = user.id
    repo = WatchlistRepository()
    check_watchlist_limits(session, user)

    channel = _resolve_channel(session, data.channel)
    row = Watchlist(
        user_id=user_id,
        channel_id=channel.id,
        topic=data.topic,
        threshold=float(data.alert_config.score_threshold),
        min_channels=data.alert_config.min_channels,
        lang=data.alert_config.notification_lang,
    )
    try:
        repo.create(session, row)
    except IntegrityError as exc:
        # Unique (user_id, channel_id, topic): same channel+topic already watched.
        session.rollback()
        raise DuplicateWatchlistError(
            "a watchlist for this channel and topic already exists"
        ) from exc
    return _to_read(row, channel)


def list_for_user(session: Session, *, user_id: int) -> list[WatchlistRead]:
    """Return every watchlist owned by the user, each with its live signal (TASK-096).

    The live signal for the whole list is aggregated in one batched call keyed by
    `channel_id` (no N+1, INV3); each row is then mapped onto its channel's signal.
    """
    repo = WatchlistRepository()
    rows = repo.list(session, user_id=user_id)
    signals = aggregate_for_user(
        session, user_id=user_id, channel_ids=[row.channel_id for row in rows]
    )
    return [
        _to_read(
            row,
            _channel_for(session, row.channel_id),
            signals.get(row.channel_id, EMPTY_SIGNAL),
        )
        for row in rows
    ]


def get(session: Session, *, user_id: int, watchlist_id: int) -> WatchlistRead | None:
    """Return one owned watchlist with its live signal, or None if missing (-> 404)."""
    row = WatchlistRepository().get_by_id(session, user_id=user_id, entity_id=watchlist_id)
    if row is None:
        return None
    signals = aggregate_for_user(session, user_id=user_id, channel_ids=[row.channel_id])
    return _to_read(
        row,
        _channel_for(session, row.channel_id),
        signals.get(row.channel_id, EMPTY_SIGNAL),
    )


def update(
    session: Session, *, user_id: int, watchlist_id: int, data: WatchlistUpdate
) -> WatchlistRead | None:
    """Partial update of an owned watchlist; None if missing / other tenant's."""
    repo = WatchlistRepository()
    row = repo.get_by_id(session, user_id=user_id, entity_id=watchlist_id)
    if row is None:
        return None

    fields = data.model_dump(exclude_unset=True)
    channel: Channel = _channel_for(session, row.channel_id)

    if "topic" in fields and data.topic is not None:
        row.topic = data.topic
    if "channel" in fields and data.channel is not None:
        channel = _resolve_channel(session, data.channel)
        row.channel_id = channel.id
    if "alert_config" in fields and data.alert_config is not None:
        row.threshold = float(data.alert_config.score_threshold)
        # AC6 (TASK-043): manual threshold update re-snapshots the floor so the
        # adapt loop uses the user's new intent value as the base.  The previous
        # floor (whether NULL or an old snapshot) is discarded — last-write-wins.
        row.threshold_floor = row.threshold
        row.min_channels = data.alert_config.min_channels
        row.lang = data.alert_config.notification_lang

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateWatchlistError(
            "a watchlist for this channel and topic already exists"
        ) from exc
    return _to_read(row, channel)


def delete(session: Session, *, user_id: int, watchlist_id: int) -> bool:
    """Delete an owned watchlist. Returns False if missing / other tenant's."""
    repo = WatchlistRepository()
    row = repo.get_by_id(session, user_id=user_id, entity_id=watchlist_id)
    if row is None:
        return False
    repo.delete(session, user_id=user_id, entity=row)
    return True


__all__ = [
    "SourceKind",
    "create",
    "delete",
    "get",
    "list_for_user",
    "update",
]
