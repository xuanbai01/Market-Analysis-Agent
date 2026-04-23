from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsItemModel
from app.schemas.news import NewsItemOut


async def list_news(
    session: AsyncSession,
    symbol: str | None,
    hours: int,
    limit: int,
    cursor: str | None,
) -> tuple[list[NewsItemOut], str | None]:
    """
    Story 1 implementation:
    - Ignore symbol + cursor for now (we'll improve later).
    - Filter by last `hours` of news.
    - Order by ts desc, limit N.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    stmt = (
        select(NewsItemModel)
        .where(NewsItemModel.ts >= cutoff)
        .order_by(NewsItemModel.ts.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        NewsItemOut(
            id=row.id,
            ts=row.ts.isoformat(),
            title=row.title,
            url=row.url,
            source=row.source,
            symbols=[],  # we'll add real tagging later
        )
        for row in rows
    ]

    next_cursor = None  # Story 1: no real cursor yet
    return items, next_cursor


async def get_news_by_id(
    session: AsyncSession,
    news_id: str,
) -> NewsItemOut | None:
    stmt = select(NewsItemModel).where(NewsItemModel.id == news_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        return None

    return NewsItemOut(
        id=row.id,
        ts=row.ts.isoformat(),
        title=row.title,
        url=row.url,
        source=row.source,
        symbols=[],
    )
