from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.news import NewsItemOut


async def list_news(session: AsyncSession, symbol: str | None, hours: int, limit: int, cursor: str | None):
    # TODO: add real DB filtering + cursoring
    return [], None


async def get_news_by_id(session: AsyncSession, news_id: str):
    # TODO: lookup by id
    return None