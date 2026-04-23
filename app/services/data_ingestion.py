from sqlalchemy.ext.asyncio import AsyncSession


async def ingest_market_data(
    session: AsyncSession,
    symbol: str,
    period: str,
    provider: str,
) -> int:
    """
    Story 1 stub:
    - Later: call yfinance/polygon, insert OHLCV into DB.
    - For now: do nothing and pretend we ingested 0 rows.
    """
    # TODO: implement real ingestion
    return 0


async def ingest_news_once(session: AsyncSession) -> int:
    """
    Story 1 stub:
    - Later: call RSS/NewsAPI, write news_items rows into DB.
    - For now: do nothing and pretend we ingested 0 rows.
    """
    # TODO: implement real news ingestion
    return 0
