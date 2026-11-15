"""
The options page's service (ADR 0008): ``GET /v1/options/{symbol}`` and
``/chain/{expiry}``.

One build reads a stock's earnings schedule (cached a day), then the
chains of the expiries ``options_analysis.report_expiries`` picks and two
years of closes, and computes everything on the options thread. The
stored IV30 history and recording the view come after, on the event loop,
so no database connection is held while Yahoo is fetched.

Cached in memory for 15 minutes (Yahoo's quotes are about 15 minutes old
anyway), six hours for a symbol with no options, at most 30 symbols. A
failed rebuild serves the copy from before; with none, it raises (the
route answers 503). Concurrent requests for a symbol share one build.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.schemas.options import ExpiryChain, OptionsReport
from app.services import earnings_calendar, options_chain
from app.services import market_calendar as mc
from app.services import options_analysis as oa
from app.services import options_metrics as om
from app.services import options_snapshot_store as store
from app.services.earnings_calendar import Schedule, reaction_sessions
from app.services.options_chain import ChainFetch, SymbolNotFound
from app.services.options_earnings import event_move, past_moves
from app.services.options_metrics import Smile

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 15 * 60
NO_OPTIONS_TTL_SECONDS = 6 * 3600
CACHE_SIZE = 30
HISTORY_PERIOD = "2y"  # past earnings moves
_SINGLE_EXPIRY_HISTORY = "5d"
_EQUITY = "EQUITY"

# Swapped in tests.
_clock = time.monotonic


def _now() -> datetime:
    return datetime.now(UTC)


class ExpiryNotListed(Exception):
    """Yahoo doesn't list that expiry for the symbol."""


class NoUsableQuotes(Exception):
    """The expiry has no two-sided quotes to price."""


@dataclass
class _Built:
    symbol: str
    fetched: ChainFetch | None
    smiles: dict[date, Smile]
    parts: dict[str, Any]  # OptionsReport fields but history, claims and generated_at


@dataclass
class _Entry:
    report: OptionsReport
    built: _Built
    expires_at: float


_cache: OrderedDict[str, _Entry] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def clear_cache() -> None:
    _cache.clear()
    _locks.clear()


def _fresh(symbol: str) -> _Entry | None:
    entry = _cache.get(symbol)
    return entry if entry is not None and entry.expires_at > _clock() else None


def is_fresh(symbol: str) -> bool:
    return _fresh(symbol) is not None


def _remember(symbol: str, entry: _Entry) -> None:
    _cache[symbol] = entry
    _cache.move_to_end(symbol)
    while len(_cache) > CACHE_SIZE:
        old, _ = _cache.popitem(last=False)
        lock = _locks.get(old)
        if lock is not None and not lock.locked():
            del _locks[old]


def _parts(
    symbol: str,
    fetched: ChainFetch | None,
    smiles: list[Smile],
    schedule: Schedule | None,
    reaction: tuple[date, date] | None,
    quoted_at: datetime,
    rate: float,
    rate_assumed: bool,
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "symbol": symbol, "name": None, "status": "no_options", "spot": None, "quoted_at": quoted_at,
        "rate": rate, "rate_assumed": rate_assumed, "iv30": None, "iv30_extrapolated": False, "iv90": None,
        "skew25": None, "rv20": None, "rv60": None, "put_call_open_interest": None, "put_call_volume": None,
        "expiries": [], "listed_expiries": [], "chain": None, "earnings": None,
    }
    if fetched is None:
        return empty
    spot = fetched.spot if fetched.spot > 0 else next((c for _d, c in reversed(fetched.closes)), None)
    metrics = om.snapshot_metrics(fetched, quoted_at, rate, rate_assumed=rate_assumed, smiles=smiles)
    default = oa.default_smile(smiles)
    put_call_oi, put_call_volume = oa.put_call_ratios(fetched.chains.values())
    earnings = None
    if schedule is not None:
        event = event_move(smiles, quoted_at, reaction, estimated=fetched.earnings_estimated)
        past = past_moves(schedule.past, fetched.closes)
        earnings = oa.earnings_block(schedule, event, past, spot, estimated=fetched.earnings_estimated)
    return {
        **empty,
        "name": fetched.name,
        "status": "ok" if smiles else "no_usable_quotes",
        "spot": spot,
        "iv30": metrics.iv30,
        "iv30_extrapolated": metrics.iv30_extrapolated,
        "iv90": metrics.iv90,
        "skew25": metrics.skew25,
        "rv20": metrics.rv20,
        "rv60": metrics.rv60,
        "put_call_open_interest": put_call_oi,
        "put_call_volume": put_call_volume,
        "expiries": [oa.expiry_summary(fetched.chains[s.expiry], s, reaction) for s in smiles],
        "listed_expiries": list(fetched.expiries),
        "chain": oa.expiry_chain(fetched.chains[default.expiry], default) if default else None,
        "earnings": earnings,
    }


def build(symbol: str, now: datetime) -> _Built:
    """Fetch and compute everything but the stored history. Blocking."""
    quoted_at = mc.quote_time(now)
    rate, rate_assumed = options_chain.risk_free_rate()
    found: dict[str, Any] = {"schedule": None, "reaction": None}

    def pick(listed: tuple[date, ...], quote: dict[str, Any]) -> list[date]:
        if quote.get("quoteType") == _EQUITY:  # a fund has no earnings
            schedule = earnings_calendar.fetch_schedule(symbol)
            found["schedule"] = schedule
            if schedule.next is not None:
                found["reaction"] = reaction_sessions(schedule.next.when.date(), schedule.next.timing)
        return oa.report_expiries(listed, quoted_at, found["reaction"])

    cpu_started = time.thread_time()
    not_found = False
    with log_external_call("yfinance.options", {"symbol": symbol, "purpose": "page"}) as call:
        try:
            fetched = options_chain.fetch_chain(symbol, pick, history_period=HISTORY_PERIOD)
        except SymbolNotFound:
            # An ordinary 404: logged as an outcome, not an error with a traceback.
            call.record_output({"status": "not_found"})
            not_found = True
        else:
            smiles = om.chain_smiles(fetched, quoted_at, rate) if fetched else []
            parts = _parts(symbol, fetched, smiles, found["schedule"], found["reaction"], quoted_at, rate, rate_assumed)
            call.record_output({
                "status": parts["status"],
                "expiries": len(fetched.chains) if fetched else 0,
                "cpu_ms": round((time.thread_time() - cpu_started) * 1000, 1),
            })
    if not_found:
        raise SymbolNotFound(symbol)
    return _Built(symbol, fetched, {s.expiry: s for s in smiles}, parts)


async def _assemble(session: AsyncSession, built: _Built, now: datetime) -> OptionsReport:
    parts = built.parts
    usable = parts["status"] == "ok"
    points = await store.iv30_history(session, built.symbol, om.METHOD_VERSION) if usable else []
    history = oa.iv_history(points, parts["iv30"])
    if usable:
        await store.touch_tracked(session, built.symbol, now)
    chain = parts["chain"]
    default = next((e for e in parts["expiries"] if chain is not None and e.expiry == chain.expiry), None)
    claims = oa.claims(
        iv30=parts["iv30"], iv90=parts["iv90"], rv20=parts["rv20"], rv60=parts["rv60"], skew25=parts["skew25"],
        default=default, put_call_oi=parts["put_call_open_interest"], earnings=parts["earnings"],
        history=history, at=now,
    )
    return OptionsReport(**parts, history=history, claims=claims, generated_at=now)


async def get_report(session: AsyncSession, symbol: str, *, now: datetime | None = None) -> OptionsReport:
    entry = _fresh(symbol)
    if entry is not None:
        return entry.report
    lock = _locks.setdefault(symbol, asyncio.Lock())
    async with lock:
        entry = _fresh(symbol)
        if entry is not None:
            return entry.report
        now = now or _now()
        try:
            built = await options_chain.on_options_thread(build, symbol, now)
        except SymbolNotFound:
            raise
        except Exception:
            stale = _cache.get(symbol)
            if stale is None:
                raise
            logger.exception("options for %s failed; serving the copy from before", symbol)
            return stale.report
        report = await _assemble(session, built, now)
        ttl = NO_OPTIONS_TTL_SECONDS if report.status == "no_options" else CACHE_TTL_SECONDS
        _remember(symbol, _Entry(report, built, _clock() + ttl))
        return report


def _fetch_expiry(symbol: str, expiry: date, built: _Built) -> Smile:
    """Read one more listed expiry into the cached build. Blocking."""
    quoted_at = built.parts["quoted_at"]
    one = options_chain.fetch_chain(symbol, lambda _listed, _quote: [expiry], history_period=_SINGLE_EXPIRY_HISTORY)
    if one is None or expiry not in one.chains or built.fetched is None:
        raise NoUsableQuotes(expiry)
    built.fetched.chains[expiry] = one.chains[expiry]
    s = om.smile(one.chains[expiry], built.fetched.spot, quoted_at, built.parts["rate"], built.fetched.dividend_yield)
    if s is None:
        raise NoUsableQuotes(expiry)
    built.smiles[expiry] = s
    return s


async def get_chain(
    session: AsyncSession, symbol: str, expiry: date, *, now: datetime | None = None
) -> ExpiryChain:
    await get_report(session, symbol, now=now)
    built = _cache[symbol].built
    if built.fetched is None or expiry not in built.fetched.expiries:
        raise ExpiryNotListed(expiry)
    s = built.smiles.get(expiry)
    if s is None:
        if expiry in built.fetched.chains:
            raise NoUsableQuotes(expiry)
        s = await options_chain.on_options_thread(_fetch_expiry, symbol, expiry, built)
    return await options_chain.on_options_thread(oa.expiry_chain, built.fetched.chains[expiry], s)
