"""option_oi_totals: whole-chain open interest, one row a session

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15

The daily IV snapshot sums open interest over the few expiries it reads
(around 30 and 90 days), a window that rolls forward, so its totals jump
when an expiry leaves it. For a short list of tickers
(``OPTIONS_FULL_CHAIN_SYMBOLS``) the run also reads every listed expiry
and stores the totals here: insert-only, the first row for a (symbol,
trading day) wins, like ``option_iv_snapshots``.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "option_oi_totals",
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_open_interest", sa.BigInteger(), nullable=False),
        sa.Column("put_open_interest", sa.BigInteger(), nullable=False),
        sa.Column("call_volume", sa.BigInteger(), nullable=False),
        sa.Column("put_volume", sa.BigInteger(), nullable=False),
        sa.Column("expiries", sa.SmallInteger(), nullable=False),
        sa.Column("listed", sa.SmallInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("option_oi_totals")
