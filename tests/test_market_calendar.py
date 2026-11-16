"""NYSE sessions and quote times (ADR 0008): option IVs are measured to
the minute from the time the quotes were made, so the calendar has to be
right on holidays and weekends."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.services import market_calendar as mc


def et(y: int, m: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=mc.ET)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2025, [(1, 1), (1, 20), (2, 17), (4, 18), (5, 26), (6, 19), (7, 4), (9, 1), (11, 27), (12, 25)]),
        (2026, [(1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19), (7, 3), (9, 7), (11, 26), (12, 25)]),
        # 2027: Juneteenth (a Saturday) on Friday the 18th, the Fourth (a
        # Sunday) on Monday the 5th, Christmas (a Saturday) on Friday the 24th.
        (2027, [(1, 1), (1, 18), (2, 15), (3, 26), (5, 31), (6, 18), (7, 5), (9, 6), (11, 25), (12, 24)]),
    ],
)
def test_nyse_holidays(year: int, expected: list[tuple[int, int]]) -> None:
    assert sorted(mc.holidays(year)) == [date(year, m, d) for m, d in expected]


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2025, [(7, 3), (11, 28), (12, 24)]),
        # 2026: the Fourth is a Saturday, so the 3rd is the holiday, not a half day.
        (2026, [(11, 27), (12, 24)]),
        # 2027: the 3rd is a Saturday; Christmas Eve is the observed holiday.
        (2027, [(11, 26)]),
        # 2028: the 3rd is a Monday; Christmas Eve a Sunday.
        (2028, [(7, 3), (11, 24)]),
    ],
)
def test_nyse_early_closes(year: int, expected: list[tuple[int, int]]) -> None:
    """1 pm closes: 3 July, the day after Thanksgiving and Christmas Eve,
    each when it is a session."""
    assert sorted(mc.early_closes(year)) == [date(year, m, d) for m, d in expected]


def test_a_half_day_closes_at_one() -> None:
    assert mc.session_close(date(2026, 11, 27)) == et(2026, 11, 27, 13)
    assert mc.session_close(date(2026, 11, 25)) == et(2026, 11, 25, 16)


def test_a_saturday_new_year_is_not_moved_to_the_year_before() -> None:
    """1 Jan 2028 is a Saturday; NYSE keeps 31 Dec 2027 open."""
    assert mc.is_session(date(2027, 12, 31))


def test_weekends_and_holidays_are_not_sessions() -> None:
    assert mc.is_session(date(2026, 11, 13))  # Friday
    assert not mc.is_session(date(2026, 11, 14))  # Saturday
    assert not mc.is_session(date(2026, 11, 26))  # Thanksgiving


def test_counts_sessions_after_start_up_to_end() -> None:
    assert mc.sessions_between(date(2026, 11, 13), date(2026, 11, 20)) == 5
    assert mc.sessions_between(date(2026, 11, 20), date(2026, 11, 27)) == 4  # Thanksgiving
    assert mc.sessions_between(date(2026, 11, 20), date(2026, 11, 20)) == 0


def test_previous_and_next_session_skip_weekends_and_holidays() -> None:
    assert mc.previous_session(date(2026, 11, 16)) == date(2026, 11, 13)
    assert mc.next_session(date(2027, 7, 2)) == date(2027, 7, 6)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (et(2026, 11, 14, 12), et(2026, 11, 13, 16)),  # Saturday: Friday's close
        (et(2026, 11, 16, 11), et(2026, 11, 16, 10, 45)),  # market hours: 15 minutes ago
        (et(2026, 11, 16, 8), et(2026, 11, 13, 16)),  # before the open: the last close
        (et(2026, 11, 16, 16, 10), et(2026, 11, 16, 15, 55)),
        (et(2026, 11, 16, 17), et(2026, 11, 16, 16)),
        (et(2026, 11, 26, 12), et(2026, 11, 25, 16)),  # Thanksgiving
        (et(2026, 11, 27, 12), et(2026, 11, 27, 11, 45)),  # a half day, in session
        (et(2026, 11, 27, 14), et(2026, 11, 27, 13)),  # after its 1 pm close
        (et(2026, 11, 28, 12), et(2026, 11, 27, 13)),  # the Saturday after
    ],
)
def test_quote_time(now: datetime, expected: datetime) -> None:
    assert mc.quote_time(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (et(2026, 11, 14, 12), True),  # Saturday: Friday's close
        (et(2026, 11, 16, 11), False),  # market hours: a delayed print
        (et(2026, 11, 16, 16, 10), False),  # the session's last prints, still delayed
        (et(2026, 11, 16, 17), True),
        (et(2026, 11, 27, 14), True),  # a half day's 1 pm close
        (et(2026, 11, 27, 12), False),
    ],
)
def test_a_quote_time_says_whether_it_is_a_close(now: datetime, expected: bool) -> None:
    assert mc.is_close(mc.quote_time(now)) is expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (et(2026, 11, 16, 11), et(2026, 11, 16, 11)),  # market hours: now, not 15 minutes ago
        (et(2026, 11, 16, 9, 30), et(2026, 11, 16, 9, 30)),  # the open
        (et(2026, 11, 16, 9, 31), et(2026, 11, 16, 9, 31)),  # not the last close: these quotes aren't delayed
        (et(2026, 11, 16, 15, 59), et(2026, 11, 16, 15, 59)),
        (et(2026, 11, 16, 16, 10), et(2026, 11, 16, 16)),  # after the close: today's close
        (et(2026, 11, 16, 20), et(2026, 11, 16, 16)),
        (et(2026, 11, 16, 9, 29), et(2026, 11, 13, 16)),  # before the open: Friday's close
        (et(2026, 11, 16, 4), et(2026, 11, 13, 16)),  # pre-market
        (et(2026, 11, 14, 12), et(2026, 11, 13, 16)),  # Saturday
        (et(2026, 11, 15, 23), et(2026, 11, 13, 16)),  # Sunday night
        (et(2026, 11, 26, 12), et(2026, 11, 25, 16)),  # Thanksgiving
        (et(2026, 11, 27, 12, 30), et(2026, 11, 27, 12, 30)),  # a half day, in session
        (et(2026, 11, 27, 13, 5), et(2026, 11, 27, 13)),  # after its 1 pm close
    ],
)
def test_a_live_quote_time_is_now_in_a_session(now: datetime, expected: datetime) -> None:
    """tastytrade's quotes are real time: made now while a session trades,
    at the last close otherwise. Yahoo's 15-minute delay isn't theirs."""
    assert mc.live_quote_time(now) == expected


def test_a_live_quote_time_after_the_close_is_a_close() -> None:
    assert mc.is_close(mc.live_quote_time(et(2026, 11, 16, 16, 5)))
    assert not mc.is_close(mc.live_quote_time(et(2026, 11, 16, 15, 59)))


def test_a_live_quote_time_reads_any_timezone() -> None:
    assert mc.live_quote_time(datetime(2026, 11, 16, 15, tzinfo=UTC)) == et(2026, 11, 16, 10)


def test_quote_time_reads_any_timezone() -> None:
    utc_saturday = datetime(2026, 11, 14, 17, tzinfo=UTC)
    assert mc.quote_time(utc_saturday) == et(2026, 11, 13, 16)


@pytest.mark.parametrize(
    ("now", "is_open"),
    [
        (et(2026, 11, 16, 9, 29), False),
        (et(2026, 11, 16, 9, 30), True),
        (et(2026, 11, 16, 16, 19), True),  # quotes still settling
        (et(2026, 11, 16, 16, 21), False),
        (et(2026, 11, 14, 12), False),
        (et(2026, 11, 26, 12), False),
        (et(2026, 11, 27, 13, 19), True),  # a half day: settling after 1 pm
        (et(2026, 11, 27, 13, 21), False),
    ],
)
def test_market_open(now: datetime, is_open: bool) -> None:
    assert mc.market_open(now) is is_open


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (et(2026, 11, 16, 17), date(2026, 11, 16)),
        (et(2026, 11, 16, 16, 19), date(2026, 11, 13)),
        (et(2026, 11, 16, 11), date(2026, 11, 13)),
        (et(2026, 11, 14, 12), date(2026, 11, 13)),
        (et(2026, 11, 26, 20), date(2026, 11, 25)),
        (et(2026, 11, 27, 14), date(2026, 11, 27)),  # a half day is done by 1:20
    ],
)
def test_latest_completed_session(now: datetime, expected: date) -> None:
    assert mc.latest_completed_session(now) == expected


def test_years_to_expiry_runs_from_the_quote_time_to_the_expiry_close() -> None:
    """Measured from Friday's close on a Saturday, a 7-day option is 7
    days long, not 6 (which would inflate its IV by about 8%)."""
    t0 = mc.quote_time(et(2026, 11, 14, 12))
    assert mc.years_to_expiry(t0, date(2026, 11, 20)) == pytest.approx(7 / 365)


def test_an_expiry_on_a_half_day_runs_to_one_pm() -> None:
    t0 = mc.quote_time(et(2026, 11, 21, 12))  # Saturday: Friday the 20th's close
    assert mc.years_to_expiry(t0, date(2026, 11, 27)) == pytest.approx((7 * 24 - 3) / 24 / 365)


def test_et_date_of_an_epoch_timestamp() -> None:
    # 2026-11-14 01:00 UTC is still 13 November in New York.
    assert mc.et_date(int(datetime(2026, 11, 14, 1, tzinfo=UTC).timestamp())) == date(2026, 11, 13)


def test_in_a_sessions_first_quarter_hour_the_quotes_are_still_the_last_close() -> None:
    """At 09:31 the delayed quotes are the previous close's, not 09:16's
    (edge-case review: a Monday weekly's IV came out 28% high)."""
    monday = et(2026, 11, 16, 9, 31)
    assert mc.quote_time(monday) == et(2026, 11, 13, 16)
    assert mc.is_close(mc.quote_time(monday))
    assert mc.quote_time(et(2026, 11, 16, 9, 46)) == et(2026, 11, 16, 9, 31)


def test_time_to_expiry_is_elapsed_time_across_a_clock_change() -> None:
    """2026-11-01 ends daylight time: Friday 16:00 to the next Friday 16:00
    is 169 hours, not the 168 a wall-clock subtraction gives."""
    t0 = mc.quote_time(et(2026, 10, 31, 12))  # Saturday: Friday the 30th's close
    assert mc.years_to_expiry(t0, date(2026, 11, 6)) == pytest.approx(169 / 24 / 365)


@pytest.mark.parametrize(
    ("quoted_at", "left"),
    [
        (et(2026, 11, 16, 9, 30), 1.0),
        (et(2026, 11, 16, 12, 45), 0.5),
        (et(2026, 11, 16, 16), 0.0),
        (et(2026, 11, 14, 12), 0.0),  # Saturday
        (et(2026, 11, 27, 11, 15), 0.5),  # a half day: 9:30 to 1:00
    ],
)
def test_the_share_of_a_session_still_to_trade(quoted_at: datetime, left: float) -> None:
    assert mc.session_left(quoted_at) == pytest.approx(left)
