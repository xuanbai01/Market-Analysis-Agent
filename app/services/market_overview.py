"""
The market strip: headline quotes plus a fear & greed estimate.

``get_market_overview`` returns the latest close and day change for a
fixed list of indices, rates, commodities and crypto, and the sentiment
estimate from ``market_sentiment``. Both come from yfinance daily bars.

Every page load asks for this, so results are kept in memory: quotes
for 5 minutes, the sentiment estimate (built from daily closes) for an
hour. A failed fetch serves the last good value if there is one, and
the strip simply shrinks if there isn't — this endpoint never errors
because a provider did.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import monotonic
from typing import Any

from app.core.observability import log_external_call
from app.schemas.market_overview import (
    MarketOverview,
    MarketQuote,
    QuoteKind,
    QuoteUnit,
    SentimentEstimate,
)
from app.services.market_sentiment import estimate_sentiment

Closes = list[tuple[date, float]]


@dataclass(frozen=True)
class QuoteSpec:
    symbol: str
    label: str
    kind: QuoteKind
    unit: QuoteUnit


# Strip order: the big three US indices and their fear gauge first.
QUOTE_SPECS: tuple[QuoteSpec, ...] = (
    QuoteSpec("^GSPC", "S&P 500", "index", "points"),
    QuoteSpec("^NDX", "Nasdaq 100", "index", "points"),
    QuoteSpec("^DJI", "Dow Jones", "index", "points"),
    QuoteSpec("^VIX", "VIX", "volatility", "points"),
    QuoteSpec("^RUT", "Russell 2000", "index", "points"),
    QuoteSpec("^TNX", "US 10Y", "rate", "percent"),
    QuoteSpec("DX-Y.NYB", "US dollar", "currency", "points"),
    QuoteSpec("GC=F", "Gold", "commodity", "usd"),
    QuoteSpec("CL=F", "WTI crude", "commodity", "usd"),
    QuoteSpec("BTC-USD", "Bitcoin", "crypto", "usd"),
)

# Inputs to the sentiment estimate. IEF = 7–10y Treasuries, HYG = US
# high-yield corporates; total-return (dividend-adjusted) closes.
SENTIMENT_SYMBOLS = {"spx": "^GSPC", "vix": "^VIX", "treasuries": "IEF", "high_yield": "HYG"}

QUOTES_PERIOD = "5d"  # enough for a previous close across a long weekend
SENTIMENT_PERIOD = "2y"  # a year of ranks on top of a 125-day average
QUOTES_TTL_SECONDS = 300.0
SENTIMENT_TTL_SECONDS = 3600.0

_YFINANCE_DOWNLOAD_LOCK = threading.Lock()


def _fetch_yfinance_closes(
    symbols: Sequence[str], period: str, adjusted: bool
) -> dict[str, Closes]:
    """Daily closes per symbol, ascending, NaNs dropped. Sync (yfinance)."""
    import yfinance as yf

    # yf.download keeps per-call results in module-level state, so two
    # downloads running at once (quotes + sentiment) can mix them up.
    with _YFINANCE_DOWNLOAD_LOCK:
        frame = yf.download(
            list(symbols),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=adjusted,
            progress=False,
            threads=True,
        )
    out: dict[str, Closes] = {}
    for symbol in symbols:
        try:
            closes = frame[symbol]["Close"].dropna()
        except KeyError:
            continue
        points = [(ts.date(), float(value)) for ts, value in closes.items()]
        if points:
            out[symbol] = points
    return out


# Swapped out in tests.
fetch_closes: Callable[[Sequence[str], str, bool], dict[str, Closes]] = _fetch_yfinance_closes


def build_quote(spec: QuoteSpec, closes: Closes) -> MarketQuote | None:
    """Latest close vs the one before it; None without two closes."""
    if len(closes) < 2:
        return None
    (_, previous), (as_of, price) = closes[-2], closes[-1]
    change = price - previous
    return MarketQuote(
        symbol=spec.symbol,
        label=spec.label,
        kind=spec.kind,
        unit=spec.unit,
        price=price,
        change=change,
        change_percent=change / previous * 100 if previous else 0.0,
        as_of=as_of,
    )


@dataclass
class _Entry:
    value: Any
    expires_at: float


_cache: dict[str, _Entry] = {}


def clear_cache() -> None:
    _cache.clear()


async def _download(purpose: str, symbols: Sequence[str], period: str, adjusted: bool) -> dict[str, Closes]:
    with log_external_call(
        "yfinance.download",
        {"purpose": purpose, "symbols": len(symbols), "period": period},
    ) as call:
        closes = await asyncio.to_thread(fetch_closes, symbols, period, adjusted)
        call.record_output({"symbols_returned": len(closes)})
    return closes


async def _cached(key: str, ttl: float, load: Callable[[], Any], empty: Any) -> Any:
    """Fresh value, else a reload; on a failed or empty reload, the stale value."""
    now = monotonic()
    entry = _cache.get(key)
    if entry and entry.expires_at > now:
        return entry.value
    try:
        value = await load()
    except Exception:  # logged by log_external_call; serve what we have
        value = empty
    if value != empty:
        _cache[key] = _Entry(value, now + ttl)
        return value
    return entry.value if entry else empty


async def _load_quotes() -> list[MarketQuote]:
    closes = await _download("market_overview.quotes", [s.symbol for s in QUOTE_SPECS], QUOTES_PERIOD, False)
    quotes = (build_quote(spec, closes.get(spec.symbol, [])) for spec in QUOTE_SPECS)
    return [q for q in quotes if q is not None]


async def _load_sentiment() -> SentimentEstimate | None:
    closes = await _download("market_overview.sentiment", list(SENTIMENT_SYMBOLS.values()), SENTIMENT_PERIOD, True)
    series = {name: closes.get(symbol, []) for name, symbol in SENTIMENT_SYMBOLS.items()}
    return estimate_sentiment(**series)


async def get_market_overview() -> MarketOverview:
    quotes, sentiment = await asyncio.gather(
        _cached("quotes", QUOTES_TTL_SECONDS, _load_quotes, []),
        _cached("sentiment", SENTIMENT_TTL_SECONDS, _load_sentiment, None),
    )
    return MarketOverview(quotes=quotes, sentiment=sentiment, generated_at=datetime.now(UTC))
