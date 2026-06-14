"""Event categorization — what KIND of crypto event a signal is (RU + EN).

Different buyers pay for different events (a listing matters to traders, a hack to risk
desks, regulation to funds) — so the alert/API (T6/T7) tags each signal with a category.
Pure keyword/rule classifier over a cluster's representative text; no model, no I/O
(ADR-001). Precedence is most-specific-first: a hacked-listing is a HACK, not a LISTING.
All patterns are NAMED (CONVENTIONS).
"""

import re
from enum import StrEnum


class EventCategory(StrEnum):
    """Coarse event taxonomy for a signal (str-enum: JSON/DB friendly)."""

    LISTING = "listing"
    HACK = "hack"
    REGULATION = "regulation"
    PRICE_MOVE = "price_move"
    OTHER = "other"


# RU + EN keyword patterns per category. Order of the tuple below IS the precedence
# (first match wins): specific incident types before the generic price move.
_HACK = (
    r"взлом|взлома|хакер|эксплойт|украл|похищен|слил[ои]?\s+средств|дрейн",
    r"\bhack(?:ed|er)?\b|\bexploit(?:ed)?\b|\bdrain(?:ed)?\b|\bstolen\b|\brug\s*pull\b|\bbreach\b",
)
_REGULATION = (
    r"\bSEC\b|\bCFTC\b|регулятор|регулирован|законопроект|запрет|санкци|иск\b|суд\b|штраф",
    r"\blawsuit\b|\bsue[sd]?\b|\bban(?:ned|s)?\b|\bregulat(?:or|ion|ory)\b|\bsanction|\bsettlement\b",
)
_LISTING = (
    r"листинг|добавил[аои]?\s+в\s+листинг|торги\s+открыт|запуск\s+торгов",
    r"\blisting\b|\blists?\b|now\s+trading|will\s+list|готов[а]?\s+к\s+торгам",
)
_PRICE_MOVE = (
    r"обновил\s+(?:максимум|минимум)|рухнул|обвал|взлетел|вырос\s+на|упал\s+на|памп|дамп",
    r"\bATH\b|all-?time\s+high|\bsurge[ds]?\b|\bcrash(?:ed|es)?\b|\bplunge[ds]?\b|\brally|\bpump(?:ed)?\b|\bdump(?:ed)?\b|[-+]?\d+\s*%",
)

_PATTERNS: tuple[tuple[EventCategory, re.Pattern[str]], ...] = (
    (EventCategory.HACK, re.compile("|".join(_HACK), re.IGNORECASE)),
    (EventCategory.REGULATION, re.compile("|".join(_REGULATION), re.IGNORECASE)),
    (EventCategory.LISTING, re.compile("|".join(_LISTING), re.IGNORECASE)),
    (EventCategory.PRICE_MOVE, re.compile("|".join(_PRICE_MOVE), re.IGNORECASE)),
)


def categorize(text: str) -> EventCategory:
    """Classify `text` into an EventCategory (most-specific category wins; else OTHER)."""
    haystack = text or ""
    for category, pattern in _PATTERNS:
        if pattern.search(haystack):
            return category
    return EventCategory.OTHER
