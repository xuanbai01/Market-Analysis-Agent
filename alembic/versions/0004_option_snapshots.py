"""option_iv_snapshots and options_tracked (ADR 0008)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15

``option_iv_snapshots`` holds one row per (symbol, trading day), written
by the daily run after the close and never updated: no free source has
option IV history, so this table is it. The PK covers the run's "already
stored for this session?" read and a symbol's history in date order.
``detail`` (JSONB) keeps the raw near-money quotes behind the figures,
about 7 KB a row, so a later method can be recomputed over the history.

``options_tracked`` lists symbols whose options page was opened, which
the daily run snapshots for 60 days after the last visit.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "option_iv_snapshots",
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method_version", sa.SmallInteger(), nullable=False),
        sa.Column("spot", sa.Float(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("iv30", sa.Float(), nullable=True),
        sa.Column("iv30_extrapolated", sa.Boolean(), nullable=False),
        sa.Column("iv90", sa.Float(), nullable=True),
        sa.Column("iv90_extrapolated", sa.Boolean(), nullable=False),
        sa.Column("skew25", sa.Float(), nullable=True),
        sa.Column("rv20", sa.Float(), nullable=True),
        sa.Column("rv60", sa.Float(), nullable=True),
        sa.Column("call_open_interest", sa.BigInteger(), nullable=False),
        sa.Column("put_open_interest", sa.BigInteger(), nullable=False),
        sa.Column("call_volume", sa.BigInteger(), nullable=False),
        sa.Column("put_volume", sa.BigInteger(), nullable=False),
        sa.Column("next_earnings", sa.Date(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_table(
        "options_tracked",
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("last_viewed", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("options_tracked")
    op.drop_table("option_iv_snapshots")
