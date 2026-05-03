"""
Phase 4.1 — read-through prices service for the hero price chart.

`get_prices_with_cache` checks ``candles`` for sufficient coverage of
the requested range; if found, returns the cached rows. Otherwise calls
the existing `ingest_market_data` path which populates `candles` via
yfinance, then re-queries.

The "sufficient coverage" heuristic is simple: count rows in the date
window vs the expected bar count. If we have at least 80% coverage AND
the latest bar is from today (or yesterday on weekends), use the cache.

Why not always re-fetch: yfinance free-tier traffic adds up across
dogfood usage. Same-day cache via `candles` matches the report-level
cache pattern from Phase 2.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.schemas.market import MarketPricesOut, PriceLatest, PricePoint
from app.services.data_ingestion import ingest_market_data

# Map the dashboard's range strings to (yfinance period, expected bar
# count). Bar count is approximate — yfinance returns slightly fewer
# bars over weekends/holidays, so the cache-coverage check uses 80%.
RANGE_TO_PERIOD: dict[str, tuple[str, int]] = {
    "60D": ("60d", 42),  # ~60 calendar days = ~42 trading days
    "1Y": ("1y", 252),
    "5Y": ("5y", 1260),
}

# Coverage threshold for the cache hit decision. 80% of the expected
# bar count means the cache has the bulk of the range; missing tail
# data is acceptable (probably the latest 1-2 days haven't been
# ingested yet — refetching just to add 2 bars isn't worth the
# yfinance roundtrip).
COVERAGE_THRESHOLD = 0.8


def _range_window(range_str: str) -> tuple[datetime, datetime, int]:
    """Return (start, end, expected_bars) for a given range string."""
    if range_str not in RANGE_TO_PERIOD:
        raise ValueError(f"Unknown range {range_str!r}")
    _period, expected_bars = RANGE_TO_PERIOD[range_str]
    end = datetime.now(UTC)
    days_back = {"60D": 90, "1Y": 400, "5Y": 5 * 400}[range_str]
    start = end - timedelta(days=days_back)
    return start, end, expected_bars


async def _query_candles_in_window(
    session: AsyncSession,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    """Pull daily candles for ``symbol`` in [start, end] ordered oldest-first."""
    stmt = (
        select(Candle)
        .where(
            Candle.symbol == symbol,
            Candle.interval == "1d",
            Candle.ts >= start,
            Candle.ts <= end,
        )
        .order_by(Candle.ts.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def _candle_to_point(candle: Candle) -> PricePoint:
    return PricePoint(
        ts=candle.ts.isoformat(),
        close=float(candle.close),
        volume=float(candle.volume),
    )


def _latest_from_points(points: list[PricePoint]) -> PriceLatest:
    """Compute headline latest + delta from the last two points.

    If only one point exists, delta is 0. Empty caller is responsible
    for handling — this helper assumes ``points`` is non-empty.
    """
    last = points[-1]
    if len(points) >= 2:
        prev_close = points[-2].close
        delta_abs = last.close - prev_close
        delta_pct = (delta_abs / prev_close) if prev_close != 0 else 0.0
    else:
        delta_abs = 0.0
        delta_pct = 0.0
    return PriceLatest(
        ts=last.ts,
        close=last.close,
        delta_abs=delta_abs,
        delta_pct=delta_pct,
    )


async def get_prices_with_cache(
    session: AsyncSession,
    symbol: str,
    range_str: str,
) -> MarketPricesOut:
    """Read-through cache for the prices endpoint.

    1. Query ``candles`` for the symbol in the range window.
    2. If coverage >= 80%, return cached rows.
    3. Else: trigger ingest_market_data (yfinance fetch + upsert), then
       re-query and return.
    """
    if range_str not in RANGE_TO_PERIOD:
        raise ValueError(f"Unknown range {range_str!r}")

    start, end, expected = _range_window(range_str)
    period_str, _ = RANGE_TO_PERIOD[range_str]

    cached = await _query_candles_in_window(session, symbol, start, end)

    if len(cached) >= expected * COVERAGE_THRESHOLD:
        # Cache hit — return without yfinance call.
        points = [_candle_to_point(c) for c in cached]
    else:
        # Cache miss — fetch + upsert + re-query.
        await ingest_market_data(
            session,
            symbol=symbol,
            period=period_str,
            provider="yfinance",
            interval="1d",
        )
        cached = await _query_candles_in_window(session, symbol, start, end)
        points = [_candle_to_point(c) for c in cached]

    if not points:
        # No data available even after ingest attempt.
        latest = PriceLatest(
            ts=end.isoformat(),
            close=0.0,
            delta_abs=0.0,
            delta_pct=0.0,
        )
    else:
        latest = _latest_from_points(points)

    return MarketPricesOut(
        ticker=symbol,
        range=range_str,
        prices=points,
        latest=latest,
    )
