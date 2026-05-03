from pydantic import BaseModel


class IngestRequest(BaseModel):
    symbol: str
    period: str = "1d"
    provider: str = "yfinance"


class OHLCV(BaseModel):
    ts: str
    o: float
    h: float
    l: float
    c: float
    v: float


class Technicals(BaseModel):
    rsi: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None


class MarketSnapshotOut(BaseModel):
    symbol: str
    as_of: str
    ohlcv: OHLCV
    technicals: Technicals | None = None


class MarketHistoryOut(BaseModel):
    symbol: str
    interval: str
    bars: list[OHLCV]


# Phase 4.1 — hero price chart endpoint shape. Optimized for the
# dashboard's needs: ticker + range + compact close-only points + a
# precomputed "latest" delta.
class PricePoint(BaseModel):
    ts: str
    close: float
    volume: float


class PriceLatest(BaseModel):
    ts: str
    close: float
    delta_abs: float
    delta_pct: float


class MarketPricesOut(BaseModel):
    ticker: str
    range: str
    prices: list[PricePoint]
    latest: PriceLatest