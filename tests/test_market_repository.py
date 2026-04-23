from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.db.models.symbols import Symbol
from app.services.market_repository import get_history, get_latest_snapshot


async def _seed_symbol(session: AsyncSession, symbol: str) -> None:
    session.add(Symbol(symbol=symbol, name=f"{symbol} test"))
    await session.flush()


def _bar(
    *,
    symbol: str,
    ts: datetime,
    close: float = 100.0,
    interval: str = "1d",
) -> Candle:
    return Candle(
        symbol=symbol,
        ts=ts,
        interval=interval,
        open=Decimal(str(close - 1)),
        high=Decimal(str(close + 1)),
        low=Decimal(str(close - 2)),
        close=Decimal(str(close)),
        volume=1_000_000,
    )


async def test_latest_snapshot_returns_none_when_empty(db_session: AsyncSession) -> None:
    await _seed_symbol(db_session, "NVDA")
    snap = await get_latest_snapshot(db_session, "NVDA", tz="UTC")
    assert snap is None


async def test_latest_snapshot_returns_newest_bar(db_session: AsyncSession) -> None:
    await _seed_symbol(db_session, "NVDA")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _bar(symbol="NVDA", ts=now - timedelta(days=2), close=900.0),
            _bar(symbol="NVDA", ts=now - timedelta(days=1), close=950.0),
            _bar(symbol="NVDA", ts=now, close=1000.0),
        ]
    )
    await db_session.flush()

    snap = await get_latest_snapshot(db_session, "NVDA", tz="UTC")
    assert snap is not None
    assert snap.symbol == "NVDA"
    assert snap.ohlcv.c == 1000.0


async def test_latest_snapshot_filters_by_interval(db_session: AsyncSession) -> None:
    await _seed_symbol(db_session, "NVDA")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _bar(symbol="NVDA", ts=now, close=999.0, interval="1h"),
            _bar(symbol="NVDA", ts=now - timedelta(days=1), close=500.0, interval="1d"),
        ]
    )
    await db_session.flush()

    # Default interval is "1d" — the 1h bar must not leak in.
    snap = await get_latest_snapshot(db_session, "NVDA", tz="UTC")
    assert snap is not None
    assert snap.ohlcv.c == 500.0


async def test_history_respects_date_filters(db_session: AsyncSession) -> None:
    await _seed_symbol(db_session, "NVDA")
    base = datetime(2026, 4, 1, tzinfo=UTC)
    db_session.add_all(
        [
            _bar(symbol="NVDA", ts=base + timedelta(days=i), close=100.0 + i)
            for i in range(5)
        ]
    )
    await db_session.flush()

    # Inclusive window covering days 1 through 3.
    bars = await get_history(
        db_session,
        "NVDA",
        start_date="2026-04-02T00:00:00+00:00",
        end_date="2026-04-04T00:00:00+00:00",
        interval="1d",
    )
    closes = [b.c for b in bars]
    assert closes == [101.0, 102.0, 103.0]


async def test_history_ascending_order(db_session: AsyncSession) -> None:
    await _seed_symbol(db_session, "NVDA")
    base = datetime(2026, 4, 1, tzinfo=UTC)
    # Insert out of order to prove the ORDER BY clause, not insertion order, drives output.
    db_session.add_all(
        [
            _bar(symbol="NVDA", ts=base + timedelta(days=2), close=103.0),
            _bar(symbol="NVDA", ts=base, close=100.0),
            _bar(symbol="NVDA", ts=base + timedelta(days=1), close=101.0),
        ]
    )
    await db_session.flush()

    bars = await get_history(
        db_session, "NVDA", start_date=None, end_date=None, interval="1d"
    )
    assert [b.c for b in bars] == [100.0, 101.0, 103.0]
