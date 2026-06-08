"""Near-duplicate collapse via MinHash/Jaccard (task-007 step 1, AC1).

Pure + immutable: ``run`` returns a NEW list, keeping the FIRST post of each
near-duplicate group and dropping later near-dups. Two posts are near-duplicates
when their estimated Jaccard similarity (over character shingles) is at or above
``Settings.dedup_similarity_threshold``. Operates on platform-independent
`RawPost` only (ADR-001) — no Telegram knowledge.

Posts with empty/`None` text produce an empty shingle set: they can never reach
the similarity threshold against a non-empty post, so they are never collapsed
into one another (edge case — empty text must not break MinHash).
"""

from datasketch import MinHash

from collector.base import RawPost
from config import get_settings
from pipeline.constants import MINHASH_NUM_PERM, MINHASH_SHINGLE_SIZE


def _shingles(text: str | None) -> set[bytes]:
    """Overlapping character k-grams of ``text`` as the MinHash element set.

    Returns an empty set for empty/`None` text (deterministic, never raises).
    """
    if not text:
        return set()
    cleaned = text.strip()
    if len(cleaned) < MINHASH_SHINGLE_SIZE:
        return {cleaned.encode("utf-8")} if cleaned else set()
    return {
        cleaned[i : i + MINHASH_SHINGLE_SIZE].encode("utf-8")
        for i in range(len(cleaned) - MINHASH_SHINGLE_SIZE + 1)
    }


def _minhash(text: str | None) -> MinHash:
    """Build a MinHash signature for ``text`` (empty set → all-empty signature)."""
    mh = MinHash(num_perm=MINHASH_NUM_PERM)
    for shingle in _shingles(text):
        mh.update(shingle)
    return mh


def run(posts: list[RawPost]) -> list[RawPost]:
    """Collapse near-duplicate posts, keeping the first of each near-dup group.

    Greedy first-wins: each post is compared against the signatures of already
    kept posts; if its estimated Jaccard with any kept post is >= the configured
    threshold it is dropped as a near-duplicate. Input list and posts are never
    mutated. Empty input → empty list.
    """
    if not posts:
        return []

    threshold = get_settings().dedup_similarity_threshold
    kept: list[RawPost] = []
    kept_signatures: list[MinHash] = []

    for post in posts:
        signature = _minhash(post.text)
        is_near_dup = any(signature.jaccard(existing) >= threshold for existing in kept_signatures)
        if is_near_dup:
            continue
        kept.append(post)
        kept_signatures.append(signature)

    return kept
