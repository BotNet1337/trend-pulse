"""Operator script: set mainstream_at on a showcase_cases row (TASK-045).

Usage (via make case-mainstream):
    make case-mainstream ID=1 AT="2026-06-10T15:00:00Z"

Or directly:
    uv run python scripts/case_mainstream.py --id 1 --at 2026-06-10T15:00:00Z

Validates:
  - Row with given ID exists in showcase_cases.
  - mainstream_at (--at) is strictly after first_seen (refuses if not).
  - --at is a valid ISO 8601 datetime (UTC assumed if no timezone).

Prints the updated row on success; exits non-zero on error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _parse_at(value: str) -> datetime:
    """Parse ISO 8601 datetime string, adding UTC if no timezone given."""
    # Try with 'Z' or +00:00 (tz-aware), then plain naive (assume UTC).
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid datetime format: {value!r}. "
        "Use ISO 8601 (e.g. 2026-06-10T15:00:00Z or 2026-06-10T15:00:00+00:00)."
    )


def main() -> None:
    """Entry point for the case_mainstream script."""
    parser = argparse.ArgumentParser(
        description="Set mainstream_at on a showcase_cases row.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/case_mainstream.py --id 1 --at 2026-06-10T15:00:00Z\n"
            "  make case-mainstream ID=1 AT=2026-06-10T15:00:00Z\n"
        ),
    )
    parser.add_argument("--id", type=int, required=True, help="showcase_cases.id to update")
    parser.add_argument(
        "--at",
        type=_parse_at,
        required=True,
        metavar="ISO8601",
        help="Datetime when the topic appeared in mainstream media (UTC).",
    )
    args = parser.parse_args()

    case_id: int = args.id
    mainstream_at: datetime = args.at

    # Late import: avoid importing DB infra at module-level (script startup speed).
    from config import get_settings
    from storage.database import get_session

    get_settings()  # validates required env vars early (fail fast)

    with get_session() as session:
        _update_case(session, case_id=case_id, mainstream_at=mainstream_at)


def _update_case(session: Session, *, case_id: int, mainstream_at: datetime) -> None:
    """Fetch, validate, update the showcase_cases row and commit."""
    from sqlalchemy import select

    from storage.models.showcase_cases import ShowcaseCase

    row = session.scalar(select(ShowcaseCase).where(ShowcaseCase.id == case_id))
    if row is None:
        print(f"ERROR: No showcase_cases row with id={case_id}", file=sys.stderr)
        sys.exit(1)

    # Edge-case validation: mainstream_at must be AFTER first_seen (AC edge case).
    if mainstream_at <= row.first_seen:
        print(
            f"ERROR: mainstream_at ({mainstream_at.isoformat()}) must be strictly "
            f"after first_seen ({row.first_seen.isoformat()}). "
            "Refusing to set a timestamp that predates detection.",
            file=sys.stderr,
        )
        sys.exit(1)

    row.mainstream_at = mainstream_at
    session.flush()
    session.commit()

    lead_seconds = int((mainstream_at - row.first_seen).total_seconds())
    lead_hours = lead_seconds / 3600

    print(
        f"Updated showcase_cases id={case_id}:\n"
        f"  title:          {row.title!r}\n"
        f"  viral_score:    {row.viral_score}\n"
        f"  first_seen:     {row.first_seen.isoformat()}\n"
        f"  mainstream_at:  {row.mainstream_at.isoformat()}\n"
        f"  lead_time:      {lead_seconds}s ({lead_hours:.1f}h)\n"
        f"  channels_count: {row.channels_count}\n"
    )


if __name__ == "__main__":
    main()
