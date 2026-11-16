"""
NYSE sessions, for option IVs measured to the minute (ADR 0008).

An option's time to expiry runs from the moment its quotes were made to
the close on the expiry date. Outside market hours that moment is the last
close, not the clock: measured from a Saturday, a 7-day option would look
6 days long and its IV about 8% too high. Yahoo's quotes trail the market
by 15 minutes (``quote_time``); tastytrade's are real time
(``live_quote_time``). Sessions (not calendar days)
count the days that carry variance, for the earnings event move.

Holidays follow NYSE's rules (Rule 7.2): New Year's Day, Martin Luther
King Jr. Day, Washington's Birthday, Good Friday, Memorial Day,
Juneteenth, Independence Day, Labor Day, Thanksgiving and Christmas. A
holiday on a Saturday is observed the Friday before, on a Sunday the
Monday after, except New Year's Day on a Saturday, which isn't observed.
Three sessions close at 1 pm: 3 July, the day after Thanksgiving and
Christmas Eve, each when it is a session. Their quotes are the 1 pm
close's, and an option expiring on one has three hours less to run (on a
weekly, about 2% of its time).

No dependency: the rules are a few lines, and a calendar package would go
into the Dockerfile pin list for this alone.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

# Production runs with TZ=UTC; the market's timezone is named explicitly.
ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
# Yahoo's option quotes trail the market by about 15 minutes.
QUOTE_DELAY = timedelta(minutes=15)
# After the close, delayed quotes are still arriving until about 16:15.
SETTLE = timedelta(minutes=20)
_YEAR = 365 * 24 * 3600

_MONDAY, _THURSDAY, _FRIDAY, _SATURDAY, _SUNDAY = 0, 3, 4, 5, 6


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == _SATURDAY:
        return day - timedelta(days=1)
    if day.weekday() == _SUNDAY:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=16)
def holidays(year: int) -> frozenset[date]:
    new_year = date(year, 1, 1)
    days = {
        _nth_weekday(year, 1, _MONDAY, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, _MONDAY, 3),  # Washington's Birthday
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, _MONDAY),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, _MONDAY, 1),  # Labor Day
        _nth_weekday(year, 11, _THURSDAY, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    if new_year.weekday() != _SATURDAY:
        days.add(_observed(new_year))
    return frozenset(days)


@lru_cache(maxsize=16)
def early_closes(year: int) -> frozenset[date]:
    """The 1 pm closes: 3 July, the day after Thanksgiving and Christmas
    Eve, each when it is a session (not a weekend or the observed holiday)."""
    day_after_thanksgiving = _nth_weekday(year, 11, _THURSDAY, 4) + timedelta(days=1)
    candidates = (date(year, 7, 3), day_after_thanksgiving, date(year, 12, 24))
    return frozenset(day for day in candidates if is_session(day))


def is_session(day: date) -> bool:
    return day.weekday() < _SATURDAY and day not in holidays(day.year)


def previous_session(day: date) -> date:
    """The last session strictly before ``day``."""
    day -= timedelta(days=1)
    while not is_session(day):
        day -= timedelta(days=1)
    return day


def next_session(day: date) -> date:
    """The first session strictly after ``day``."""
    day += timedelta(days=1)
    while not is_session(day):
        day += timedelta(days=1)
    return day


def sessions_between(start: date, end: date) -> int:
    """Sessions after ``start``, up to and including ``end``."""
    count, day = 0, start
    while day < end:
        day += timedelta(days=1)
        count += is_session(day)
    return count


def session_open(day: date) -> datetime:
    return datetime.combine(day, OPEN, tzinfo=ET)


def session_close(day: date) -> datetime:
    close = EARLY_CLOSE if day in early_closes(day.year) else CLOSE
    return datetime.combine(day, close, tzinfo=ET)


def market_open(now: datetime) -> bool:
    """Whether quotes are still moving: a session between the open and a
    few minutes after the close."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    return is_session(day) and session_open(day) <= now_et < session_close(day) + SETTLE


def latest_completed_session(now: datetime) -> date:
    now_et = now.astimezone(ET)
    day = now_et.date()
    if is_session(day) and now_et >= session_close(day) + SETTLE:
        return day
    return previous_session(day)


def _made_at(now: datetime, delay: timedelta) -> datetime:
    """When quotes ``delay`` behind the market, seen at ``now``, were made:
    ``delay`` ago during a session, else the last close."""
    now_et = now.astimezone(ET)
    day = now_et.date()
    delayed = now_et - delay
    # In a session's first ``delay`` the delayed quotes are still the last
    # close's: 09:16 is no quote time, and a weekly's T would run short.
    if is_session(day) and delayed >= session_open(day):
        return min(delayed, session_close(day))
    return session_close(previous_session(day))


def quote_time(now: datetime) -> datetime:
    """When the quotes Yahoo serves at ``now`` were made: 15 minutes ago
    during a session, else the last close."""
    return _made_at(now, QUOTE_DELAY)


def live_quote_time(now: datetime) -> datetime:
    """When real-time quotes (tastytrade's) seen at ``now`` were made: now
    during a session, else the last close (today's once it has closed).
    Yahoo's clock (``quote_time``) would put them 15 minutes back, and in
    a session's first quarter hour at the last close: on an expiry morning
    that's a day or more of time to expiry that isn't there."""
    return _made_at(now, timedelta(0))


def is_close(quoted_at: datetime) -> bool:
    """Whether a quote time (``quote_time``) is a session's close rather
    than a delayed print from inside one."""
    t = quoted_at.astimezone(ET)
    return t == session_close(t.date())


def session_left(quoted_at: datetime) -> float:
    """The share of the quote's session still to trade: 1 at the open, 0 at
    the close and outside sessions."""
    t = quoted_at.astimezone(ET)
    day = t.date()
    if not is_session(day) or t >= session_close(day):
        return 0.0
    start, end = session_open(day), session_close(day)
    return min(1.0, (end - max(t, start)).total_seconds() / (end - start).total_seconds())


def years_to_expiry(quoted_at: datetime, expiry: date) -> float:
    """Years (of 365 days) from the quote time to the close on ``expiry``,
    in elapsed time: aware datetimes in one zone subtract as wall clocks,
    which is an hour off across a daylight-saving change."""
    return (session_close(expiry).astimezone(UTC) - quoted_at.astimezone(UTC)).total_seconds() / _YEAR


def et_date(epoch_seconds: int | float) -> date:
    return datetime.fromtimestamp(epoch_seconds, tz=ET).date()
