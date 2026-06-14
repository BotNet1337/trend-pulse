"""Actionable signal payload — composes the whole noise-filtered, independence-weighted
signal into ONE object an alert / API / MCP tool can act on.

Per product strategy, the sellable unit is not "a cluster" but: WHAT happened (category
+ narrative), HOW STRONG (independence-weighted headline score, noise excluded), WHERE
it started (origin channel + time), and HOW EARLY (lead-time to cross-channel
confirmation). This pure builder folds T1-T5 (noise_filter, independence, attribution,
categorize, headline) into a `SignalPayload`. No I/O, no DB (ADR-001).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from scorer.attribution import AttributionPost, attribute
from scorer.categorize import EventCategory, categorize
from scorer.headline import compute_headline_score
from scorer.independence import effective_independent_reach
from scorer.noise_filter import ClusterPost, SignalKind, classify_cluster
from scorer.score import ScoreInputs

# Narrative is the origin post's text, capped for an alert line.
NARRATIVE_MAX_CHARS = 220
# "Cross-channel confirmed" = the story reached this many distinct channels; the
# lead-time to that point is the headline early-warning metric buyers pay for.
CONFIRMATION_CHANNEL_N = 3


@dataclass(frozen=True)
class SignalPost:
    """Unified per-post input for the payload builder (text + channel + time)."""

    text: str
    channel_id: int
    posted_at: float        # epoch seconds


@dataclass(frozen=True)
class SignalPayload:
    """The actionable signal an alert / API / MCP tool emits."""

    headline_score: float            # [0,100], independence-weighted, 0 if noise
    signal_kind: SignalKind          # organic | promo | coordinated
    category: EventCategory          # listing | hack | regulation | price_move | other
    origin_channel: int
    origin_at: float
    total_channels: int              # raw distinct channels in the cluster
    independent_channels: float      # effective independent reach (shill ring → ~1)
    lead_time_to_confirmation_seconds: float | None  # origin → CONFIRMATION_CHANNEL_N
    narrative: str                   # origin post text, capped


def build_signal_payload(
    *,
    posts: Iterable[SignalPost],
    base: ScoreInputs,
    independence_weights: Mapping[int, float],
) -> SignalPayload | None:
    """Compose an actionable `SignalPayload` from a cluster's posts, or None if empty.

    `base` carries the cluster's aggregates (views/forwards/reactions, delta_hours,
    watched count); `independence_weights` is `independence.independence_weights` for
    the watched set. The headline score uses INDEPENDENT reach and is 0 for noise.
    """
    post_list = list(posts)
    if not post_list:
        return None

    kind = classify_cluster(
        tuple(
            ClusterPost(text=p.text, posted_at=p.posted_at, channel_id=p.channel_id)
            for p in post_list
        )
    )
    timeline = attribute(
        AttributionPost(channel_id=p.channel_id, posted_at=p.posted_at) for p in post_list
    )
    if timeline is None:  # pragma: no cover - post_list is non-empty so this never trips
        return None

    channels = {p.channel_id for p in post_list}
    independent = effective_independent_reach(channels, independence_weights)
    score = compute_headline_score(
        base=base, effective_independent_channels=independent, signal_kind=kind
    )

    # Narrative + category come from the ORIGIN channel's earliest post.
    origin_posts = sorted(
        (p for p in post_list if p.channel_id == timeline.origin_channel),
        key=lambda p: p.posted_at,
    )
    origin_text = origin_posts[0].text if origin_posts else ""

    return SignalPayload(
        headline_score=score,
        signal_kind=kind,
        category=categorize(origin_text),
        origin_channel=timeline.origin_channel,
        origin_at=timeline.origin_at,
        total_channels=len(channels),
        independent_channels=independent,
        lead_time_to_confirmation_seconds=timeline.lead_time_seconds_to_nth_channel(
            CONFIRMATION_CHANNEL_N
        ),
        narrative=origin_text[:NARRATIVE_MAX_CHARS],
    )
