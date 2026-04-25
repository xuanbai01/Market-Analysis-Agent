"""news_symbols join table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25

Adds the many-to-many join between news_items and symbols. A single
article may mention multiple tickers ("NVDA earnings drag AMD lower")
and a single ticker accumulates many articles, so a join table is the
right shape — not a foreign key on news_items.

Both FKs cascade on delete: removing a symbol drops its article
mappings (the article itself stays for other symbols), and removing an
article drops all its mappings (no dangling rows). Composite PK
prevents duplicate (article, symbol) rows.

Index on (symbol, news_id) — and implicitly on the PK (news_id, symbol)
— so both query directions are cheap: "all articles for AAPL" and "all
symbols mentioned in this article".
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_symbols",
        sa.Column(
            "news_id",
            sa.String(length=64),
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "symbol",
            sa.String(length=16),
            sa.ForeignKey("symbols.symbol", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # The PK already covers (news_id, symbol) lookups. Add the reverse
    # index so "all articles for symbol X, newest first" is also a fast
    # range scan — the dominant query for /v1/news?symbol=...
    op.create_index(
        "ix_news_symbols_symbol_news_id",
        "news_symbols",
        ["symbol", "news_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_symbols_symbol_news_id", table_name="news_symbols")
    op.drop_table("news_symbols")
