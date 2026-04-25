from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.schemas.news import NewsItemOut, NewsListResponse
from app.services.news_ingestion import fetch_news_for_symbol, ingest_news_once
from app.services.news_repository import get_news_by_id, list_news

router = APIRouter()


class NewsIngestRequest(BaseModel):
    """Optional symbol-scoped ingest. Omit ``symbol`` to fan out across
    every tracked symbol (slower; rate-limited by NewsAPI's free tier)."""

    symbol: str | None = None


@router.post("/news/ingest")
async def news_ingest(
    payload: NewsIngestRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    if payload and payload.symbol:
        count = await fetch_news_for_symbol(session, payload.symbol)
        return {
            "job_id": "local-inline",
            "ingested": count,
            "symbol": payload.symbol.upper(),
        }
    count = await ingest_news_once(session)
    return {"job_id": "local-inline", "ingested": count}


@router.get("/news", response_model=NewsListResponse)
async def news_list(
    symbol: str | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    items, next_cursor = await list_news(session, symbol, hours, limit, cursor)
    return NewsListResponse(items=items, next_cursor=next_cursor)


@router.get("/news/{news_id}", response_model=NewsItemOut)
async def news_detail(news_id: str, session: AsyncSession = Depends(get_session)):
    item = await get_news_by_id(session, news_id)
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
    return item
