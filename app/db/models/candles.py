from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

# Allowed values: "1d", "1h", "5m". Kept as a short varchar rather than a
# Postgres enum so that adding intervals later is a schema-free change.
INTERVAL_LEN = 8

# 18 total digits, 6 fractional — safely covers prices from fractional pennies
# up to ~1e12. Integer math on Numeric avoids the float-drift pitfalls that
# bite cost bases, P&L, and technicals aggregations down the line.
PRICE = Numeric(18, 6)


class Candle(Base):
    """
    An OHLCV bar for a given (symbol, ts, interval).

    Append-only — never update a bar in place. If a provider restates,
    insert a superseding row and scope reads by latest `ingested_at`
    (future column) rather than mutating history.
    """

    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("symbols.symbol", ondelete="CASCADE"),
        primary_key=True,
    )
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    interval: Mapped[str] = mapped_column(String(INTERVAL_LEN), primary_key=True)

    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
