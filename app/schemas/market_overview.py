"""Response shape for ``GET /v1/market/overview`` — the market strip."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

QuoteKind = Literal["index", "volatility", "rate", "currency", "commodity", "crypto"]
# How to print ``price``: index points, a percent yield, or US dollars.
QuoteUnit = Literal["points", "percent", "usd"]
SentimentRating = Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
SentimentKey = Literal["momentum", "volatility", "safe_haven", "junk_bond_demand"]


class MarketQuote(BaseModel):
    symbol: str
    label: str
    kind: QuoteKind
    unit: QuoteUnit
    price: float
    change: float
    change_percent: float = Field(description="Change vs the previous close, in percent (1.5 = 1.5%).")
    as_of: date = Field(description="Session date of ``price``.")


class SentimentComponent(BaseModel):
    key: SentimentKey
    label: str
    score: float = Field(ge=0, le=100, description="0 = most fearful, 100 = most greedy.")
    description: str


class SentimentEstimate(BaseModel):
    """Our own fear/greed estimate — not CNN's index (see market_sentiment.py)."""

    score: float = Field(ge=0, le=100)
    rating: SentimentRating
    components: list[SentimentComponent]
    as_of: date
    methodology: str


class MarketOverview(BaseModel):
    quotes: list[MarketQuote]
    sentiment: SentimentEstimate | None
    generated_at: datetime
