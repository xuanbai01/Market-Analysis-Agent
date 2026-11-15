"""
The daily IV snapshot run (ADR 0008).

A GitHub Actions cron calls ``POST /v1/options/snapshots`` after each US
close, and once more later the same night. Each run stores one row per
ticker for the last completed session, and only rows not stored yet: a
weekend or holiday run, or the retry after a good run, writes nothing
(``no_new_session``). While the market is open it refuses
(``market_open``): the day's figures aren't settled.

Tickers: ``OPTIONS_SNAPSHOT_SYMBOLS``, then the symbols whose options page
was opened in the last 60 days, at most 30. After the snapshots, the run
reads the whole chain of each ``OPTIONS_FULL_CHAIN_SYMBOLS`` ticker (one
Yahoo call per listed expiry) and stores its total open interest
(``option_oi_totals``): last, so the slower reads never cost a snapshot,
under the same time budget and throttle pause. Totals are best-effort:
the cron fails only on a missing snapshot.

One ticker's failure is its own: the others still run. Yahoo throttling
pauses the run once for 30 seconds; a second throttle defers the rest to
the retry run. The run stops after 300 seconds. No database connection
is held while Yahoo is fetched, and the fetch and the math run on the
options thread, off the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.core.settings import settings
from app.schemas.options import FailedTicker, SnapshotRun
from app.services import market_calendar as mc
from app.services import options_chain
from app.services import options_metrics as om
from app.services import options_snapshot_store as store
from app.services.options_chain import on_options_thread as _on_options_thread

logger = logging.getLogger(__name__)

MAX_TARGETS = 30
TRACKED_DAYS = 60
TIME_BUDGET_SECONDS = 300
RATE_LIMIT_PAUSE_SECONDS = 30
TOTALS_HISTORY = "5d"  # fetch_chain reads daily closes too; the totals need none
# A stored totals row is never updated, so the cron's first run (22:17 UTC,
# 1-2 h after the close) leaves a short read to its night run (00:47 UTC,
# 3 h 47 min or more after), which stores whatever it reads with the count
# of expiries read: a ticker Yahoo always reads short still gets its row,
# and the page says how many expiries it covers. (On a 1 pm half day the
# first run is already past this, so there's no second try.)
KEEP_SHORT_READ_AFTER = timedelta(hours=3, minutes=30)
_SHORT_READS = frozenset({"partial", "unread"})
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_RATE_LIMIT_ERRORS = frozenset({"YFRateLimitError"})

_run_lock = asyncio.Lock()

# Swapped in tests.
_sleep = asyncio.sleep
_clock = time.monotonic


def _now() -> datetime:
    return datetime.now(UTC)


class SnapshotRunning(Exception):
    """Another run is in progress in this process."""


def parse_symbols(raw: str) -> list[str]:
    """Upper-cased valid tickers from a comma-separated list, in order, once each."""
    seen: dict[str, None] = {}
    for part in raw.split(","):
        symbol = part.strip().upper()
        if _SYMBOL.match(symbol):
            seen.setdefault(symbol, None)
    return list(seen)


async def targets(session: AsyncSession, now: datetime) -> list[str]:
    tracked = await store.tracked_symbols(session, now - timedelta(days=TRACKED_DAYS))
    return parse_symbols(",".join([settings.OPTIONS_SNAPSHOT_SYMBOLS, *tracked]))[:MAX_TARGETS]


def is_rate_limit(exc: BaseException) -> bool:
    return type(exc).__name__ in _RATE_LIMIT_ERRORS


def snapshot_one(
    symbol: str, session_date: date, quoted_at: datetime, rate: float, rate_assumed: bool
) -> tuple[str, dict[str, Any] | None]:
    """(status, row) for one ticker; the row only when status is "ok".
    Blocking: fetches from Yahoo and computes.

    The row is keyed on the session the run snapshots, not the
    underlying's last print: a thin name last traded on Thursday would
    otherwise be keyed on Thursday on a Friday run, collide with
    Thursday's row and leave Friday unwritten. The print's own date goes
    into the detail."""
    cpu_started = time.thread_time()
    with log_external_call("yfinance.options", {"symbol": symbol, "purpose": "snapshot"}) as call:
        fetched = options_chain.fetch_chain(symbol, lambda listed, _quote: om.snapshot_expiries(listed, quoted_at))
        metrics = om.snapshot_metrics(fetched, quoted_at, rate, rate_assumed=rate_assumed) if fetched else None
        call.record_output({
            "status": metrics.status if metrics else "no_options",
            "expiries": len(fetched.chains) if fetched else 0,
            "cpu_ms": round((time.thread_time() - cpu_started) * 1000, 1),
        })
    if fetched is None or metrics is None:
        return "no_options", None
    if metrics.status != "ok":
        return metrics.status, None
    # fetch_chain falls back to the last close; with neither there is no
    # spot, and a $0 spot would be stored forever.
    spot = fetched.spot
    if spot <= 0:
        return "no_usable_quotes", None
    underlying_date = mc.et_date(fetched.market_time).isoformat() if fetched.market_time else None
    return "ok", {
        "symbol": symbol,
        "trade_date": session_date,
        "as_of": quoted_at,
        "method_version": om.METHOD_VERSION,
        "spot": spot,
        "rate": rate,
        "iv30": metrics.iv30,
        "iv30_extrapolated": metrics.iv30_extrapolated,
        "iv90": metrics.iv90,
        "iv90_extrapolated": metrics.iv90_extrapolated,
        "skew25": metrics.skew25,
        "rv20": metrics.rv20,
        "rv60": metrics.rv60,
        "call_open_interest": metrics.call_open_interest,
        "put_open_interest": metrics.put_open_interest,
        "call_volume": metrics.call_volume,
        "put_volume": metrics.put_volume,
        "next_earnings": fetched.next_earnings,
        "detail": {**metrics.detail, "underlying_date": underlying_date},
    }


def chain_totals_one(symbol: str, session_date: date, quoted_at: datetime) -> tuple[str, dict[str, Any] | None]:
    """(status, row) of ``symbol``'s open interest and volume summed over
    every listed expiry, adjusted contracts included. An expiry counts as
    read only with both sides quoted: "partial" (with the row) when one
    listed wasn't, "unread" (no row) when none was. Blocking."""
    cpu_started = time.thread_time()
    with log_external_call("yfinance.options", {"symbol": symbol, "purpose": "chain_totals"}) as call:
        fetched = options_chain.fetch_chain(
            symbol, lambda listed, _quote: list(listed), history_period=TOTALS_HISTORY, read_calendar=False
        )
        call.record_output({
            "expiries": len(fetched.chains) if fetched else 0,
            "listed": len(fetched.expiries) if fetched else 0,
            "cpu_ms": round((time.thread_time() - cpu_started) * 1000, 1),
        })
    if fetched is None or not fetched.expiries:
        return "no_options", None
    chains = [c for c in fetched.chains.values() if c.calls and c.puts]
    if not chains:
        return "unread", None
    return ("partial" if len(chains) < len(fetched.expiries) else "ok"), {
        "symbol": symbol,
        "trade_date": session_date,
        "as_of": quoted_at,
        "call_open_interest": sum(q.open_interest for c in chains for q in c.calls),
        "put_open_interest": sum(q.open_interest for c in chains for q in c.puts),
        "call_volume": sum(q.volume for c in chains for q in c.calls),
        "put_volume": sum(q.volume for c in chains for q in c.puts),
        "expiries": len(chains),
        "listed": len(fetched.expiries),
    }


async def _insert(session: AsyncSession, row: dict[str, Any], write: Any = None) -> bool:
    """Insert, retrying once on a connection the database dropped while
    the run was fetching (Neon drops idle ones)."""
    write = write or store.insert_snapshot
    try:
        return await write(session, row)
    except DBAPIError as exc:
        if not exc.connection_invalidated:
            raise
        await session.rollback()
        return await write(session, row)


async def run_snapshots(session: AsyncSession, *, now: datetime | None = None) -> SnapshotRun:
    if _run_lock.locked():
        raise SnapshotRunning
    async with _run_lock:
        return await _run(session, now or _now())


async def _run(session: AsyncSession, now: datetime) -> SnapshotRun:
    started = _clock()
    lists: dict[str, list[str]] = {
        k: []
        for k in ("written", "skipped", "no_options", "no_usable_quotes", "deferred", "totals_written", "totals_skipped", "totals_deferred")
    }
    failed: list[FailedTicker] = []

    def finish(status: str, session_date: Any, symbols: list[str]) -> SnapshotRun:
        stored = {*lists["written"], *lists["skipped"]}
        configured = parse_symbols(settings.OPTIONS_SNAPSHOT_SYMBOLS)
        missing = [s for s in configured if s not in stored] if session_date else []
        return SnapshotRun(
            status=status, session_date=session_date, targets=symbols, failed=failed, missing=missing,
            duration_ms=round((_clock() - started) * 1000, 1), **lists,  # type: ignore[arg-type]
        )

    if mc.market_open(now):
        return finish("market_open", None, [])
    session_date = mc.latest_completed_session(now)
    symbols = await targets(session, now)
    done = await store.stored_symbols(session, session_date)
    full_chain = parse_symbols(settings.OPTIONS_FULL_CHAIN_SYMBOLS)
    totals_done = await store.stored_totals(session, session_date) if full_chain else set()
    await session.rollback()  # no connection held while Yahoo is fetched
    lists["skipped"] = [s for s in symbols if s in done]
    pending = [s for s in symbols if s not in done]
    lists["totals_skipped"] = [s for s in full_chain if s in totals_done]
    totals_pending = [s for s in full_chain if s not in totals_done]
    if not pending and not totals_pending:
        return finish("no_new_session", session_date, symbols)

    quoted_at = mc.quote_time(now)
    rate, rate_assumed = await _on_options_thread(options_chain.risk_free_rate)
    paused, i = False, 0
    while i < len(pending):
        symbol = pending[i]
        if _clock() - started > TIME_BUDGET_SECONDS:
            lists["deferred"] = pending[i:]
            break
        try:
            status, row = await _on_options_thread(snapshot_one, symbol, session_date, quoted_at, rate, rate_assumed)
            if row is not None:
                status = "written" if await _insert(session, row) else "skipped"
        except Exception as exc:
            if is_rate_limit(exc):
                if paused:
                    lists["deferred"] = pending[i:]
                    break
                paused = True
                await _sleep(RATE_LIMIT_PAUSE_SECONDS)
                continue  # the same ticker once more
            if isinstance(exc, options_chain.SymbolNotFound):
                failed.append(FailedTicker(symbol=symbol, reason="not_found"))  # delisted or misspelt
                i += 1
                continue
            logger.exception("IV snapshot failed for %s", symbol)
            # A failed statement leaves the session needing a rollback; without
            # it every later ticker's insert would fail too.
            await session.rollback()
            failed.append(FailedTicker(symbol=symbol, reason=type(exc).__name__))
            i += 1
            continue
        lists[status].append(symbol)
        i += 1
    if not lists["deferred"]:
        keep_short = now - quoted_at >= KEEP_SHORT_READ_AFTER
        await _run_totals(session, totals_pending, session_date, quoted_at, keep_short, started, paused, lists, failed)
    else:
        lists["totals_deferred"] = totals_pending  # throttled or out of time already: the retry run reads them
    return finish("ok", session_date, symbols)


async def _run_totals(
    session: AsyncSession,
    pending: list[str],
    session_date: date,
    quoted_at: datetime,
    keep_short: bool,
    started: float,
    paused: bool,
    lists: dict[str, list[str]],
    failed: list[FailedTicker],
) -> None:
    """The whole-chain totals, after the snapshots, under the run's budget
    and its one throttle pause (``paused``: already used by the snapshots).
    A short read waits for the night run unless ``keep_short``."""
    i = 0
    while i < len(pending):
        symbol = pending[i]
        if _clock() - started > TIME_BUDGET_SECONDS:
            lists["totals_deferred"] += pending[i:]
            break
        try:
            status, row = await _on_options_thread(chain_totals_one, symbol, session_date, quoted_at)
            if status in _SHORT_READS and not keep_short:
                lists["totals_deferred"].append(symbol)  # the night run reads it again
            elif row is None:
                failed.append(FailedTicker(symbol=symbol, reason=f"totals: {status}"))
            elif await _insert(session, row, store.insert_totals):
                lists["totals_written"].append(symbol)
            else:
                lists["totals_skipped"].append(symbol)
        except Exception as exc:
            if is_rate_limit(exc):
                if paused:
                    lists["totals_deferred"] += pending[i:]
                    break
                paused = True
                await _sleep(RATE_LIMIT_PAUSE_SECONDS)
                continue
            logger.exception("open interest totals failed for %s", symbol)
            await session.rollback()
            failed.append(FailedTicker(symbol=symbol, reason=f"totals: {type(exc).__name__}"))
        i += 1
