"""baseline: symbols, news_items, candles

Revision ID: 0001
Revises:
Create Date: 2026-04-23

Creates the initial schema and seeds two canonical symbols (NVDA, SPY) so
a fresh developer can exercise `GET /v1/symbols` without an ingest step.
Supersedes the hand-rolled `db/init.sql` bootstrap.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "news_items",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
    )
    # Most queries filter by recency; a desc index on ts keeps them cheap.
    op.create_index(
        "ix_news_items_ts_desc",
        "news_items",
        [sa.text("ts DESC")],
    )

    op.create_table(
        "candles",
        sa.Column(
            "symbol",
            sa.String(length=16),
            sa.ForeignKey("symbols.symbol", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), primary_key=True),
        sa.Column("interval", sa.String(length=8), primary_key=True),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    # "Latest bar for a symbol at an interval" is the hottest query; put a
    # (symbol, interval, ts desc) index on it so it's a single-row lookup.
    op.create_index(
        "ix_candles_symbol_interval_ts_desc",
        "candles",
        ["symbol", "interval", sa.text("ts DESC")],
    )

    # Seed a couple of canonical symbols so /v1/symbols returns data out of
    # the box. Keep this list short — everything else should come from the
    # real ingest pipeline.
    symbols_table = sa.table(
        "symbols",
        sa.column("symbol", sa.String),
        sa.column("name", sa.String),
    )
    op.bulk_insert(
        symbols_table,
        [
            {"symbol": "NVDA", "name": "NVIDIA Corp"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_candles_symbol_interval_ts_desc", table_name="candles")
    op.drop_table("candles")
    op.drop_index("ix_news_items_ts_desc", table_name="news_items")
    op.drop_table("news_items")
    op.drop_table("symbols")
