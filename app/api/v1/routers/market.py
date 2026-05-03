from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.schemas.market import (
    IngestRequest,
    MarketHistoryOut,
    MarketPricesOut,
    MarketSnapshotOut,
)
from app.services.data_ingestion import ingest_market_data
from app.services.market_prices import RANGE_TO_PERIOD, get_prices_with_cache
from app.services.market_repository import get_history, get_latest_snapshot

router = APIRouter()


@router.post("/market/ingest")
async def market_ingest(req: IngestRequest, session: AsyncSession = Depends(get_session)):
    count = await ingest_market_data(session, req.symbol, req.period, req.provider)
    return {"job_id": "local-inline", "ingested": count, "symbol": req.symbol}


@router.get("/market/{symbol}", response_model=MarketSnapshotOut)
async def market_latest(symbol: str, tz: str = Query("America/New_York"), session: AsyncSession = Depends(get_session)):
    snap = await get_latest_snapshot(session, symbol.upper(), tz)
    if not snap:
        raise HTTPException(status_code=404, detail="Symbol not found or no data")
    return snap


@router.get("/market/{symbol}/history", response_model=MarketHistoryOut)
async def market_history(
    symbol: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    interval: str = Query("1d", pattern="^(1d|1h|5m)$"),
    session: AsyncSession = Depends(get_session),
):
    data = await get_history(session, symbol.upper(), start_date, end_date, interval)
    return MarketHistoryOut(symbol=symbol.upper(), interval=interval, bars=data)


# Phase 4.1 — hero price chart endpoint.
# Read-through cache via `candles` to lower yfinance load on dogfood
# traffic. Range is restricted to the three Phase-4.1 values; 1D/5D
# (intraday cadence) land later.
_RANGE_PATTERN = "^(" + "|".join(RANGE_TO_PERIOD.keys()) + ")$"


@router.get("/market/{symbol}/prices", response_model=MarketPricesOut)
async def market_prices(
    symbol: str,
    range: str = Query("60D", pattern=_RANGE_PATTERN),
    session: AsyncSession = Depends(get_session),
):
    """Daily-bar OHLCV for the dashboard hero price chart.

    Returns close-only points + a precomputed ``latest`` delta block.
    Range is one of 60D / 1Y / 5Y; the route falls through to
    ``ingest_market_data`` on cache miss.
    """
    return await get_prices_with_cache(session, symbol.upper(), range)