"""Collector package — source abstraction port + model (ADR-001).

Public surface: the platform-independent contracts (`SourceKind`, `SourceRef`,
`PostMetrics`, `RawPost`, `SourceCollector`) and the in-code `registry`. The
Telegram implementation lives under `collector.telegram` and is imported lazily by
the registry, so importing this package never requires telethon.
"""

from collector import registry
from collector.base import (
    PostMetrics,
    RawPost,
    SourceCollector,
    SourceKind,
    SourceRef,
)

__all__ = [
    "PostMetrics",
    "RawPost",
    "SourceCollector",
    "SourceKind",
    "SourceRef",
    "registry",
]
