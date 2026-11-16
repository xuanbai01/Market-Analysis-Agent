"""
The owner's IV history from tastytrade (ADR 0009, tastytrade PR C).

The options page's IV percentile waits on our own daily snapshots
(63 sessions, from 2026-11-15). tastytrade has the history already:
- **daily candles** over DXLink carry the stock's IV, a fraction, from
  about 2016 (3,235 NVDA sessions since 2014, IV from 2016; checked on
  Fly 2026-11-16, printing no value);
- **market metrics** give today's IV index, IV rank and IV percentile
  (fractions), and the 30-day IV and 30/60/90-day historical
  volatilities (percent, read here as fractions).

Each session gets its close, its IV and the 20-session realized
volatility from the closes (``options_math.realized_vol``, the options
page's RV20). The last year's sessions say where today's IV sits.

tastytrade's data is the owner's alone: behind the owner key, kept
CACHE_SECONDS in memory for at most MAX_SYMBOLS symbols, never stored,
never in a prompt or the demo, and logged as counts only.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.owner import IvHistory, IvMetrics, IvPoint, IvYear
from app.services import dxlink
from app.services import options_math as om
from app.services import tastytrade_client as tt
from app.services.owner_positions import failure_reason, field_of, finite_number

logger = logging.getLogger(__name__)

YEARS = 10  # tastytrade's candles carry IV from about 2016
YEAR_SESSIONS = 252
RV_WINDOW = 20  # the options page's RV20
CACHE_SECONDS = 900.0  # daily candles; the metrics move during a session
MAX_SYMBOLS = 8  # about 2,500 sessions each
BUILD_SECONDS = 45.0  # ten years of candles over DXLink, and the metrics
DIGITS = 5  # enough for a tenth of a vol point; keeps the answer small

# Range checks, so a unit tastytrade changed can't show as 4,500% IV.
MAX_FRACTION = 5.0
MAX_PERCENT = 500.0


class IvHistoryUnavailable(Exception):
    """tastytrade or its feed didn't answer, or isn't set up; the reason is
    safe to show."""


class NoHistory(Exception):
    """tastytrade has no candles and no metrics for the symbol."""


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
    return when if when.tzinfo else when.replace(tzinfo=UTC)


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


def points_of(candles: tuple[dxlink.Candle, ...]) -> list[IvPoint]:
    """One point per session, oldest first. A daily candle is stamped 00:00
    UTC on its session's date (checked on Fly), so that date is the day."""
    points: list[IvPoint] = []
    closes: list[float] = []
    for candle in candles:
        close = finite_number(candle.close)
        if close is not None and close > 0:
            closes.append(close)
        rv = om.realized_vol(closes, RV_WINDOW) if close is not None and close > 0 else None
        points.append(IvPoint(date=candle.time.astimezone(UTC).date(), close=_round(close),
                              iv=_round(_fraction(candle.imp_volatility)), rv20=_round(rv)))
    return points


def year_of(points: list[IvPoint]) -> IvYear:
    """Where the latest IV sits among the last YEAR_SESSIONS sessions' IVs."""
    ivs = [p.iv for p in points if p.iv is not None][-YEAR_SESSIONS:]
    if not ivs:
        return IvYear()
    today, low, high = ivs[-1], min(ivs), max(ivs)
    return IvYear(
        sessions=len(ivs),
        iv_low=low, iv_high=high, iv_median=_round(statistics.median(ivs)),
        iv_rank=_round((today - low) / (high - low)) if high > low else None,
        iv_percentile=_round(sum(1 for v in ivs if v < today) / len(ivs)),
    )


def _item_for(payload: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    items = (payload.get("data") or {}).get("items") or []
    wanted = tastytrade_symbol(symbol)
    return next((i for i in items if isinstance(i, dict) and str(field_of(i, "symbol")).upper() == wanted), None)


async def _build(symbol: str) -> IvHistory:
    wanted = tastytrade_symbol(symbol)
    since = _now() - timedelta(days=round(365.25 * YEARS) + 7)
    payload, history = await asyncio.gather(
        tt.get("/market-metrics", {"symbols": wanted}, op="market_metrics"),
        dxlink.fetch_candles(wanted, "d", since),
    )
    item = _item_for(payload, symbol)
    if item is None and not history.candles:
        raise NoHistory(symbol)
    points = points_of(history.candles)
    first_iv = next((p.date for p in points if p.iv is not None), None)
    logger.info("owner iv history: %d sessions, %d with an IV, metrics %s",
                len(points), sum(1 for p in points if p.iv is not None), "read" if item else "missing")
    return IvHistory(symbol=symbol.upper(), as_of=_now(), metrics=metrics_of(item), points=points,
                     year=year_of(points), iv_since=first_iv, complete=history.complete and not history.snipped)


def _keep(symbol: str, history: IvHistory) -> None:
    now = _clock()
    for old in [s for s, (at, _) in _kept.items() if now - at >= CACHE_SECONDS]:
        del _kept[old]
    _kept[symbol] = (now, history)
    _kept.move_to_end(symbol)
    while len(_kept) > MAX_SYMBOLS:
        _kept.popitem(last=False)


async def iv_history(symbol: str) -> IvHistory:
    """``symbol``'s IV history and today's figures, at most CACHE_SECONDS
    old. ``NoHistory`` when tastytrade has nothing for it;
    ``IvHistoryUnavailable`` with the reason otherwise."""
    if not tt.is_configured():
        raise IvHistoryUnavailable("tastytrade isn't set up on the server")
    key = symbol.upper()
    _users[key] = _users.get(key, 0) + 1
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        # The deadline covers waiting behind another build of the same symbol.
        async with asyncio.timeout(BUILD_SECONDS), lock:
            kept = _kept.get(key)
            if kept is not None and _clock() - kept[0] < CACHE_SECONDS:
                return kept[1]
            built = await _build(key)
            _keep(key, built)
            return built
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound, TimeoutError) as exc:
        raise IvHistoryUnavailable(failure_reason(exc)) from exc
    except dxlink.DxlinkError as exc:
        raise IvHistoryUnavailable(f"tastytrade's feed failed: {exc}") from exc
    finally:
        _users[key] -= 1
        if _users[key] == 0:  # no lock left behind per symbol ever asked
            del _users[key]
            _locks.pop(key, None)
