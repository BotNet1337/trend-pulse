"""Ad / shill noise filter — classify a cross-channel cluster as organic vs noise.

The cross-channel viral score is only valuable if it surfaces ORGANIC virality — a
real story independently picked up by editorial channels — and NOT advertising. Two
noise classes mimic cross-channel virality and must be excluded (product strategy:
channel-independence / anti-shill is the moat):

  • PROMO        — sponsored / shill content: a post (or most of a cluster) carries
                   advertising markers (#реклama, ref/utm links, invite links, promo
                   CTAs, a contract address with a buy-call).
  • COORDINATED  — a paid "seeding" campaign: the SAME text pushed across many
                   channels almost SIMULTANEOUSLY. Organic spread is time-LAGGED and
                   the wording varies; coordinated seeding is near-identical text in a
                   tight window. (Telegram syndication of a wire story is the same
                   shape and is equally not "organic virality".)

Everything else is ORGANIC. This module is PURE — no I/O, no DB, no platform SDK
(ADR-001) — so the scorer/pipeline can call it and exclude noise. All thresholds are
NAMED constants (CONVENTIONS — no magic literals).
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

# ── Promo markers (RU + EN crypto advertising) ───────────────────────────────
# A single unambiguous marker is enough to call a POST promotional; cluster-level
# promo requires a MAJORITY of posts to be promotional (a lone ad reposted into an
# otherwise-organic story should not poison the whole cluster).
_PROMO_PATTERNS: tuple[str, ...] = (
    r"#\s*реклам",                     # #реклама / # реклама
    r"\b(?:ad|sponsored|promo(?:ted)?)\b",
    r"партн[её]рск",                  # партнёрский материал
    r"utm_[a-z]+=",                    # utm tracking
    r"\bref(?:erral)?[._=/-]",        # referral links
    r"t\.me/\+",                       # private invite link (typical of shill funnels)
    r"промокод|промо-?код",
    r"\bзалетай(?:те)?\b|\bуспей(?:те)?\s+купить|\bbuy\s+now\b|\bape\s+in\b",
    r"\bairdrop\b.*\bclaim\b|\bclaim\b.*\bairdrop\b",
    r"\b0x[a-fA-F0-9]{40}\b",         # EVM contract address (paired with a buy-call below)
    r"\b(?:not\s+financial\s+advice|nfa|это\s+не\s+финанс\w*\s+совет)\b",
)
_PROMO_RE = re.compile("|".join(_PROMO_PATTERNS), re.IGNORECASE)

# A cluster is PROMO when at least this FRACTION of its posts are promotional.
PROMO_CLUSTER_FRACTION = 0.5

# COORDINATED seeding: the same normalized text appears across at least this many
# DISTINCT channels, all within COORDINATED_WINDOW_SECONDS (simultaneous = seeded,
# not organically propagated), and that duplicate set covers at least
# COORDINATED_DUP_FRACTION of the cluster's distinct channels.
COORDINATED_MIN_CHANNELS = 3
COORDINATED_WINDOW_SECONDS = 600.0       # 10 minutes — tighter than organic spread
COORDINATED_DUP_FRACTION = 0.6
# Texts shorter than this (after normalization) are too generic to judge as a
# coordinated duplicate (e.g. "GM", a lone emoji) — ignore them for dup detection.
_MIN_DEDUP_TEXT_LEN = 24

_URL_RE = re.compile(r"https?://\S+|t\.me/\S+|@\w+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


class SignalKind(StrEnum):
    """Noise classification of a cluster (str-enum: JSON/DB friendly)."""

    ORGANIC = "organic"
    PROMO = "promo"
    COORDINATED = "coordinated"


@dataclass(frozen=True)
class ClusterPost:
    """Minimal per-post shape the filter needs — platform-independent."""

    text: str
    posted_at: float        # epoch seconds
    channel_id: int


def is_promotional(text: str) -> bool:
    """True iff `text` carries an unambiguous advertising marker."""
    return bool(_PROMO_RE.search(text or ""))


def _normalize(text: str) -> str:
    """Lowercase, strip URLs/@handles/punctuation/emojis, collapse whitespace.

    Two posts that are the SAME ad with different tracking links / emojis must
    normalize to the same string so coordinated seeding is detected.
    """
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = _URL_RE.sub(" ", text)
    text = _NONWORD_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _is_coordinated(posts: tuple[ClusterPost, ...]) -> bool:
    """True iff a near-identical text was seeded across many channels near-simultaneously.

    For each normalized text, look at the DISTINCT channels that carried it and the
    time span across those channels. Coordinated when one text covers
    >= COORDINATED_MIN_CHANNELS distinct channels AND >= COORDINATED_DUP_FRACTION of
    the cluster's distinct channels, all within COORDINATED_WINDOW_SECONDS.
    """
    distinct_channels = {p.channel_id for p in posts}
    if len(distinct_channels) < COORDINATED_MIN_CHANNELS:
        return False

    by_text: dict[str, list[ClusterPost]] = {}
    for p in posts:
        norm = _normalize(p.text)
        if len(norm) < _MIN_DEDUP_TEXT_LEN:
            continue
        by_text.setdefault(norm, []).append(p)

    for group in by_text.values():
        chans = {p.channel_id for p in group}
        if len(chans) < COORDINATED_MIN_CHANNELS:
            continue
        if len(chans) < COORDINATED_DUP_FRACTION * len(distinct_channels):
            continue
        times = [p.posted_at for p in group]
        if max(times) - min(times) <= COORDINATED_WINDOW_SECONDS:
            return True
    return False


def classify_cluster(posts: tuple[ClusterPost, ...]) -> SignalKind:
    """Classify a cluster as ORGANIC, PROMO, or COORDINATED.

    Precedence: PROMO (a majority are ads) > COORDINATED (same text seeded across
    channels at once) > ORGANIC. An empty cluster is ORGANIC (nothing to flag).
    """
    if not posts:
        return SignalKind.ORGANIC

    promo_count = sum(1 for p in posts if is_promotional(p.text))
    if promo_count >= PROMO_CLUSTER_FRACTION * len(posts):
        return SignalKind.PROMO

    if _is_coordinated(posts):
        return SignalKind.COORDINATED

    return SignalKind.ORGANIC


def is_noise(posts: tuple[ClusterPost, ...]) -> bool:
    """True iff the cluster is PROMO or COORDINATED (should be excluded from the signal)."""
    return classify_cluster(posts) is not SignalKind.ORGANIC
