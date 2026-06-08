"""Unit tests for the watchlist service seams + tenant-scope (mocked repo, no DB)."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from api.watchlist import service
from api.watchlist.exceptions import LimitExceededError, RefValidationError
from api.watchlist.refs import validate_ref
from api.watchlist.schemas import (
    AlertConfig,
    ChannelRef,
    WatchlistCreate,
)
from storage.models.users import User

# Free-plan channel cap (overview §6) — used to size the mocked usage in tests.
_FREE_CHANNELS_CAP = 5


def _user(user_id: int = 1, plan: str = "free") -> User:
    user = User()
    user.id = user_id
    user.plan = plan
    return user


def _create_data(handle: str = "@chan_name") -> WatchlistCreate:
    return WatchlistCreate(
        topic="ai",
        channel=ChannelRef(handle=handle),
        alert_config=AlertConfig(score_threshold=50, min_channels=2, notification_lang="en"),
    )


# --- limits seam (now bridged to billing.assert_within_limit, ADR-003) ---


def test_check_limits_allows_below_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.watchlist import limits

    # Mock the single billing entry so this stays DB-free; below-cap → no raise.
    monkeypatch.setattr(limits, "assert_within_limit", lambda session, user, resource: None)
    limits.check_watchlist_limits(MagicMock(), _user())


def test_check_limits_raises_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.watchlist import limits
    from billing import PlanLimitExceeded

    def _raise(session: Any, user: Any, resource: Any) -> None:
        raise PlanLimitExceeded("channels limit reached", code=402)

    monkeypatch.setattr(limits, "assert_within_limit", _raise)
    with pytest.raises(LimitExceededError):
        limits.check_watchlist_limits(MagicMock(), _user())


# --- validate_ref seam (stub-tolerant: format-only when no collector) ---


def test_validate_ref_format_only_accepts_valid_telegram() -> None:
    assert validate_ref(ChannelRef(handle="@valid_handle")) is True


# --- tenant scope: another tenant's id is indistinguishable from missing ---


def test_get_returns_none_for_other_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.get_by_id.return_value = None  # row not owned by user -> repo filters it out
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)

    result = service.get(MagicMock(), user_id=1, watchlist_id=999)
    assert result is None
    repo.get_by_id.assert_called_once_with(
        repo.get_by_id.call_args.args[0], user_id=1, entity_id=999
    )


def test_delete_returns_false_for_other_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.get_by_id.return_value = None
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)

    assert service.delete(MagicMock(), user_id=1, watchlist_id=999) is False
    repo.delete.assert_not_called()


def test_update_returns_none_for_other_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.get_by_id.return_value = None
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)

    from api.watchlist.schemas import WatchlistUpdate

    result = service.update(
        MagicMock(), user_id=1, watchlist_id=999, data=WatchlistUpdate(topic="x")
    )
    assert result is None


# --- create: enforces the limit before touching channels ---


def test_create_raises_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.list.return_value = [object()] * _FREE_CHANNELS_CAP
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)
    channel_repo = MagicMock()
    monkeypatch.setattr(service, "ChannelRepository", lambda: channel_repo)

    def _raise(session: Any, user: Any) -> None:
        raise LimitExceededError("channels limit reached")

    monkeypatch.setattr(service, "check_watchlist_limits", _raise)

    with pytest.raises(LimitExceededError):
        service.create(MagicMock(), user=_user(), data=_create_data())
    channel_repo.get_or_create.assert_not_called()


def test_create_raises_ref_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.list.return_value = []
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)
    monkeypatch.setattr(service, "check_watchlist_limits", lambda session, user: None)
    # Force the seam to reject the ref regardless of format.
    monkeypatch.setattr(service, "validate_ref", lambda ref: False)
    channel_repo = MagicMock()
    monkeypatch.setattr(service, "ChannelRepository", lambda: channel_repo)

    with pytest.raises(RefValidationError):
        service.create(MagicMock(), user=_user(), data=_create_data())
    channel_repo.get_or_create.assert_not_called()


def test_create_inserts_and_maps_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.list.return_value = []
    monkeypatch.setattr(service, "check_watchlist_limits", lambda session, user: None)

    def _create(session: Any, entity: Any) -> Any:
        entity.id = 42  # simulate flush assigning a PK
        return entity

    repo.create.side_effect = _create
    monkeypatch.setattr(service, "WatchlistRepository", lambda: repo)

    from storage.models.channels import Channel, SourceKind

    channel = Channel(source_kind=SourceKind.TELEGRAM, handle="@chan_name")
    channel.id = 7
    channel_repo = MagicMock()
    channel_repo.get_or_create.return_value = channel
    monkeypatch.setattr(service, "ChannelRepository", lambda: channel_repo)

    result = service.create(MagicMock(), user=_user(3), data=_create_data())
    assert result.id == 42
    assert result.user_id == 3
    assert result.channel.handle == "@chan_name"
    assert result.channel.kind is SourceKind.TELEGRAM
    assert result.alert_config.score_threshold == 50
    assert result.alert_config.min_channels == 2
