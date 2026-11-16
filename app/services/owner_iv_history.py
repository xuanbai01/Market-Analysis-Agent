"""
The owner's IV history from tastytrade (ADR 0009, tastytrade PR C).

The options page's IV percentile waits on our own daily snapshots
(63 sessions, from 2026-11-15). tastytrade has the history already:
- **daily candles** over DXLink carry the stock's IV, a fraction, from
  about 2016 (3,235 NVDA sessions since 2014, IV from 2016; checked on
  Fly 2026-11-16, printing no value). A candle is stamped 00:00 UTC on
  its session's date;
- **market metrics** give today's IV index, IV rank and IV percentile
  (fractions), and the 30-day IV and 30/60/90-day historical
  volatilities (percent, read here as fractions).

Each session gets its close, its IV and the 20-session realized
volatility from the closes (``options_math.realized_vol``, the options
page's RV20). The last year's sessions say where today's IV sits.

tastytrade's data is the owner's alone: behind the owner key, kept
CACHE_SECONDS in memory for at most MAX_SYMBOLS symbols (dropped on any
visit once expired), never stored, never in a prompt or the demo, and
logged as counts only.
"""
from __future__ import annotations

import asyncio
import logging
import re
import statistics
import time
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.owner import IvHistory, IvMetrics, IvPoint, IvYear
from app.services import dxlink, options_chain
from app.services import options_math as om
from app.services import tastytrade_client as tt
from app.services.owner_positions import failure_reason, field_of, finite_number, items_of

logger = logging.getLogger(__name__)

YEARS = 10  # tastytrade's candles carry IV from about 2016
YEAR_SESSIONS = 252
RV_WINDOW = 20  # the options page's RV20
CACHE_SECONDS = 900.0  # daily candles; the metrics move during a session
MAX_SYMBOLS = 8
# Ten years of sessions, with room: tastytrade has sent a whole history
# when it misread the start (dxlink), so what comes back is cut to this.
MAX_POINTS = YEARS * YEAR_SESSIONS + 30
BUILD_SECONDS = 45.0  # ten years of candles over DXLink, and the metrics
DIGITS = 5  # enough for a tenth of a vol point; keeps the answer small

# Range checks, so a unit tastytrade changed can't show as 4,500% IV.
MAX_FRACTION = 5.0
MAX_PERCENT = 500.0

# tastytrade's form of a ticker. Checked here too, not only by the route:
# a comma would be a list in the metrics query, and braces or "=" dxFeed's
# attribute syntax in the candle symbol.
_TT_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:/[A-Z0-9]{1,4})?")


class IvHistoryUnavailable(Exception):
    """tastytrade or its feed didn't answer, or isn't set up; the reason is
    safe to show."""


class NoHistory(Exception):
    """tastytrade has no candles and no metrics for the symbol, or it isn't
    a ticker."""


def _now() -> datetime:
    return datetime.now(UTC)


def _clock() -> float:
    return time.monotonic()


_kept: OrderedDict[str, tuple[float, IvHistory]] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}
_users: dict[str, int] = {}


def reset() -> None:
    """Tests only."""
    _kept.clear()
    _locks.clear()
    _users.clear()


def tastytrade_symbol(symbol: str) -> str:
    """tastytrade's form of a ticker: a class share's dash or dot is a slash."""
    return symbol.upper().replace("-", "/").replace(".", "/")


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, DIGITS)


def _fraction(value: Any) -> float | None:
    number = finite_number(value)
    return number if number is not None and 0 < number <= MAX_FRACTION else None


def _percent(value: Any) -> float | None:
    number = finite_number(value)
    return number / 100 if number is not None and 0 < number <= MAX_PERCENT else None


def _unit(value: Any) -> float | None:
    number = finite_number(value)
    return number if number is not None and 0 <= number <= 1 else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)


def metrics_of(item: dict[str, Any] | None) -> IvMetrics:
    item = item or {}
    return IvMetrics(
        iv_index=_round(_fraction(field_of(item, "implied-volatility-index"))),
        iv30=_round(_percent(field_of(item, "implied-volatility-30-day"))),
        iv_rank=_round(_unit(field_of(item, "tw-implied-volatility-index-rank"))),
        iv_percentile=_round(_unit(field_of(item, "implied-volatility-percentile"))),
        hv30=_round(_percent(field_of(item, "historical-volatility-30-day"))),
        hv60=_round(_percent(field_of(item, "historical-volatility-60-day"))),
        hv90=_round(_percent(field_of(item, "historical-volatility-90-day"))),
        updated_at=_when(field_of(item, "implied-volatility-updated-at")),
    )


def points_of(candles: Sequence[dxlink.Candle]) -> list[IvPoint]:
    """One point per session, oldest first. A candle's UTC date is its
    session. A close that isn't a price is no close and has no RV20."""
    points: list[IvPoint] = []
    closes: list[float] = []
    for candle in candles:
        number = finite_number(candle.close)
        close = number if number is not None and number > 0 else None
        if close is not None:
            closes.append(close)
        rv = om.realized_vol(closes, RV_WINDOW) if close is not None else None
        points.append(IvPoint(date=candle.time.astimezone(UTC).date(), close=_round(close),
                              iv=_round(_fraction(candle.imp_volatility)), rv20=_round(rv)))
    return points


def year_of(points: list[IvPoint]) -> IvYear:
    """Where the latest IV sits among the last YEAR_SESSIONS sessions (not
    the last that many IVs: sparse IVs would stretch the year). The rank
    runs from the year's low (0) to its high (1); the percentile is the
    share of the year's other sessions with a lower IV."""
    ivs = [p.iv for p in points[-YEAR_SESSIONS:] if p.iv is not None]
    if not ivs:
        return IvYear()
    today, low, high, others = ivs[-1], min(ivs), max(ivs), ivs[:-1]
    return IvYear(
        sessions=len(ivs),
        iv_low=low, iv_high=high, iv_median=_round(statistics.median(ivs)),
        iv_rank=_round((today - low) / (high - low)) if high > low else None,
        iv_percentile=_round(sum(1 for v in others if v < today) / len(others)) if others else None,
    )


def _clip(candles: Sequence[dxlink.Candle], since: datetime, now: datetime) -> list[dxlink.Candle]:
    inside = [c for c in candles if since <= c.time <= now]
    return inside[-MAX_POINTS:]


def _item_for(payload: Any, wanted: str) -> dict[str, Any] | None:
    """The metrics item for ``wanted``; a wrong-shaped answer reads as none."""
    for item in items_of(payload):
        echoed = field_of(item, "symbol")
        if isinstance(echoed, str) and tastytrade_symbol(echoed) == wanted:
            return item
    return None


async def _metrics(wanted: str) -> Any:
    try:
        return await tt.get("/market-metrics", {"symbols": wanted}, op="market_metrics")
    except tt.TastytradeNotFound:
        return None  # not a symbol tastytrade has metrics for: the candles decide


async def _both(wanted: str, since: datetime) -> tuple[Any, dxlink.CandleHistory]:
    """The metrics and the candles at once. When one fails or the deadline
    hits, the other is stopped: a candle fetch left running would hold the
    machine's one DXLink session for nothing."""
    tasks = (asyncio.create_task(_metrics(wanted)), asyncio.create_task(dxlink.fetch_candles(wanted, "d", since)))
    try:
        # Whichever fails first gives the reason: a feed that refused at once
        # isn't "took too long" because the metrics were still waiting.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        failed = next((t.exception() for t in done if not t.cancelled() and t.exception() is not None), None)
        if failed is not None:
            raise failed
        return tasks[0].result(), tasks[1].result()
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _build(wanted: str) -> IvHistory:
    now = _now()
    since = now - timedelta(days=round(365.25 * YEARS) + 7)
    payload, history = await _both(wanted, since)
    item = _item_for(payload, wanted)
    candles = _clip(history.candles, since, now)
    if item is None and not candles:
        raise NoHistory(wanted)
    # The arithmetic runs on the options thread, off the event loop.
    points = await options_chain.on_options_thread(points_of, candles)
    year = await options_chain.on_options_thread(year_of, points)
    logger.info("owner iv history: %d sessions, %d with an IV, metrics %s",
                len(points), sum(1 for p in points if p.iv is not None), "read" if item else "missing")
    return IvHistory(symbol=wanted, as_of=now, metrics=metrics_of(item), points=points, year=year,
                     iv_since=next((p.date for p in points if p.iv is not None), None),
                     complete=history.complete and not history.snipped)


def _forget_expired() -> None:
    now = _clock()
    for old in [s for s, (at, _) in _kept.items() if now - at >= CACHE_SECONDS]:
        del _kept[old]


def _keep(key: str, history: IvHistory) -> None:
    _kept[key] = (_clock(), history)
    _kept.move_to_end(key)
    while len(_kept) > MAX_SYMBOLS:
        _kept.popitem(last=False)


async def iv_history(symbol: str) -> IvHistory:
    """``symbol``'s IV history and today's figures, at most CACHE_SECONDS
    old. ``NoHistory`` when tastytrade has nothing for it (or it isn't a
    ticker); ``IvHistoryUnavailable`` with the reason otherwise."""
    if not tt.is_configured():
        raise IvHistoryUnavailable("tastytrade isn't set up on the server")
    key = tastytrade_symbol(symbol)  # BRK-B and BRK.B share one copy
    if not _TT_SYMBOL.fullmatch(key):
        raise NoHistory(symbol)
    _forget_expired()  # on every visit, not only when a build is kept
    _users[key] = _users.get(key, 0) + 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        # The deadline covers waiting behind another build of the same symbol.
        async with asyncio.timeout(BUILD_SECONDS), lock:
            kept = _kept.get(key)
            if kept is not None and _clock() - kept[0] < CACHE_SECONDS:
                built = kept[1]
            else:
                built = await _build(key)
                _keep(key, built)
        # One copy for BRK-B and BRK.B; each answer names the ticker asked for.
        return built.model_copy(update={"symbol": symbol.upper()})
    except TimeoutError as exc:
        logger.warning("owner iv history: gave up after %.0f s", BUILD_SECONDS)  # no symbol
        raise IvHistoryUnavailable(failure_reason(exc)) from exc
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound) as exc:
        raise IvHistoryUnavailable(failure_reason(exc)) from exc
    except dxlink.DxlinkError as exc:
        raise IvHistoryUnavailable(f"tastytrade's feed failed: {exc}") from exc
    finally:
        _users[key] -= 1
        if _users[key] == 0:  # no lock left behind per symbol ever asked
            del _users[key]
            _locks.pop(key, None)
