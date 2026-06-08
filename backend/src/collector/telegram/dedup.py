"""Pure cross-tenant dedup of source references (AC5, ADR-002 §3).

A channel watched by N tenants is read ONCE: we build the UNION of unique
`SourceRef`. Handles are normalized first so `@Channel`, `@channel` and
`https://t.me/channel` collapse to a single ref. Pure + order-preserving so the
read order is deterministic and the function is trivially testable.
"""

from collector.base import SourceKind, SourceRef

_TME_PREFIXES = ("https://t.me/", "http://t.me/", "t.me/")


def normalize_handle(handle: str, kind: SourceKind) -> str:
    """Normalize a handle to its canonical form for dedup/comparison.

    Telegram: strip a `t.me/` URL prefix, ensure a single leading '@', lowercase
    (Telegram usernames are case-insensitive). Other kinds: trimmed as-is.
    """
    value = handle.strip()
    if kind is SourceKind.TELEGRAM:
        for prefix in _TME_PREFIXES:
            if value.lower().startswith(prefix):
                value = value[len(prefix) :]
                break
        value = value.lstrip("@")
        return f"@{value.lower()}"
    return value


def unique_refs(refs: list[SourceRef]) -> list[SourceRef]:
    """Return the order-preserving UNION of unique, normalized `SourceRef`s."""
    seen: set[tuple[SourceKind, str]] = set()
    result: list[SourceRef] = []
    for ref in refs:
        canonical = SourceRef(kind=ref.kind, handle=normalize_handle(ref.handle, ref.kind))
        key = (canonical.kind, canonical.handle)
        if key in seen:
            continue
        seen.add(key)
        result.append(canonical)
    return result
