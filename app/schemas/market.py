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