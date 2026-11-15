"""
Yahoo's option chains, read into plain values (ADR 0008).

One ``option_chain()`` call with no date returns the list of expiries,
the front expiry's chain and the underlying quote; every other expiry is
one more call, so callers pick only the expiries they need. Daily closes
come along for realized volatility. Everything here is blocking (yfinance
is), and callers run it on the options thread.

Yahoo's own ``impliedVolatility`` column is not read: on illiquid strikes
it was junk (up to 154%), so every IV is computed from bid and ask in
``options_metrics``.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypeVar

from app.services import market_calendar as mc

logger = logging.getLogger(__name__)

# The 13-week Treasury bill yield when ^IRX can't be read. A wrong rate
# moves a 30-day IV by a few hundredths of a point.
ASSUMED_RATE = 0.04
RATE_TTL_SECONDS = 12 * 3600
HISTORY_PERIOD = "6mo"  # the snapshot's realized vol; the page asks for 2y (past reports)
_REGULAR = "REGULAR"
# Only a stock has earnings; Yahoo answers a fund's calendar with a 404
# that yfinance logs as an error.
_EQUITY = "EQUITY"


@dataclass(frozen=True)
class Quote:
    strike: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    # False for an adjusted contract (after a split or merger), whose
    # deliverable isn't 100 shares; those never price an IV.
    regular: bool

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class ExpiryQuotes:
    expiry: date
    calls: tuple[Quote, ...]
    puts: tuple[Quote, ...]


@dataclass(frozen=True)
class ChainFetch:
    symbol: str
    spot: float
    market_time: int  # epoch seconds of the underlying quote
    dividend_yield: float  # trailing, as a fraction; only for the forward's fallback
    expiries: tuple[date, ...]  # every expiry Yahoo lists
    chains: dict[date, ExpiryQuotes]  # the picked ones
    closes: tuple[tuple[date, float], ...]  # daily closes, oldest first
    next_earnings: date | None = None  # from Yahoo's calendar; None for a fund
    name: str | None = None
    quote_type: str | None = None  # "EQUITY", "ETF"...
    earnings_estimated: bool = False  # Yahoo marks the next report date as an estimate


class SymbolNotFound(Exception):
    """Yahoo lists neither options nor prices for the symbol."""


# Which listed expiries to fetch, given all of them and the underlying's
# quote (the page reads a stock's earnings schedule before choosing).
ExpiryPicker = Callable[[tuple[date, ...], dict[str, Any]], Sequence[date]]


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _quotes(frame: Any) -> tuple[Quote, ...]:
    rows = frame[["strike", "bid", "ask", "volume", "openInterest", "contractSize"]].to_numpy().tolist()
    return tuple(
        Quote(
            strike=_number(strike),
            bid=_number(bid),
            ask=_number(ask),
            volume=int(_number(volume)),
            open_interest=int(_number(open_interest)),
            regular=size == _REGULAR,
        )
        for strike, bid, ask, volume, open_interest, size in rows
    )


def _next_earnings(ticker: Any, today: date) -> date | None:
    """The first upcoming date in ``calendar["Earnings Date"]`` (Yahoo's
    JSON calendar, not the scraped earnings page). Never fails the chain."""
    try:
        calendar = ticker.calendar
        raw = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
        values = raw if isinstance(raw, list | tuple) else [raw]
        days = [d.date() if isinstance(d, datetime) else d for d in values if isinstance(d, date)]
        return min((d for d in days if d >= today), default=None)
    except Exception:
        logger.warning("could not read the earnings calendar", exc_info=True)
        return None


def _dividend_yield(underlying: dict[str, Any]) -> float:
    """``trailingAnnualDividendYield`` is a fraction (KO 0.0216) beside
    ``dividendYield`` in percent (2.14); a value above 1 is read as a percent,
    since a percent taken as a fraction would make the fallback forward
    100 times wrong."""
    value = _number(underlying.get("trailingAnnualDividendYield"))
    return value / 100 if value > 1 else value


def _fetch_yfinance_chain(
    symbol: str, pick: ExpiryPicker, history_period: str, read_calendar: bool
) -> ChainFetch | None:
    import yfinance  # noqa: PLC0415  -- lazy: tests swap in a fake module

    ticker = yfinance.Ticker(symbol)
    front = ticker.option_chain()
    if front.calls is None:
        # No listed options, or a symbol Yahoo doesn't know: prices tell them apart.
        if ticker.history(period="5d", auto_adjust=True)["Close"].dropna().empty:
            raise SymbolNotFound(symbol)
        return None
    underlying = front.underlying or {}
    listed = tuple(sorted(date.fromisoformat(e) for e in ticker.options))
    chains: dict[date, ExpiryQuotes] = {}
    for expiry in pick(listed, underlying):
        if expiry not in listed or expiry in chains:
            continue
        chain = front if expiry == listed[0] else ticker.option_chain(expiry.isoformat())
        if chain.calls is not None and chain.puts is not None:  # one side missing: drop the expiry
            chains[expiry] = ExpiryQuotes(expiry, _quotes(chain.calls), _quotes(chain.puts))
    history = ticker.history(period=history_period, auto_adjust=True)
    closes = tuple(
        (day, _number(close))
        for day, close in zip(history.index.date, history["Close"].tolist(), strict=False)
        if _number(close) > 0
    )
    market_time = int(_number(underlying.get("regularMarketTime")))
    # Today, not the last print's date: a thin name last traded days ago
    # would keep an earnings date that has passed.
    today = datetime.now(mc.ET).date()
    return ChainFetch(
        symbol=symbol,
        spot=_number(underlying.get("regularMarketPrice")),
        market_time=market_time,
        dividend_yield=_dividend_yield(underlying),
        expiries=listed,
        chains=chains,
        closes=closes,
        next_earnings=(
            _next_earnings(ticker, today) if read_calendar and underlying.get("quoteType") == _EQUITY else None
        ),
        name=underlying.get("longName") or underlying.get("shortName"),
        quote_type=underlying.get("quoteType"),
        earnings_estimated=bool(underlying.get("isEarningsDateEstimate")),
    )


ChainProvider = Callable[[str, ExpiryPicker, str, bool], "ChainFetch | None"]
PROVIDERS: dict[str, ChainProvider] = {"yfinance": _fetch_yfinance_chain}


def fetch_chain(
    symbol: str,
    pick: ExpiryPicker,
    *,
    history_period: str = HISTORY_PERIOD,
    read_calendar: bool = True,
    provider: str = "yfinance",
) -> ChainFetch | None:
    """The chains of ``symbol`` for the expiries ``pick`` chooses; None
    when the symbol lists no options; ``SymbolNotFound`` when Yahoo knows
    no such symbol. ``read_calendar=False`` skips the earnings-calendar
    call (the page has the schedule). Blocking."""
    return PROVIDERS[provider](symbol, pick, history_period, read_calendar)


# Every options fetch and computation runs on this one thread: off the
# event loop, and one Yahoo call at a time (the page and the daily run).
_OPTIONS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="options")
_T = TypeVar("_T")


async def on_options_thread(fn: Callable[..., _T], *args: Any) -> _T:
    return await asyncio.get_running_loop().run_in_executor(_OPTIONS_EXECUTOR, fn, *args)


def _fetch_yfinance_irx() -> float | None:
    import yfinance  # noqa: PLC0415

    closes = yfinance.Ticker("^IRX").history(period="5d")["Close"].dropna().tolist()
    return float(closes[-1]) if closes else None


# Swapped in tests.
fetch_irx: Callable[[], float | None] = _fetch_yfinance_irx

_rate_cache: tuple[float, float] | None = None  # (rate, expires_at monotonic)


def clear_rate_cache() -> None:
    global _rate_cache
    _rate_cache = None


def risk_free_rate() -> tuple[float, bool]:
    """(rate, assumed): the 13-week T-bill yield from ^IRX as a fraction,
    cached for 12 hours, or ``ASSUMED_RATE`` with assumed=True when it
    can't be read. Blocking."""
    global _rate_cache
    now = time.monotonic()
    if _rate_cache is not None and _rate_cache[1] > now:
        return _rate_cache[0], False
    try:
        percent = fetch_irx()
    except Exception:
        logger.warning("could not read ^IRX; assuming a %.2f rate", ASSUMED_RATE, exc_info=True)
        percent = None
    if percent is None or not 0 <= percent < 25:
        return ASSUMED_RATE, True
    _rate_cache = (percent / 100, now + RATE_TTL_SECONDS)
    return percent / 100, False
