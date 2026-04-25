from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsItemModel
from app.db.models.news_symbols import NewsSymbol
from app.schemas.news import NewsItemOut


async def _symbols_for_news(
    session: AsyncSession,
    news_ids: list[str],
) -> dict[str, list[str]]:
    """
    Bulk-load the symbols tagged on a batch of articles. Returns a dict
    keyed by news_id; each value is the symbols list (empty if none).
    Avoids N+1 queries on list endpoints.
    """
    if not news_ids:
        return {}
    stmt = select(NewsSymbol).where(NewsSymbol.news_id.in_(news_ids))
    rows = (await session.execute(stmt)).scalars().all()

    out: dict[str, list[str]] = {nid: [] for nid in news_ids}
    for row in rows:
        out[row.news_id].append(row.symbol)
    # Stable order so the API response doesn't churn between calls.
    for sym_list in out.values():
        sym_list.sort()
    return out


async def list_news(
    session: AsyncSession,
    symbol: str | None,
    hours: int,
    limit: int,
    cursor: str | None,
) -> tuple[list[NewsItemOut], str | None]:
    """
    List articles in the last ``hours``, newest first. When ``symbol``
    is given, restrict to articles tagged with that symbol via the
    ``news_symbols`` join. Cursor pagination is still TBD — for now we
    cap at ``limit`` and return ``next_cursor=None``.
    """
    _ = cursor  # cursor pagination lands when result sets actually overflow
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    stmt = select(NewsItemModel).where(NewsItemModel.ts >= cutoff)
    if symbol:
        # Inner join through news_symbols — keeps the index plan simple
        # and lets Postgres push the symbol filter into the join lookup.
        stmt = stmt.join(
            NewsSymbol, NewsSymbol.news_id == NewsItemModel.id
        ).where(NewsSymbol.symbol == symbol.upper())
    stmt = stmt.order_by(NewsItemModel.ts.desc()).limit(limit)

    rows = (await session.execute(stmt)).scalars().all()

    sym_map = await _symbols_for_news(session, [r.id for r in rows])
    items = [
        NewsItemOut(
            id=row.id,
            ts=row.ts.isoformat(),
            title=row.title,
            url=row.url,
            source=row.source,
            symbols=sym_map.get(row.id, []),
        )
        for row in rows
    ]

    return items, None


async def get_news_by_id(
    session: AsyncSession,
    news_id: str,
) -> NewsItemOut | None:
    stmt = select(NewsItemModel).where(NewsItemModel.id == news_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if not row:
        return None

    sym_map = await _symbols_for_news(session, [row.id])
    return NewsItemOut(
        id=row.id,
        ts=row.ts.isoformat(),
        title=row.title,
        url=row.url,
        source=row.source,
        symbols=sym_map.get(row.id, []),
    )
