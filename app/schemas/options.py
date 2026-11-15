"""Response schemas for the options routes (ADR 0008)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class FailedTicker(BaseModel):
    symbol: str
    reason: str = Field(description="the exception's class name; details are in the server log")


class SnapshotRun(BaseModel):
    """What one daily IV snapshot run did. The cron reads ``status`` and
    the lists; ``market_open`` and a mostly failed run fail the job."""

    status: Literal["ok", "no_new_session", "market_open"]
    session_date: date | None = Field(description="the trading day the run snapshots; None while the market is open")
    targets: list[str]
    written: list[str]
    skipped: list[str] = Field(description="already stored for this trading day")
    no_options: list[str]
    no_usable_quotes: list[str]
    failed: list[FailedTicker]
    deferred: list[str] = Field(description="not reached: Yahoo throttled the run, or it ran out of time")
    duration_ms: float
