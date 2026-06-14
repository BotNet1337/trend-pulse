"""Pure cross-tenant dedup of Twitter `SourceRef`s (TASK-031, mirrors telegram/dedup).

An account watched by N tenants is read ONCE: build the UNION of unique refs.
Twitter handles are normalized first (strip a leading '@' / `x.com|twitter.com/`
URL prefix, lowercase — X usernames are case-insensitive) so `@Acme`, `acme` and
`https://x.com/acme` collapse to one ref. Pure + order-preserving (deterministic
read order, trivially testable).
"""

from collector.base import SourceKind, SourceRef

_URL_PREFIXES = (
    "https://x.com/",
    "http://x.com/",
    "x.com/",
    "https://twitter.com/",
    "http://twitter.com/",
    "twitter.com/",
)


def normalize_handle(handle: str) -> str:
    """Normalize a Twitter handle to its canonical bare-username form (lowercased).

    Strips a `@` / `x.com|twitter.com/` URL prefix AND any trailing path or query
    (`/elonmusk/status/123`, `/elonmusk?ref=...`, `/elonmusk/`) so a profile/tweet
    URL collapses to the bare username — never a malformed handle to the API.
    """
    value = handle.strip()
    lowered = value.lower()
    for prefix in _URL_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.lstrip("@")
    # Keep only the username segment (drop /path and ?query).
    value = value.split("/", 1)[0].split("?", 1)[0]
    return value.lower()


def unique_twitter_refs(refs: list[SourceRef]) -> list[SourceRef]:
    """Order-preserving UNION of unique, normalized TWITTER `SourceRef`s.

    Non-Twitter refs are ignored (the Twitter collector only handles TWITTER).
    """
    seen: set[str] = set()
    result: list[SourceRef] = []
    for ref in refs:
        if ref.kind is not SourceKind.TWITTER:
            continue
        canonical = SourceRef(kind=SourceKind.TWITTER, handle=normalize_handle(ref.handle))
        if canonical.handle in seen:
            continue
        seen.add(canonical.handle)
        result.append(canonical)
    return result
