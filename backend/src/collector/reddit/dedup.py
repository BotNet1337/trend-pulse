"""Pure cross-tenant dedup of Reddit `SourceRef`s (TASK-092, mirrors twitter/dedup).

A subreddit watched by N tenants is read ONCE: build the UNION of unique refs.
Reddit subreddit handles are normalized first (strip a leading `r/` / `/r/` /
`reddit.com/r/` URL prefix, lowercase — subreddit names are case-insensitive) so
`r/CryptoCurrency`, `cryptocurrency` and `https://www.reddit.com/r/CryptoCurrency`
collapse to one ref. Pure + order-preserving (deterministic read order, testable).
"""

from collector.base import SourceKind, SourceRef

_URL_PREFIXES = (
    "https://www.reddit.com/r/",
    "https://reddit.com/r/",
    "http://www.reddit.com/r/",
    "http://reddit.com/r/",
    "www.reddit.com/r/",
    "reddit.com/r/",
    "/r/",
    "r/",
)


def normalize_handle(handle: str) -> str:
    """Normalize a Reddit handle to its canonical bare-subreddit form (lowercased).

    Strips an `r/` / `/r/` / `reddit.com/r/` URL prefix AND any trailing path or
    query (`/CryptoCurrency/comments/...`, `/CryptoCurrency?ref=...`,
    `/CryptoCurrency/`) so a subreddit/post URL collapses to the bare subreddit
    name — never a malformed handle to the API.
    """
    value = handle.strip()
    lowered = value.lower()
    for prefix in _URL_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    # Keep only the subreddit segment (drop /path and ?query).
    value = value.split("/", 1)[0].split("?", 1)[0]
    return value.lower()


def unique_reddit_refs(refs: list[SourceRef]) -> list[SourceRef]:
    """Order-preserving UNION of unique, normalized REDDIT `SourceRef`s.

    Non-Reddit refs are ignored (the Reddit collector only handles REDDIT).
    """
    seen: set[str] = set()
    result: list[SourceRef] = []
    for ref in refs:
        if ref.kind is not SourceKind.REDDIT:
            continue
        canonical = SourceRef(kind=SourceKind.REDDIT, handle=normalize_handle(ref.handle))
        if canonical.handle in seen:
            continue
        seen.add(canonical.handle)
        result.append(canonical)
    return result
