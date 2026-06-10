"""Cases domain service (TASK-045).

``get_cases(session, top_n) -> CasesResponse``

Queries showcase_cases:
  - WHERE mainstream_at IS NOT NULL (only operator-confirmed cases).
  - ORDER BY (mainstream_at - first_seen) DESC (longest lead-time first).
  - LIMIT top_n.
  - Returns aggregate-only fields (compliance §7 — no raw content).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.cases.schemas import CaseItem, CasesResponse
from storage.models.showcase_cases import ShowcaseCase


def get_cases(session: Session, *, top_n: int) -> CasesResponse:
    """Return top-N proof-of-speed cases sorted by lead-time DESC.

    Only cases with mainstream_at IS NOT NULL are returned (cases without an
    operator-filled timestamp are not yet proof-points and stay hidden).

    Args:
        session: Sync SQLAlchemy session.
        top_n:   Max number of items to return (≤ settings.cases_top_n_max).

    Returns:
        CasesResponse with items sorted by lead_time DESC.
    """
    # Compute lead time as a SQL expression for ordering.
    # PostgreSQL supports interval arithmetic; SQLAlchemy renders
    # (mainstream_at - first_seen) as an interval, then EXTRACT(epoch …) → seconds.
    lead_time_expr = func.extract("epoch", ShowcaseCase.mainstream_at - ShowcaseCase.first_seen)

    stmt = (
        select(ShowcaseCase)
        .where(ShowcaseCase.mainstream_at.is_not(None))
        .order_by(lead_time_expr.desc())
        .limit(top_n)
    )

    rows = session.execute(stmt).scalars().all()

    items: list[CaseItem] = []
    for row in rows:
        mainstream_at = row.mainstream_at
        if mainstream_at is None:  # pragma: no cover — filtered IS NOT NULL above
            continue
        items.append(
            CaseItem(
                title=row.title,
                viral_score=row.viral_score,
                first_seen=row.first_seen,
                mainstream_at=mainstream_at,
                lead_time_seconds=int((mainstream_at - row.first_seen).total_seconds()),
                channels_count=row.channels_count,
            )
        )

    return CasesResponse(items=items)


__all__ = ["get_cases"]
