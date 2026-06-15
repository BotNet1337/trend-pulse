"""Public temporal-cascade datasets → the shared B2 early-window feature schema (B3).

TASK-111 (Track B→C / B3). B0 showed the offline crypto-RU corpus yields only ~315
genuinely-multi-channel quality stories, so the OFFLINE GBDT (C1) is N-limited on TG
data alone. Public cascade datasets supply training VOLUME with the SAME early-window
structure the B2 harness consumes, validating the methodology at scale.

What this module does: load a timestamped interaction stream, group it into CASCADES
(all interactions targeting one item, ordered by time), and project each cascade into
the shared B2 contract — a `eval.forward_split.ClusterOutcome` (birth + future
outcome) plus an early-window feature vector measured over `[birth, birth + T_obs]`
only. The feature names mirror the TG harness (`harness3_forward_split`) so the same
split/label/metric code runs unchanged on either substrate.

DATASETS (status logged by `bootstrap_status`):
- **Higgs Twitter** (snap.stanford.edu/data/higgs-activity_time.html) — WORKING. A
  563k-row stream `userA userB unix_ts {RT|RE|MT}`; a cascade = all activity targeting
  `userB`. Free, direct download (~4 MB gz). The committed sample is the first 5k rows
  (`data_public/higgs_activity_sample.txt`); the full file is gitignored under `data/`.
- **Pushshift Telegram** (zenodo 3607497) — SKIPPED: `messages.ndjson.zst` is ~52 GB
  (infeasible to bootstrap offline); the small `channels`/`accounts` files carry no
  per-message cascade timing.
- **Weibo / DeepHawkes** (github CaoQi92/DeepHawkes) — SKIPPED: the repo ships only
  code; the cascade dataset is behind a manual Google-Drive/Baidu download (no direct
  URL, needs manual auth).
- **MemeTracker** (snap.stanford.edu/data/memetracker9.html) — SKIPPED: monthly
  phrase-cluster files are GB-scale; no small official sample slice.

This module is typed (no `Any`), validates at the boundary, and is pure I/O + mapping.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from eval.forward_split import ClusterOutcome  # noqa: E402


class HiggsInteraction(Enum):
    """The three Higgs activity types (col 4); weighted like TG engagement (RT > RE > MT)."""

    RETWEET = "RT"
    REPLY = "RE"
    MENTION = "MT"


# engagement weights — a retweet (spread) > a reply > a mention, mirroring the TG
# forward/reaction/view ordering in `scorer.score`. Named, no magic literals.
_INTERACTION_WEIGHT: dict[HiggsInteraction, float] = {
    HiggsInteraction.RETWEET: 3.0,
    HiggsInteraction.REPLY: 2.0,
    HiggsInteraction.MENTION: 1.0,
}


class PublicDatasetError(ValueError):
    """A public-dataset row could not be parsed into the expected typed record."""


@dataclass(frozen=True)
class CascadeEvent:
    """One timestamped interaction in a cascade — typed + validated at the boundary."""

    source_id: int
    target_id: int
    epoch: int
    interaction: HiggsInteraction

    def __post_init__(self) -> None:
        if self.epoch < 0:
            raise PublicDatasetError(f"epoch must be >= 0, got {self.epoch}")


def parse_higgs_line(line: str, *, line_num: int) -> CascadeEvent:
    """Parse one ``userA userB ts {RT|RE|MT}`` Higgs row into a `CascadeEvent`."""
    parts = line.split()
    if len(parts) != 4:
        raise PublicDatasetError(f"line {line_num}: expected 4 fields, got {len(parts)}: {line!r}")
    try:
        source_id = int(parts[0])
        target_id = int(parts[1])
        epoch = int(parts[2])
    except ValueError as exc:
        raise PublicDatasetError(f"line {line_num}: non-integer field: {line!r}") from exc
    try:
        interaction = HiggsInteraction(parts[3])
    except ValueError as exc:
        raise PublicDatasetError(
            f"line {line_num}: unknown interaction {parts[3]!r}: {line!r}"
        ) from exc
    return CascadeEvent(
        source_id=source_id, target_id=target_id, epoch=epoch, interaction=interaction
    )


def load_higgs(path: Path) -> list[CascadeEvent]:
    """Load the Higgs activity stream into validated `CascadeEvent`s (one per row)."""
    events: list[CascadeEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line_num, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            events.append(parse_higgs_line(stripped, line_num=line_num))
    return events


@dataclass(frozen=True)
class CascadeFeatures:
    """Shared early-window feature vector (mirrors the TG harness feature names).

    Measured over ``[birth, birth + obs_seconds]`` only — leak-free early signal.
    ``e_eng_log`` is the weighted-interaction analogue of TG ``e_eng_log``; ``e_ch`` is
    distinct early SOURCES (analogue of distinct channels = breadth of spread).
    """

    e_ch: float  # distinct early sources (breadth)
    e_posts: float  # early interaction count
    e_eng_log: float  # log1p(weighted early engagement)
    e_burst: float  # early sources per hour (spread speed)


_SECONDS_PER_HOUR = 3600.0
_MIN_SPAN_HOURS = 1.0 / 60.0  # 1-minute floor, mirrors the score's burst floor


def group_cascades(events: list[CascadeEvent]) -> dict[int, list[CascadeEvent]]:
    """Group events into cascades keyed by ``target_id`` (the item being spread).

    A cascade = every interaction targeting one user/item, in time order. Events
    within a cascade are sorted ascending by epoch (then source for determinism).
    """
    by_target: dict[int, list[CascadeEvent]] = defaultdict(list)
    for event in events:
        by_target[event.target_id].append(event)
    return {
        target: sorted(group, key=lambda e: (e.epoch, e.source_id))
        for target, group in by_target.items()
    }


@dataclass(frozen=True)
class MappedCascade:
    """A cascade projected into the B2 contract: outcome + early features."""

    outcome: ClusterOutcome
    features: CascadeFeatures


def _weighted_engagement(events: list[CascadeEvent]) -> float:
    return sum(_INTERACTION_WEIGHT[e.interaction] for e in events)


def map_cascade(
    cascade_id: int, events: list[CascadeEvent], *, obs_seconds: int
) -> MappedCascade | None:
    """Project one time-ordered cascade into a `ClusterOutcome` + early `CascadeFeatures`.

    The cascade's birth is its first event's epoch; the EARLY window keeps only events
    within ``obs_seconds`` of birth; the FUTURE outcome is the full cascade's weighted
    engagement. Returns ``None`` for an empty cascade or one with no early events (the
    caller filters these out). No leakage: features use only early events, the outcome
    is measured over the full cascade and never fed into the feature vector.
    """
    if not events:
        return None
    t0 = events[0].epoch
    early = [e for e in events if e.epoch - t0 <= obs_seconds]
    if not early:
        return None
    distinct_sources = len({e.source_id for e in early})
    early_eng = _weighted_engagement(early)
    span_hours = max((early[-1].epoch - t0) / _SECONDS_PER_HOUR, _MIN_SPAN_HOURS)
    age = events[-1].epoch - t0
    return MappedCascade(
        outcome=ClusterOutcome(
            cluster_id=cascade_id,
            t0_epoch=float(t0),
            final_outcome=_weighted_engagement(events),
            age_at_outcome_seconds=age,
        ),
        features=CascadeFeatures(
            e_ch=float(distinct_sources),
            e_posts=float(len(early)),
            e_eng_log=float(math.log1p(early_eng)),
            e_burst=float(distinct_sources / max(span_hours, obs_seconds / _SECONDS_PER_HOUR)),
        ),
    )


def map_higgs_to_b2(
    events: list[CascadeEvent], *, obs_seconds: int, min_cascade_size: int = 2
) -> list[MappedCascade]:
    """Map a Higgs stream into B2-ready cascades, keeping cascades >= ``min_cascade_size``.

    ``min_cascade_size`` is the public-data analogue of the B0 ``too_small`` /
    ``single_channel`` gate (a 1-interaction cascade is not a spreading story). Cascades
    are id'd deterministically by sorted ``target_id`` so runs are reproducible.
    """
    if min_cascade_size < 1:
        raise PublicDatasetError(f"min_cascade_size must be >= 1, got {min_cascade_size}")
    grouped = group_cascades(events)
    mapped: list[MappedCascade] = []
    for cascade_id, target in enumerate(sorted(grouped)):
        cascade = grouped[target]
        if len(cascade) < min_cascade_size:
            continue
        result = map_cascade(cascade_id, cascade, obs_seconds=obs_seconds)
        if result is not None:
            mapped.append(result)
    return mapped


@dataclass(frozen=True)
class DatasetStatus:
    """Bootstrap status of one public dataset (for the B3 report)."""

    name: str
    available: bool
    note: str


def bootstrap_status() -> tuple[DatasetStatus, ...]:
    """The B3 bootstrap log: which datasets are wired vs skipped and why."""
    return (
        DatasetStatus(
            name="Higgs Twitter",
            available=True,
            note="563k activities, free direct download (~4MB gz); sample committed",
        ),
        DatasetStatus(
            name="Pushshift Telegram (zenodo 3607497)",
            available=False,
            note=(
                "messages.ndjson.zst ~52GB - infeasible offline; "
                "metadata files lack cascade timing"
            ),
        ),
        DatasetStatus(
            name="Weibo / DeepHawkes",
            available=False,
            note="repo ships code only; dataset behind manual Google-Drive/Baidu download",
        ),
        DatasetStatus(
            name="MemeTracker",
            available=False,
            note="monthly phrase files are GB-scale; no small official sample slice",
        ),
    )
