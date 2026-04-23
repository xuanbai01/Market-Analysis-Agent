from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.market import OHLCV, MarketSnapshotOut, Technicals


async def get_latest_snapshot(session: AsyncSession, symbol: str, tz: str) -> MarketSnapshotOut | None:
    """
    Story 1 stub:
    - In the future, query OHLCV from the DB and compute technicals.
    - For now, return a fake 1.0 bar so the endpoint works.
    """
    now = datetime.now(UTC).isoformat()

    # TODO: replace with real DB query using SQLAlchemy
    ohlcv = OHLCV(
        ts=now,
        o=1.0,
        h=1.0,
        l=1.0,
        c=1.0,
        v=0.0,
    )

    return MarketSnapshotOut(
        symbol=symbol,
        as_of=now,
        ohlcv=ohlcv,
        technicals=Technicals(),  # all None
    )


async def get_history(
    session: AsyncSession,
    symbol: str,
    start_date: str | None,
    end_date: str | None,
    interval: str,
) -> list[OHLCV]:
    """
    Story 1 stub:
    - Later: query a candles table with filters.
    - For now: return an empty list.
    """
    # TODO: implement real history query
    return []
