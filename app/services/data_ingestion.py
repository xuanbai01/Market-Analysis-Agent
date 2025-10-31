from sqlalchemy.ext.asyncio import AsyncSession


async def ingest_market_data(session: AsyncSession, symbol: str, period: str, provider: str) -> int:
    # TODO: fetch via yfinance/polygon; insert OHLCV rows; return count
    return 0


async def ingest_news_once(session: AsyncSession) -> int:
    # TODO: fetch RSS (Reuters), hash URL -> id, insert rows; return count
    return 0