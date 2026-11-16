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
from collections import OrderedDict
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
MAX_CHAINS = 10  # a chain is big (every expiry's strikes): only the last few are kept
BUILD_SECONDS = 30.0
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


# A chain by expiry (ISO date): (strike, call symbol, put symbol) rows, not
# tastytrade's dicts. SPY's or SPX's lists every expiry's strikes, and ten
# are kept on a 512 MB machine.
Chain = dict[str, list[tuple[float, str, str]]]
_chains: OrderedDict[str, tuple[float, Chain]] = OrderedDict()
_live: dict[tuple[str, date], tuple[float, LiveChain]] = {}
# One build at a time per symbol and expiry; others don't wait on it. A
# lock stays while anyone holds or waits on it (counted: asyncio marks a
# lock free before the waiter it wakes has taken it).
_locks: dict[tuple[str, date], asyncio.Lock] = {}
_users: dict[tuple[str, date], int] = {}


def reset() -> None:
    """Forget what's cached (tests)."""
    _chains.clear()
    _live.clear()
    _locks.clear()
    _users.clear()


def _remember_chain(symbol: str, chain: Chain) -> None:
    """Keep a chain CHAIN_SECONDS, and only the MAX_CHAINS newest."""
    now = _clock()
    for old in [s for s, (at, _) in _chains.items() if now - at >= CHAIN_SECONDS]:
        del _chains[old]
    _chains[symbol] = (now, chain)
    _chains.move_to_end(symbol)
    while len(_chains) > MAX_CHAINS:
        _chains.popitem(last=False)


def _forget_old_quotes() -> None:
    """tastytrade's quotes leave memory once they're past use."""
    for old in [k for k, (at, _) in _live.items() if _clock() - at >= CACHE_SECONDS]:
        del _live[old]


def _tastytrade_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "/").replace(".", "/")


def _rows(expiration: dict[str, Any]) -> list[tuple[float, str, str]]:
    rows = []
    strikes = field_of(expiration, "strikes")
    for strike in strikes if isinstance(strikes, list) else []:
        if not isinstance(strike, dict):
            continue
        k = finite_number(field_of(strike, "strike-price"))
        call, put = field_of(strike, "call"), field_of(strike, "put")
        if k is not None and isinstance(call, str) and isinstance(put, str):
            rows.append((k, call, put))
    return rows


async def _expirations(symbol: str) -> Chain:
    """The standard chain (a non-standard deliverable is left out) as plain
    rows by expiry, kept CHAIN_SECONDS."""
    cached = _chains.get(symbol)
    if cached is not None and _clock() - cached[0] < CHAIN_SECONDS:
        return cached[1]
    payload = await tt.get(f"/option-chains/{tt.symbol_path(symbol)}/nested", op="option_chain")
    chain: Chain = {}
    for item in items_of(payload, strict=True):
        shares = finite_number(field_of(item, "shares-per-contract"))
        if shares not in (None, STANDARD_DELIVERABLE):
            continue
        found = field_of(item, "expirations")
        for expiration in found if isinstance(found, list) else []:
            day = field_of(expiration, "expiration-date") if isinstance(expiration, dict) else None
            if isinstance(day, str):
                chain.setdefault(day, []).extend(_rows(expiration))
    _remember_chain(symbol, chain)
    return chain


def _strikes(chain: Chain, expiry: date, root: str) -> list[tuple[float, str, str]]:
    """(strike, call symbol, put symbol) for ``expiry``, one per strike; a
    symbol that isn't an OCC one for that expiry is dropped, so nothing else
    reaches a query. Where two roots list a strike (an adjusted root that
    still declares 100 shares, SPX beside SPXW), the standard one is kept:
    ``root`` itself, else one without a digit; so no strike counts twice."""
    by_strike: dict[float, tuple[int, str, str]] = {}
    for k, call, put in chain.get(expiry.isoformat(), []):
        try:
            parsed = [parse_occ(s) for s in (call, put)]
        except ValueError:
            continue
        if any(p.expiry != expiry for p in parsed):
            continue
        found_root = parsed[0].root
        rank = 0 if found_root == root else 1 if not any(c.isdigit() for c in found_root) else 2
        if k not in by_strike or rank < by_strike[k][0]:
            by_strike[k] = (rank, call, put)
    return sorted((k, call, put) for k, (_rank, call, put) in by_strike.items())


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
    strikes = _strikes(await _expirations(symbol), expiry, symbol.upper().replace("-", "").replace(".", ""))
    if not strikes:
        raise NotListed(expiry)
    underlying = _tastytrade_symbol(symbol)
    equity = (await _quotes("equity", [underlying])).get(underlying, {})
    # tastytrade's own price only: Yahoo's delayed one isn't passed off as live.
    spot = finite_number(field_of(equity, "mark")) or finite_number(field_of(equity, "mid"))
    if spot is None or spot <= 0:
        raise LiveChainUnavailable("tastytrade sent no price for the underlying")
    cached = options_report.cached_underlying(symbol)  # the dividend yield only
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
    _forget_old_quotes()
    _users[key] = _users.get(key, 0) + 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with asyncio.timeout(BUILD_SECONDS), lock:
            cached = _live.get(key)
            if cached is not None and _clock() - cached[0] < CACHE_SECONDS:
                return cached[1]
            built = await _build(symbol, expiry)
            _live[key] = (_clock(), built)
            return built
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound, TimeoutError) as exc:
        raise LiveChainUnavailable(failure_reason(exc)) from exc
    finally:
        _users[key] -= 1
        if _users[key] == 0:  # no lock left behind per expiry ever asked
            del _users[key]
            _locks.pop(key, None)
