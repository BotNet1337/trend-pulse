"""Channel-reference helpers: map `ChannelRef` to storage params + validate (seam).

`validate_ref` is the seam for the real collector check (task-005). A collector
`registry` does not exist yet, so the optional import is guarded: if a registry is
present and knows the `kind`, delegate to it; otherwise fall back to format-only
validation (stub-tolerant — do NOT fail just because the collector is absent).

We never import collector internals — only an optional public `registry` surface.
"""

from typing import Protocol, runtime_checkable

from api.watchlist.schemas import TELEGRAM_HANDLE_PATTERN, ChannelRef
from storage.models.channels import SourceKind


@runtime_checkable
class _CollectorRegistry(Protocol):
    """Minimal public surface a future collector registry is expected to expose."""

    def validate_ref(self, *, kind: SourceKind, handle: str) -> bool: ...


def _load_registry() -> _CollectorRegistry | None:
    """Return the collector registry if it exists, else None (task-005 not shipped)."""
    try:
        from collector import registry  # type: ignore[import-not-found, unused-ignore]
    except ImportError:
        return None
    if isinstance(registry, _CollectorRegistry):
        return registry
    return None


def _format_ok(ref: ChannelRef) -> bool:
    """Format-only check (current default). Telegram handle regex; others pass."""
    if ref.kind is SourceKind.TELEGRAM:
        return bool(TELEGRAM_HANDLE_PATTERN.match(ref.handle))
    return True


def validate_ref(ref: ChannelRef) -> bool:
    """True if the reference is valid. Delegates to the collector when available."""
    registry = _load_registry()
    if registry is not None:
        return registry.validate_ref(kind=ref.kind, handle=ref.handle)
    return _format_ok(ref)


def to_storage_params(ref: ChannelRef) -> tuple[SourceKind, str]:
    """Map a `ChannelRef` to `ChannelRepository.get_or_create` params (kind, handle)."""
    return ref.kind, ref.handle
