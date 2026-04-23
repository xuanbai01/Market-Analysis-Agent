from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.schemas.market import IngestRequest, MarketHistoryOut, MarketSnapshotOut
from app.services.data_ingestion import ingest_market_data
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
    interval: str = Query("1d", regex="^(1d|1h|5m)$"),
    session: AsyncSession = Depends(get_session),
):
    data = await get_history(session, symbol.upper(), start_date, end_date, interval)
    return MarketHistoryOut(symbol=symbol.upper(), interval=interval, bars=data)