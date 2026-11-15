"""
Yahoo's ``Ticker.info``, read again when it comes back cut short.

Yahoo sometimes answers ``info`` with only part of its fields. One KO
fetch on 2026-11-13 had no price-to-sales, EV/EBITDA or gross margin, and
the report showed dashes in those cells until it was regenerated.

Price-to-sales is the marker: every company with revenue has one, banks
and loss-makers included (they lack gross margin, EV/EBITDA or a P/E for
real). So an answer with a market cap but no price-to-sales was cut
short; ``read_info`` reads it once more and fills in what the second
answer has. Sync, like the rest of the yfinance code (callers run it on a
thread).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

PARTIAL_MARKER = "priceToSalesTrailing12Months"


def _info(ticker: Any) -> dict[str, Any]:
    return getattr(ticker, "info", {}) or {}


def is_partial(info: dict[str, Any]) -> bool:
    return info.get("marketCap") is not None and info.get(PARTIAL_MARKER) is None


def read_info(symbol: str, ticker: Any, fresh_ticker: Callable[[], Any]) -> dict[str, Any]:
    """``ticker.info``; if that was cut short, the same with the gaps
    filled from a second read on ``fresh_ticker()`` (a Ticker caches its
    info, so a retry needs a new one)."""
    info = _info(ticker)
    if not is_partial(info):
        return info
    logger.info("yahoo info for %s came back without %s; reading it again", symbol, PARTIAL_MARKER)
    retry = _info(fresh_ticker())
    return {**info, **{key: value for key, value in retry.items() if value is not None}}
