"""Response shapes for the public read-only demo (app/services/demo.py)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DemoSymbol(BaseModel):
    """One ticker the demo can show."""

    symbol: str = Field(min_length=1, max_length=16)
    name: str | None = None
    generated_at: datetime


class DemoIndex(BaseModel):
    """The demo tickers that have a stored report; empty when the demo is off."""

    symbols: list[DemoSymbol] = Field(default_factory=list)
