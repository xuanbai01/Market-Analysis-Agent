"""
Every expiry, live (options PR 5, ADR 0009): the owner's whole option
chain from tastytrade, out to MAX_DAYS, for strikes within STRIKE_RANGE of
the price.

- **Strikes:** from tastytrade's nested chain (owner_live_chain keeps it,
  standard deliverables only, one root per strike, OCC-checked). Each
  contract's DXLink name is worked out from its checked OCC symbol
  (``owner_live_chain.dxlink_name``), so nothing unchecked from tastytrade's
  answer reaches a subscription.
- **Quotes and open interest:** over DXLink, one session of Quote events
  and one of Summary events for every contract at once (SPY: 4,816
  contracts in 19 expiries, about 3.5 s a session, checked on Fly
  2026-11-16 printing counts only). REST would take dozens of calls.
- **Everything else** is the options page's own code: each expiry's
  forward, our own IVs and smile from the mids (``options_metrics.smile``),
  its summary row (``options_analysis.expiry_summary``: ATM IV, expected
  move, max pain, net gamma), and the positioning added up across the
  expiries (``options_positioning.across``). Times run from now
  (``market_calendar.live_quote_time``): the quotes are real time.

tastytrade's data is the owner's alone: behind the owner key, the result
kept CACHE_SECONDS in memory for at most MAX_SYMBOLS symbols, never stored,
never in a prompt or the demo, logged as counts only. It's read on demand,
one underlying at a time, never in the background (tastytrade's terms
§8(3): no large cross-sections collected).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.schemas.options import ExpirySummary
from app.schemas.owner import WholeChain
from app.services import dxlink, options_chain, options_metrics, options_report
from app.services import market_calendar as mc
from app.services import options_analysis as oa
from app.services import options_positioning as op
from app.services import owner_live_chain as lc
from app.services import tastytrade_client as tt
from app.services.options_chain import ExpiryQuotes, Quote
from app.services.options_metrics import Smile
from app.services.owner_positions import failure_reason, finite_number

logger = logging.getLogger(__name__)

MAX_DAYS = 120  # four months: most open interest and nearly all gamma
STRIKE_RANGE = 0.15  # strikes within 15% of the price
SHOWN_RANGE = 0.10  # the by-strike rows the page draws
# Contracts in one read; nearest expiries first. SPY within 15% is 4,816.
MAX_OPTIONS = 6_000
CACHE_SECONDS = 60.0  # open interest is a day's; quotes move, but this is read on demand
MAX_SYMBOLS = 4
BUILD_SECONDS = 60.0  # the chain, the price and two DXLink sessions of up to 20 s
# Builds at once across symbols: DXLink takes one session at a time anyway,
# and each build holds a parsed chain while it waits.
MAX_BUILDS = 1
# A quote time this far ahead of now is no time.
FUTURE_SKEW_SECONDS = 86_400

_TT_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:/[A-Z0-9]{1,4})?")


class WholeChainUnavailable(Exception):
    """tastytrade or its feed didn't answer, or isn't set up; the reason is
    safe to show."""


class NoOptions(Exception):
    """tastytrade lists no options on the symbol within MAX_DAYS, or it isn't a ticker."""


def _now() -> datetime:
    return datetime.now(UTC)


def _clock() -> float:
    return time.monotonic()


_kept: OrderedDict[str, tuple[float, WholeChain]] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}
_users: dict[str, int] = {}
_builds: asyncio.Semaphore | None = None


def _building() -> asyncio.Semaphore:
    global _builds
    if _builds is None:
        _builds = asyncio.Semaphore(MAX_BUILDS)
    return _builds


def reset() -> None:
    """Tests only."""
    global _builds
    _kept.clear()
    _locks.clear()
    _users.clear()
    _builds = None


@dataclass(frozen=True)
class _Expiry:
    expiry: date
    strikes: tuple[tuple[float, str, str], ...]  # (strike, call's DXLink name, put's)


def pick(chain: lc.Chain, root: str, spot: float, quoted_at: datetime) -> tuple[list[_Expiry], bool]:
    """The expiries out to MAX_DAYS, nearest first, each with its strikes
    within STRIKE_RANGE and their DXLink names; stops at MAX_OPTIONS.
    Returns (picked, capped). CPU (it parses each symbol in range): run on
    the options thread."""
    picked: list[_Expiry] = []
    budget = MAX_OPTIONS
    low, high = spot * (1 - STRIKE_RANGE), spot * (1 + STRIKE_RANGE)
    for day in sorted(chain):
        expiry = date.fromisoformat(day)
        years = mc.years_to_expiry(quoted_at, expiry)
        if years <= 0 or years * 365 > MAX_DAYS:
            continue
        strikes = tuple(
            (k, lc.dxlink_name(call), lc.dxlink_name(put))
            for k, call, put in lc.standard_strikes(chain, expiry, root, low, high)
        )
        if not strikes:
            continue
        if 2 * len(strikes) > budget:
            if not picked:  # the nearest expiry alone is too big: its strikes nearest the price
                nearest = sorted(strikes, key=lambda s: abs(s[0] - spot))[: budget // 2]
                picked.append(_Expiry(expiry, tuple(sorted(nearest))))
            return picked, True
        budget -= 2 * len(strikes)
        picked.append(_Expiry(expiry, strikes))
    return picked, False


def _quote(strike: float, quote: dict[str, Any] | None, summary: dict[str, Any] | None) -> Quote:
    bid = finite_number((quote or {}).get("bidPrice"))
    ask = finite_number((quote or {}).get("askPrice"))
    oi = finite_number((summary or {}).get("openInterest"))
    # Open interest beyond any real contract's is no figure (it would overflow the sums).
    oi = oi if oi is not None and 0 <= oi <= lc.MAX_OPEN_INTEREST else 0
    return Quote(strike=strike, bid=max(bid or 0.0, 0.0), ask=max(ask or 0.0, 0.0), volume=0,
                 open_interest=int(oi), regular=True)


def _newest(quotes: dict[str, dict[str, Any]], now: datetime) -> datetime | None:
    """The newest quote time, ignoring one that isn't a time or is ahead of now."""
    latest = now.timestamp() + FUTURE_SKEW_SECONDS
    stamps = [finite_number(q.get(f)) for q in quotes.values() for f in ("bidTime", "askTime")]
    seconds = [s / 1000 for s in stamps if s is not None and 0 < s / 1000 <= latest]
    try:
        return datetime.fromtimestamp(max(seconds), UTC) if seconds else None
    except (OverflowError, OSError, ValueError):
        return None


def assemble(
    picked: Sequence[_Expiry], quotes: dict[str, dict[str, Any]], summaries: dict[str, dict[str, Any]],
    spot: float, quoted_at: datetime, rate: float, dividend_yield: float,
) -> tuple[list[ExpirySummary], list[tuple[ExpiryQuotes, Smile]], list[date], int]:
    """Each expiry through the options page's own code. Returns (summary rows,
    (quotes, smile) for the positioning, expiries without a usable smile,
    contracts that sent both a quote and open interest). CPU: run on the
    options thread."""
    rows: list[ExpirySummary] = []
    parts: list[tuple[ExpiryQuotes, Smile]] = []
    left_out: list[date] = []
    quoted = 0
    for e in picked:
        # A strike with no quote on either side isn't a $0.00 row.
        both = [(k, c, p) for k, c, p in e.strikes if c in quotes and p in quotes]
        quoted += sum(1 for _k, c, p in both for name in (c, p) if name in summaries)
        chain = ExpiryQuotes(
            expiry=e.expiry,
            calls=tuple(_quote(k, quotes.get(c), summaries.get(c)) for k, c, _ in both),
            puts=tuple(_quote(k, quotes.get(p), summaries.get(p)) for k, _, p in both),
        )
        smile = options_metrics.smile(chain, spot, quoted_at, rate, dividend_yield) if both else None
        if smile is None:
            left_out.append(e.expiry)
            continue
        rows.append(oa.expiry_summary(chain, smile, None, quoted_at))
        parts.append((chain, smile))
    return rows, parts, left_out, quoted


def _shown(parts: list[tuple[ExpiryQuotes, Smile]], spot: float) -> list[float]:
    strikes = {q.strike for chain, _ in parts for q in (*chain.calls, *chain.puts)}
    return sorted(k for k in strikes if abs(k / spot - 1) <= SHOWN_RANGE)


async def _build(key: str) -> WholeChain:
    """``key`` is the upper-cased ticker: the chain and report caches are keyed so."""
    now = _now()
    quoted_at = mc.live_quote_time(now)  # tastytrade's quotes are real time
    chain = await lc.expirations(key)
    if not any(0 < mc.years_to_expiry(quoted_at, date.fromisoformat(d)) * 365 <= MAX_DAYS for d in chain):
        raise NoOptions(key)
    spot = await lc.underlying_price(key)
    root = key.replace("-", "").replace(".", "")
    picked, capped = await options_chain.on_options_thread(pick, chain, root, spot, quoted_at)
    if not picked:
        raise NoOptions(key)
    names = [name for e in picked for _k, c, p in e.strikes for name in (c, p)]
    # One session at a time on the machine (dxlink): quotes, then open interest.
    quotes = await dxlink.fetch_once("Quote", names)
    if not quotes:
        raise WholeChainUnavailable("tastytrade's feed sent no quotes")  # not an empty chain kept a minute
    summaries = await dxlink.fetch_once("Summary", names)
    rate, _assumed = await options_chain.on_options_thread(options_chain.risk_free_rate)
    cached = options_report.cached_underlying(key)  # the dividend yield only
    rows, parts, left_out, quoted = await options_chain.on_options_thread(
        assemble, picked, quotes, summaries, spot, quoted_at, rate, cached[1] if cached else 0.0)
    positioning = await options_chain.on_options_thread(op.across, parts, spot, _shown(parts, spot))
    logger.info("owner whole chain: %d expiries, %d left out, %d contracts asked, %d quoted",
                len(rows), len(left_out), len(names), quoted)
    return WholeChain(
        symbol=key, spot=spot, quoted_at=quoted_at, as_of=now, updated_at=_newest(quotes, now), expiries=rows,
        positioning=positioning, max_days=MAX_DAYS, strike_range=STRIKE_RANGE, options_read=len(names),
        options_quoted=quoted, left_out=left_out, capped=capped,
    )


def _forget_expired() -> None:
    now = _clock()
    for old in [s for s, (at, _) in _kept.items() if now - at >= CACHE_SECONDS]:
        del _kept[old]


def _keep(key: str, whole: WholeChain) -> None:
    _kept[key] = (_clock(), whole)
    _kept.move_to_end(key)
    while len(_kept) > MAX_SYMBOLS:
        _kept.popitem(last=False)


async def whole_chain(symbol: str) -> WholeChain:
    """``symbol``'s whole chain out to MAX_DAYS, at most CACHE_SECONDS old.
    ``NoOptions`` when tastytrade lists none (or it isn't a ticker);
    ``WholeChainUnavailable`` with the reason otherwise."""
    if not tt.is_configured():
        raise WholeChainUnavailable("tastytrade isn't set up on the server")
    key = symbol.upper()
    if not _TT_SYMBOL.fullmatch(key.replace("-", "/").replace(".", "/")):
        raise NoOptions(symbol)
    _forget_expired()
    _users[key] = _users.get(key, 0) + 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with asyncio.timeout(BUILD_SECONDS), lock:
            kept = _kept.get(key)
            if kept is not None and _clock() - kept[0] < CACHE_SECONDS:
                return kept[1]
            async with _building():  # one whole chain at a time across symbols
                built = await _build(key)
            _keep(key, built)
            return built
    except TimeoutError as exc:
        logger.warning("owner whole chain: gave up after %.0f s", BUILD_SECONDS)  # no symbol
        raise WholeChainUnavailable(failure_reason(exc)) from exc
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound) as exc:
        raise WholeChainUnavailable(failure_reason(exc)) from exc
    except lc.LiveChainUnavailable as exc:
        raise WholeChainUnavailable(str(exc)) from exc
    except dxlink.DxlinkError as exc:
        raise WholeChainUnavailable(f"tastytrade's feed failed: {exc}") from exc
    finally:
        _users[key] -= 1
        if _users[key] == 0:  # no lock left behind per symbol ever asked
            del _users[key]
            _locks.pop(key, None)
