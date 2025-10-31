from pydantic import BaseModel
from typing import Optional


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
    rsi: Optional[float] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None


class MarketSnapshotOut(BaseModel):
    symbol: str
    as_of: str
    ohlcv: OHLCV
    technicals: Technicals | None = None


class MarketHistoryOut(BaseModel):
    symbol: str
    interval: str
    bars: list[OHLCV]