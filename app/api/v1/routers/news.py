from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.dependencies import get_session
from app.schemas.news import NewsItemOut, NewsListResponse
from app.services.news_repository import list_news, get_news_by_id
from app.services.data_ingestion import ingest_news_once


router = APIRouter()


@router.post("/news/ingest")
async def news_ingest(session: AsyncSession = Depends(get_session)):
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="News item not found")
    return item