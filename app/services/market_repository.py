from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.schemas.market import OHLCV, MarketSnapshotOut, Technicals


def _candle_to_ohlcv(row: Candle) -> OHLCV:
    """Convert a Candle row to the API's short-name OHLCV schema."""
    return OHLCV(
        ts=row.ts.isoformat(),
        o=float(row.open),
        h=float(row.high),
        l=float(row.low),
        c=float(row.close),
        v=float(row.volume),
    )


async def get_latest_snapshot(
    session: AsyncSession,
    symbol: str,
    tz: str,
    interval: str = "1d",
) -> MarketSnapshotOut | None:
    """
    Return the most recent bar for ``symbol`` at ``interval``, or None if
    nothing has been ingested yet. The ``tz`` hint is reserved for future
    display-time conversion; we always store and return UTC.
    """
    _ = tz  # reserved
    stmt = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.interval == interval)
        .order_by(Candle.ts.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return MarketSnapshotOut(
        symbol=row.symbol,
        as_of=row.ts.isoformat(),
        ohlcv=_candle_to_ohlcv(row),
        technicals=Technicals(),  # populated in a later PR
    )


async def get_history(
    session: AsyncSession,
    symbol: str,
    start_date: str | None,
    end_date: str | None,
    interval: str,
) -> list[OHLCV]:
    """
    Return bars for ``symbol`` at ``interval``, optionally filtered by
    ``start_date`` / ``end_date`` (inclusive, ISO 8601 strings).

    ISO strings are parsed to ``datetime`` on the Python side before
    binding — Postgres will not auto-cast varchar to timestamptz in
    comparison predicates. If the caller sends an unparseable string,
    ``fromisoformat`` raises ValueError which FastAPI serializes as a
    problem+json 500 (we'll tighten this to a 400 when the endpoint
    gains real input validation).
    """
    stmt = select(Candle).where(
        Candle.symbol == symbol,
        Candle.interval == interval,
    )
    if start_date:
        stmt = stmt.where(Candle.ts >= datetime.fromisoformat(start_date))
    if end_date:
        stmt = stmt.where(Candle.ts <= datetime.fromisoformat(end_date))
    stmt = stmt.order_by(Candle.ts.asc())

    rows = (await session.execute(stmt)).scalars().all()
    return [_candle_to_ohlcv(r) for r in rows]
