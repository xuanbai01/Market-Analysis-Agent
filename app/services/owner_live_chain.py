"""One expiry's option chain, live from tastytrade, for the owner (ADR 0009,
PR B).

The options page reads Yahoo's chain, 15 minutes delayed in a session.
With the owner key it can switch an expiry to tastytrade's live quotes:
the strikes come from tastytrade's nested chain (kept CHAIN_SECONDS), the
bids, asks, volume and open interest from its REST quotes for the
STRIKES_EACH_SIDE strikes either side of the price, and everything else
(the forward, our own IVs, the smile, positioning) from the same code that
reads Yahoo's chain, so the page draws them the same way.

tastytrade's figures are the owner's alone: kept CACHE_SECONDS in memory,
never stored, never in a prompt (the options read stays on Yahoo's
chain), never in the demo. Logs carry counts only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

from app.schemas.owner import LiveChain
from app.services import market_calendar as mc
from app.services import options_analysis as oa
from app.services import options_chain, options_report
from app.services import options_metrics as om
from app.services import tastytrade_client as tt
from app.services.options_chain import ExpiryQuotes, Quote
from app.services.owner_positions import (
    failure_reason,
    field_of,
    finite_number,
    items_of,
    parse_occ,
)

logger = logging.getLogger(__name__)

CACHE_SECONDS = 10.0
CHAIN_SECONDS = 600.0  # a chain's strikes change rarely
STRIKES_EACH_SIDE = 40
QUOTE_BATCH = 100
STANDARD_DELIVERABLE = 100


class LiveChainUnavailable(Exception):
    """tastytrade isn't set up, didn't answer, or gave nothing to price."""


class NotListed(Exception):
    """tastytrade lists no standard options on the symbol for that expiry."""


# Swapped in tests.
def _clock() -> float:
    return time.monotonic()


def _now() -> datetime:
    return datetime.now(UTC)


_chains: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_live: dict[tuple[str, date], tuple[float, LiveChain]] = {}
_lock = asyncio.Lock()


def reset() -> None:
    """Forget what's cached (tests)."""
    global _lock
    _chains.clear()
    _live.clear()
    _lock = asyncio.Lock()


def _tastytrade_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "/").replace(".", "/")


async def _expirations(symbol: str) -> list[dict[str, Any]]:
    """The standard chain's expirations (a non-standard deliverable is left
    out), kept CHAIN_SECONDS."""
    cached = _chains.get(symbol)
    if cached is not None and _clock() - cached[0] < CHAIN_SECONDS:
        return cached[1]
    payload = await tt.get(f"/option-chains/{tt.symbol_path(symbol)}/nested", op="option_chain")
    expirations: list[dict[str, Any]] = []
    for item in items_of(payload, strict=True):
        shares = finite_number(field_of(item, "shares-per-contract"))
        if shares not in (None, STANDARD_DELIVERABLE):
            continue
        found = field_of(item, "expirations")
        expirations += [e for e in found if isinstance(e, dict)] if isinstance(found, list) else []
    _chains[symbol] = (_clock(), expirations)
    return expirations


def _strikes(expirations: list[dict[str, Any]], expiry: date) -> list[tuple[float, str, str]]:
    """(strike, call symbol, put symbol) for ``expiry``; a symbol that isn't
    an OCC one for that expiry is dropped, so nothing else reaches a query."""
    found: list[tuple[float, str, str]] = []
    for expiration in expirations:
        if field_of(expiration, "expiration-date") != expiry.isoformat():
            continue
        for strike in field_of(expiration, "strikes") or []:
            if not isinstance(strike, dict):
                continue
            k = finite_number(field_of(strike, "strike-price"))
            call, put = field_of(strike, "call"), field_of(strike, "put")
            if k is None or not isinstance(call, str) or not isinstance(put, str):
                continue
            try:
                ok = all(parse_occ(s).expiry == expiry for s in (call, put))
            except ValueError:
                ok = False
            if ok:
                found.append((k, call, put))
    return sorted(set(found))


async def _quotes(kind: str, symbols: list[str]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(symbols), QUOTE_BATCH):
        batch = symbols[start:start + QUOTE_BATCH]
        for item in items_of(await tt.get("/market-data/by-type", {kind: ",".join(batch)}, op="quotes"), strict=True):
            symbol = field_of(item, "symbol")
            if isinstance(symbol, str) and symbol in batch:
                quotes[symbol] = item
    return quotes


def _quote(strike: float, item: dict[str, Any] | None) -> Quote:
    item = item or {}
    count = lambda name: int(max(finite_number(field_of(item, name)) or 0, 0))  # noqa: E731
    return Quote(
        strike=strike,
        bid=max(finite_number(field_of(item, "bid")) or 0.0, 0.0),
        ask=max(finite_number(field_of(item, "ask")) or 0.0, 0.0),
        volume=count("volume"),
        open_interest=count("open-interest"),
        regular=True,
    )


def _newest(items: list[dict[str, Any]]) -> datetime | None:
    stamps = []
    for item in items:
        stamp = field_of(item, "updated-at")
        try:
            when = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except ValueError:
            continue
        if when is not None:
            stamps.append(when if when.tzinfo else when.replace(tzinfo=UTC))
    return max(stamps, default=None)


async def _build(symbol: str, expiry: date) -> LiveChain:
    strikes = _strikes(await _expirations(symbol), expiry)
    if not strikes:
        raise NotListed(expiry)
    underlying = _tastytrade_symbol(symbol)
    equity = (await _quotes("equity", [underlying])).get(underlying, {})
    cached = options_report.cached_underlying(symbol)
    spot = finite_number(field_of(equity, "mark")) or finite_number(field_of(equity, "mid")) or (cached[0] if cached else None)
    if spot is None or spot <= 0:
        raise LiveChainUnavailable("tastytrade sent no price for the underlying")
    near = sorted(strikes, key=lambda s: abs(s[0] - spot))[: 2 * STRIKES_EACH_SIDE]
    near.sort()
    quotes = await _quotes("equity-option", [s for _, call, put in near for s in (call, put)])
    chain = ExpiryQuotes(
        expiry=expiry,
        calls=tuple(_quote(k, quotes.get(call)) for k, call, _ in near),
        puts=tuple(_quote(k, quotes.get(put)) for k, _, put in near),
    )
    now = _now()
    quoted_at = mc.quote_time(now)
    rate, _assumed = await options_chain.on_options_thread(options_chain.risk_free_rate)
    dividend_yield = cached[1] if cached else 0.0
    smile = await options_chain.on_options_thread(om.smile, chain, spot, quoted_at, rate, dividend_yield)
    if smile is None:
        raise LiveChainUnavailable("tastytrade sent no usable quotes for that expiry")
    shown = await options_chain.on_options_thread(oa.expiry_chain, chain, smile, spot)
    logger.info("owner live chain: %d strikes, %d quotes", len(near), len(quotes))
    return LiveChain(
        symbol=symbol, expiry=expiry, spot=spot, quoted_at=quoted_at,
        updated_at=_newest(list(quotes.values())), chain=shown,
    )


async def live_chain(symbol: str, expiry: date) -> LiveChain:
    """``symbol``'s chain for ``expiry`` at tastytrade's quotes, at most
    CACHE_SECONDS old. ``NotListed`` when tastytrade lists no such expiry;
    ``LiveChainUnavailable`` with the reason otherwise."""
    if not tt.is_configured():
        raise LiveChainUnavailable("tastytrade isn't set up on the server")
    key = (symbol, expiry)
    async with _lock:
        cached = _live.get(key)
        if cached is not None and _clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            built = await _build(symbol, expiry)
        except (tt.TastytradeUnavailable, tt.TastytradeNotFound) as exc:
            raise LiveChainUnavailable(failure_reason(exc)) from exc
        _live[key] = (_clock(), built)
        for stale in [k for k, (at, _) in _live.items() if _clock() - at >= CACHE_SECONDS]:
            del _live[stale]  # nothing kept past its use
        return built
