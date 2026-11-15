"""
When a company reports, and which session trades on it (ADR 0008).

Yahoo's ``earnings_dates`` carry the time of day: 16:00 is after the
close (NVDA, AAPL), 06:00-08:00 before the open (KO, JPM), midnight means
the time isn't known. That decides the first session that trades on a
report, which the options page needs for the implied earnings move and
for each past report's actual move.

The rule for the next report date lives here too, so the research
report's Earnings section and the options page agree: ``calendar``'s
date unless it's on or before the latest report (Yahoo keeps the date
just reported for a while), else the next scheduled row of
``earnings_dates``.

yfinance scrapes ``earnings_dates`` from HTML: about 0.05-0.09
CPU-seconds a ticker on Linux (2026-11-15), so a schedule is cached for
a day.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from typing import Any, Literal

from app.services import market_calendar as mc

logger = logging.getLogger(__name__)

Timing = Literal["before_open", "during", "after_close", "unknown"]

# Rows to ask yfinance for: past and scheduled reports come in one frame.
EARNINGS_DATES_FETCH_LIMIT = 24
SCHEDULE_TTL_SECONDS = 24 * 3600
_CACHE_SIZE = 64
_MIDNIGHT = clock_time(0, 0)


def safe_attr(ticker: Any, name: str) -> Any:
    """``ticker.<name>``, or None if reading it raises (yfinance is flaky)."""
    try:
        return getattr(ticker, name, None)
    except Exception:  # noqa: BLE001
        return None


def safe_float(value: Any) -> float | None:
    """A float, or None for NaN, None or anything non-numeric."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def get_earnings_dates(ticker: Any) -> Any:
    """About 24 rows of past and scheduled reports in one call
    (``get_earnings_dates(limit=24)``, else the ``earnings_dates``
    property); None on any failure."""
    method = getattr(ticker, "get_earnings_dates", None)
    if callable(method):
        try:
            return method(limit=EARNINGS_DATES_FETCH_LIMIT)
        except Exception:  # noqa: BLE001
            pass
    return safe_attr(ticker, "earnings_dates")


def calendar_date(calendar: Any) -> str | None:
    """``calendar["Earnings Date"]`` as an ISO date (a list or one date)."""
    if not isinstance(calendar, dict):
        return None
    raw = calendar.get("Earnings Date")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    try:
        return raw.isoformat()
    except AttributeError:
        return str(raw)


def next_scheduled_row(earnings_dates: Any, after: str | None) -> tuple[str | None, float | None]:
    """The earliest scheduled row (no Reported EPS yet) dated after
    ``after``: (ISO date, EPS estimate)."""
    if earnings_dates is None or getattr(earnings_dates, "empty", True):
        return None, None
    if "Reported EPS" not in earnings_dates.columns:
        return None, None
    best: tuple[str, float | None] | None = None
    for idx, row in earnings_dates.iterrows():
        if safe_float(row.get("Reported EPS")) is not None:
            continue
        try:
            day = idx.date().isoformat()
        except AttributeError:
            continue
        if after is not None and day <= after:
            continue
        if best is None or day < best[0]:
            best = (day, safe_float(row.get("EPS Estimate")))
    return best if best is not None else (None, None)


def next_report_date(calendar: Any, earnings_dates: Any, latest_report_date: str | None) -> str | None:
    """The shared rule: the calendar's date unless it's stale (on or before
    the latest report), else the next scheduled row."""
    cal = calendar_date(calendar)
    if cal is not None and latest_report_date is not None and cal <= latest_report_date:
        cal = None
    return cal or next_scheduled_row(earnings_dates, latest_report_date)[0]


# ── Timing ───────────────────────────────────────────────────────────


def timing_of(when: datetime) -> Timing:
    local = when.astimezone(mc.ET)
    moment = local.time()
    if moment == _MIDNIGHT:
        return "unknown"
    if moment < mc.OPEN:
        return "before_open"
    if local >= mc.session_close(local.date()):  # 1 pm on a half day
        return "after_close"
    return "during"


def reaction_sessions(day: date, timing: Timing) -> tuple[date, date]:
    """(earliest, latest) first session that trades on a report: the same
    one unless the timing is unknown, when it may be either."""
    same = day if mc.is_session(day) else mc.next_session(day)
    if timing in ("before_open", "during"):
        return same, same
    following = mc.next_session(day)
    if timing == "after_close":
        return following, following
    return same, following


@dataclass(frozen=True)
class Announcement:
    when: datetime  # in ET
    timing: Timing
    reported: bool


@dataclass(frozen=True)
class Schedule:
    next: Announcement | None
    past: tuple[Announcement, ...]  # reported, oldest first


def announcements(earnings_dates: Any) -> list[Announcement]:
    """Every row of an ``earnings_dates`` frame, oldest first."""
    if earnings_dates is None or getattr(earnings_dates, "empty", True):
        return []
    found = []
    for idx, row in earnings_dates.iterrows():
        try:
            raw = idx.to_pydatetime()
        except (AttributeError, ValueError):
            continue
        # A naive time is New York's: astimezone would take the machine's
        # zone (UTC on Fly) and turn a 16:00 report into "during".
        when = raw.replace(tzinfo=mc.ET) if raw.tzinfo is None else raw.astimezone(mc.ET)
        found.append(Announcement(when, timing_of(when), safe_float(row.get("Reported EPS")) is not None))
    return sorted(found, key=lambda a: a.when)


def schedule(earnings_dates: Any, calendar: Any) -> Schedule:
    rows = announcements(earnings_dates)
    past = tuple(a for a in rows if a.reported)
    latest = past[-1].when.date().isoformat() if past else None
    next_iso = next_report_date(calendar, earnings_dates, latest)
    if next_iso is None:
        return Schedule(next=None, past=past)
    next_day = date.fromisoformat(next_iso[:10])
    match = next((a for a in rows if not a.reported and a.when.date() == next_day), None)
    if match is None:  # only the calendar knows it: no time of day
        match = Announcement(datetime.combine(next_day, _MIDNIGHT, tzinfo=mc.ET), "unknown", False)
    return Schedule(next=match, past=past)


# ── Fetch, cached ────────────────────────────────────────────────────


def _fetch_yfinance_frames(symbol: str) -> tuple[Any, Any]:
    import yfinance  # noqa: PLC0415  -- lazy: tests swap in a fake

    ticker = yfinance.Ticker(symbol)
    return get_earnings_dates(ticker), safe_attr(ticker, "calendar")


# Swapped in tests.
fetch_frames: Callable[[str], tuple[Any, Any]] = _fetch_yfinance_frames

_cache: dict[str, tuple[Schedule, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def fetch_schedule(symbol: str) -> Schedule:
    """``symbol``'s report schedule, cached for a day; empty when Yahoo
    can't be read (an implied earnings move is then refused, not guessed).
    Blocking."""
    now = time.monotonic()
    hit = _cache.get(symbol)
    if hit is not None and hit[1] > now:
        return hit[0]
    try:
        frame, calendar = fetch_frames(symbol)
        result = schedule(frame, calendar)
    except Exception:
        logger.warning("could not read %s's earnings schedule", symbol, exc_info=True)
        return Schedule(next=None, past=())
    if frame is None:
        # The scrape failed quietly (get_earnings_dates returns None): use
        # what the calendar gave this once, but ask again next time.
        logger.warning("no earnings dates for %s; not caching the schedule", symbol)
        return result
    if len(_cache) >= _CACHE_SIZE:
        _cache.pop(min(_cache, key=lambda k: _cache[k][1]))
    _cache[symbol] = (result, now + SCHEDULE_TTL_SECONDS)
    return result
