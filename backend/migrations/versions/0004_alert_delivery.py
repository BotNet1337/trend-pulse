"""Alert delivery — delivery status/attempts + user delivery-config (task-009).

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09

Additive and backward-compatible (single head 0001→0002→0003→0004):

- `alerts.delivery_status` (NOT NULL, server_default `'pending'`) +
  `alerts.delivery_attempts` (NOT NULL, server_default `0`) — the delivery state
  machine; existing rows backfill via the server defaults.
- `users.telegram_bot_token` / `telegram_chat_id` / `webhook_url` (nullable) —
  per-user delivery config; the bot token is a secret at rest (never logged).
- `users.plan` (NOT NULL, server_default `'free'`) — the plan-gating seam for
  webhook delivery (free/pro/team); hard enforcement is task-010.

SQLAlchemy ops only (no f-string SQL — CONVENTIONS).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELIVERY_STATUS_MAX = 16
_PLAN_MAX = 16
_TELEGRAM_BOT_TOKEN_MAX = 128
_TELEGRAM_CHAT_ID_MAX = 64
_WEBHOOK_URL_MAX = 2048


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column(
            "delivery_status",
            sa.String(length=_DELIVERY_STATUS_MAX),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("telegram_bot_token", sa.String(length=_TELEGRAM_BOT_TOKEN_MAX), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("telegram_chat_id", sa.String(length=_TELEGRAM_CHAT_ID_MAX), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("webhook_url", sa.String(length=_WEBHOOK_URL_MAX), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "plan",
            sa.String(length=_PLAN_MAX),
            nullable=False,
            server_default="free",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "plan")
    op.drop_column("users", "webhook_url")
    op.drop_column("users", "telegram_chat_id")
    op.drop_column("users", "telegram_bot_token")
    op.drop_column("alerts", "delivery_attempts")
    op.drop_column("alerts", "delivery_status")
