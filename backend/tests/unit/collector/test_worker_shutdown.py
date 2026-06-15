"""TASK-106 — graceful collector disconnect on worker-process shutdown.

The `worker_process_shutdown` handler must gracefully `aclose()` every cached collector
(clean MTProto disconnect → fewer AuthKeyDuplicated when the next child reconnects the same
session) and then close the per-process event loop — best-effort, never raising out of shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import pytest

from collector import registry, tasks
from collector.base import RawPost, SourceKind, SourceRef


class _FakeCollector:
    """Minimal SourceCollector with a recording (optionally failing) aclose."""

    def __init__(self, kind: SourceKind, *, fail: bool = False) -> None:
        self.kind = kind
        self.closed = False
        self._fail = fail

    async def validate_ref(self, ref: SourceRef) -> bool:
        return True

    def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        raise NotImplementedError

    async def aclose(self) -> None:
        if self._fail:
            raise RuntimeError("disconnect boom")
        self.closed = True


def test_shutdown_closes_cached_collectors_and_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(tasks, "_loop", loop)
    fc = _FakeCollector(SourceKind.TELEGRAM)
    monkeypatch.setattr(registry, "cached_collectors", lambda: [fc])

    tasks._close_collectors_on_shutdown()

    assert fc.closed is True  # aclose awaited
    assert loop.is_closed()  # loop closed after


def test_shutdown_tolerates_aclose_error(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(tasks, "_loop", loop)
    fc = _FakeCollector(SourceKind.TELEGRAM, fail=True)
    monkeypatch.setattr(registry, "cached_collectors", lambda: [fc])

    tasks._close_collectors_on_shutdown()  # must NOT raise despite aclose error

    assert loop.is_closed()  # still proceeds to close the loop


def test_shutdown_noop_when_no_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_loop", None)
    consulted: list[int] = []
    monkeypatch.setattr(registry, "cached_collectors", lambda: (consulted.append(1), [])[1])

    tasks._close_collectors_on_shutdown()  # no loop → clean no-op

    assert consulted == []  # never even enumerates collectors when there's no loop
