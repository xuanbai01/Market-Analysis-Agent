"""
The daily IV snapshot run (ADR 0008).

A GitHub Actions cron calls ``POST /v1/options/snapshots`` after each US
close, and once more later the same night. Each run stores one row per
ticker for the last completed session, and only rows not stored yet: a
weekend or holiday run, or the retry after a good run, writes nothing
(``no_new_session``). While the market is open it refuses
(``market_open``): the day's figures aren't settled.

Tickers: ``OPTIONS_SNAPSHOT_SYMBOLS``, then the symbols whose options page
was opened in the last 60 days, at most 30.

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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.core.settings import settings
from app.schemas.options import FailedTicker, SnapshotRun
from app.services import market_calendar as mc
from app.services import options_chain
from app.services import options_metrics as om
from app.services import options_snapshot_store as store

logger = logging.getLogger(__name__)

MAX_TARGETS = 30
TRACKED_DAYS = 60
TIME_BUDGET_SECONDS = 300
RATE_LIMIT_PAUSE_SECONDS = 30
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_RATE_LIMIT_ERRORS = frozenset({"YFRateLimitError"})

_OPTIONS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="options")
_run_lock = asyncio.Lock()

# Swapped in tests.
_sleep = asyncio.sleep
_clock = time.monotonic


def _now() -> datetime:
    return datetime.now(UTC)


_T = TypeVar("_T")


class SnapshotRunning(Exception):
    """Another run is in progress in this process."""


async def _on_options_thread(fn: Callable[..., _T], *args: Any) -> _T:
    return await asyncio.get_running_loop().run_in_executor(_OPTIONS_EXECUTOR, fn, *args)


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
        fetched = options_chain.fetch_chain(symbol, lambda listed: om.snapshot_expiries(listed, quoted_at))
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
    underlying_date = mc.et_date(fetched.market_time).isoformat() if fetched.market_time else None
    return "ok", {
        "symbol": symbol,
        "trade_date": session_date,
        "as_of": quoted_at,
        "method_version": om.METHOD_VERSION,
        "spot": fetched.spot,
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


async def _insert(session: AsyncSession, row: dict[str, Any]) -> bool:
    """Insert, retrying once on a connection the database dropped while
    the run was fetching (Neon drops idle ones)."""
    try:
        return await store.insert_snapshot(session, row)
    except DBAPIError as exc:
        if not exc.connection_invalidated:
            raise
        await session.rollback()
        return await store.insert_snapshot(session, row)


async def run_snapshots(session: AsyncSession, *, now: datetime | None = None) -> SnapshotRun:
    if _run_lock.locked():
        raise SnapshotRunning
    async with _run_lock:
        return await _run(session, now or _now())


async def _run(session: AsyncSession, now: datetime) -> SnapshotRun:
    started = _clock()
    lists: dict[str, list[str]] = {k: [] for k in ("written", "skipped", "no_options", "no_usable_quotes", "deferred")}
    failed: list[FailedTicker] = []

    def finish(status: str, session_date: Any, symbols: list[str]) -> SnapshotRun:
        return SnapshotRun(
            status=status, session_date=session_date, targets=symbols, failed=failed,
            duration_ms=round((_clock() - started) * 1000, 1), **lists,  # type: ignore[arg-type]
        )

    if mc.market_open(now):
        return finish("market_open", None, [])
    session_date = mc.latest_completed_session(now)
    symbols = await targets(session, now)
    done = await store.stored_symbols(session, session_date)
    await session.rollback()  # no connection held while Yahoo is fetched
    lists["skipped"] = [s for s in symbols if s in done]
    pending = [s for s in symbols if s not in done]
    if not pending:
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
            logger.exception("IV snapshot failed for %s", symbol)
            failed.append(FailedTicker(symbol=symbol, reason=type(exc).__name__))
            i += 1
            continue
        lists[status].append(symbol)
        i += 1
    return finish("ok", session_date, symbols)
