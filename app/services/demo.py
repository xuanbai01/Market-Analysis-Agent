"""
The public read-only demo.

Everything that builds a report sits behind the shared secret, so nobody
but the owner could see the product. The demo opens a narrow window: for
the tickers named in ``DEMO_SYMBOLS``, anyone can read the latest report
already stored and the prices already stored. Nothing here generates a
report, calls the LLM or reaches a data provider, so a visitor cannot
spend money or quota whatever they request.

How the content stays current: the owner opens a demo ticker while
signed in, which builds or rebuilds its report through the normal route;
the demo shows that report from then on, with its date.

**Built to be hammered.** The routes are open, so the cost of one
request has to be close to nothing:

- Responses are cached in memory for five minutes as the **serialized
  bytes**. A report is a large document; validating and serializing it
  per request would let a loop pin the one shared CPU. A hit is a
  dictionary lookup and a write to the socket.
- The cache can only hold keys for listed tickers and the three allowed
  ranges, so a caller can't grow it.
- The routes add ``Cache-Control`` so browsers and proxies repeat less,
  and a per-IP limit (``DEMO_RATE_LIMIT_PER_MINUTE``) slows one caller.

``DEMO_SYMBOLS`` empty (the default) turns the demo off: the index is
empty and every other route answers 404.
"""
from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.schemas.demo import DemoIndex, DemoSymbol
from app.services import market_prices, research_cache, research_orchestrator

# The demo shows full reports only: the dashboard never asks for another.
FOCUS = "full"
CACHE_TTL_SECONDS = 300.0
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


@dataclass(frozen=True)
class StoredReport:
    """A report as it will be sent, plus what the index needs from it."""

    body: bytes
    name: str | None
    generated_at: datetime


_cache: dict[tuple[str, ...], tuple[float, Any]] = {}


def clear_cache() -> None:
    """Forget every cached demo response (tests; a config change)."""
    _cache.clear()


def demo_symbols() -> tuple[str, ...]:
    """The tickers the demo may show, in the order configured. Entries
    that don't look like a ticker are dropped."""
    seen: list[str] = []
    for raw in settings.DEMO_SYMBOLS.split(","):
        symbol = raw.strip().upper()
        if _TICKER.fullmatch(symbol) and symbol not in seen:
            seen.append(symbol)
    return tuple(seen)


def is_demo_symbol(symbol: str) -> bool:
    return symbol.upper() in demo_symbols()


async def _cached(key: tuple[str, ...], load: Callable[[], Awaitable[Any]]) -> Any:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    value = await load()
    _cache[key] = (now + CACHE_TTL_SECONDS, value)
    return value


async def stored_report(session: AsyncSession, symbol: str) -> StoredReport | None:
    """The newest stored full report for a demo ticker, however old,
    serialized once; None for a ticker off the list or with nothing
    stored. Never builds one."""
    target = symbol.upper()
    if not is_demo_symbol(target):
        return None

    async def _load() -> StoredReport | None:
        report = await research_cache.lookup_latest(session, symbol=target, focus=FOCUS)
        if report is None:
            return None
        # The same repairs the signed-in route applies to an older row.
        report = research_orchestrator.backfill_top_level_metadata(report)
        report = research_orchestrator.backfill_layout_signals(report)
        return StoredReport(
            body=report.model_dump_json().encode("utf-8"),
            name=report.name,
            generated_at=report.generated_at,
        )

    return await _cached(("report", target), _load)


async def stored_prices(session: AsyncSession, symbol: str, range_str: str) -> bytes | None:
    """Stored prices for a demo ticker (possibly none), serialized once;
    None for a ticker off the list. Never fetches from the provider."""
    target = symbol.upper()
    if not is_demo_symbol(target):
        return None

    async def _load() -> bytes:
        prices = await market_prices.get_cached_prices(session, target, range_str)
        return prices.model_dump_json().encode("utf-8")

    return await _cached(("prices", target, range_str), _load)


async def index(session: AsyncSession) -> DemoIndex:
    """The demo tickers that have a report to show."""
    entries: list[DemoSymbol] = []
    for symbol in demo_symbols():
        report = await stored_report(session, symbol)
        if report is not None:
            entries.append(DemoSymbol(symbol=symbol, name=report.name, generated_at=report.generated_at))
    return DemoIndex(symbols=entries)
