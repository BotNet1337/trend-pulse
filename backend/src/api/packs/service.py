"""Packs domain service (TASK-038).

subscribe():   bulk-insert watchlist rows for a pack in a single transaction;
               skips rows that conflict on unique (user_id, channel_id, topic)
               using per-row savepoints so a single conflict does not roll back
               the entire batch; idempotent.
unsubscribe(): delete all watchlist rows by (user_id, pack_slug); 0 rows = OK.

Design decisions (from task doc §Discussion):
- Subscribing the SAME pack again must NOT fail the limit check: we check whether
  any row with this pack_slug already exists BEFORE calling assert_within_limit.
- Pack rows use `pack_slug` as the de-facto subscription marker; no separate table.
- Single outer transaction per subscribe call; skip-conflicts use nested savepoints
  so they do not roll back previously-created rows in the batch.
- No sync on pack updates: unsubscribe + subscribe picks up new channel list.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import get_tenant_user_id
from api.packs.data import PackDef
from api.packs.schemas import SubscribeResult, UnsubscribeResult
from billing.limits import assert_within_limit
from billing.plans import Resource
from storage.models.channels import Channel, SourceKind
from storage.models.users import User
from storage.models.watchlists import Watchlist
from storage.repositories import ChannelRepository


def _get_or_create_channel(session: Session, handle: str, kind: SourceKind) -> Channel:
    """Resolve a pack channel handle to the global Channel row (dedup).

    Mirrors watchlist service._resolve_channel but without format validation —
    pack handles are curated and verified at PR time, not at runtime.
    """
    return ChannelRepository().get_or_create(session, source_kind=kind, handle=handle)


def _is_already_subscribed(session: Session, user_id: int, pack_slug: str) -> bool:
    """Return True if the user already has at least one watchlist row for this pack."""
    stmt = (
        select(Watchlist.id)
        .where(Watchlist.user_id == user_id)
        .where(Watchlist.pack_slug == pack_slug)
        .limit(1)
    )
    return session.scalars(stmt).first() is not None


def subscribe(
    session: Session,
    *,
    user: User,
    pack: PackDef,
) -> SubscribeResult:
    """Subscribe the user to a pack — bulk-insert watchlist rows in one transaction.

    Idempotency: if the pack is already subscribed (any row with this pack_slug),
    skip the limit check and only insert rows that are still missing (created=0 if
    all already exist). Each row insert uses a savepoint so a unique conflict
    does not roll back previously-created rows in the same batch.

    The full batch is committed or rolled back atomically by the caller's session
    context (get_db_session commit-on-yield, rollback-on-error).
    """
    # Derive tenant scope via the single canonical function (ADR-002, Finding 4).
    user_id = get_tenant_user_id(user)
    pack_slug = pack.slug

    # Idempotency: re-subscribing the same pack must not consume another PACKS slot.
    already_subscribed = _is_already_subscribed(session, user_id, pack_slug)
    if not already_subscribed:
        # New pack subscription — enforce the PACKS plan limit (ADR-003).
        assert_within_limit(session, user, Resource.PACKS)

    created = 0
    skipped = 0

    for pack_channel in pack.channels:
        # Open the savepoint BEFORE resolving the channel so that an IntegrityError
        # on the channel's uq_channels_source_kind_handle (raised by a concurrent
        # subscribe that created the same channel between our SELECT-miss and our
        # INSERT) is caught here and rolled back to this savepoint rather than
        # poisoning the whole transaction.
        savepoint = session.begin_nested()
        try:
            channel = _get_or_create_channel(session, pack_channel.handle, pack_channel.kind)
            row = Watchlist(
                user_id=user_id,
                channel_id=channel.id,
                topic=pack.topic,
                threshold=float(pack.default_score_threshold),
                min_channels=pack.default_min_channels,
                lang=pack.default_notification_lang,
                pack_slug=pack_slug,
            )
            session.add(row)
            session.flush()
            savepoint.commit()
            created += 1
        except IntegrityError:
            # Two possible conflicts:
            # 1. uq_channels_source_kind_handle — concurrent channel creation race.
            #    After rollback the channel row now exists; we could re-SELECT it but
            #    the watchlist insert would also fail (same channel_id already watched),
            #    so we simply skip — outcome is correct (channel already tracked).
            # 2. unique (user_id, channel_id, topic) on Watchlist — already watched
            #    manually or via a prior pack subscribe overlap.
            # In both cases: roll back ONLY this savepoint, count as skipped.
            savepoint.rollback()
            skipped += 1

    return SubscribeResult(created=created, skipped=skipped)


def unsubscribe(
    session: Session,
    *,
    user_id: int,
    pack_slug: str,
) -> UnsubscribeResult:
    """Delete all watchlist rows for (user_id, pack_slug).

    Decision (task doc §Discussion): slug not in catalog = 404 (handled in router);
    valid slug with 0 subscription rows for this user = 200 with deleted=0 (idempotent).
    Manual watchlists (pack_slug IS NULL) are NEVER touched.
    """
    stmt = (
        select(Watchlist)
        .where(Watchlist.user_id == user_id)
        .where(Watchlist.pack_slug == pack_slug)
    )
    rows = list(session.scalars(stmt).all())
    deleted = len(rows)
    for row in rows:
        session.delete(row)
    if deleted > 0:
        session.flush()
    return UnsubscribeResult(deleted=deleted)


__all__ = ["subscribe", "unsubscribe"]
