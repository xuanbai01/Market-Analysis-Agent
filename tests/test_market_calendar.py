"""NYSE sessions and quote times (ADR 0008): option IVs are measured to
the minute from the time the quotes were made, so the calendar has to be
right on holidays and weekends."""
from __future__ import annotations

from datetime import date, datetime

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
    ],
)
def test_quote_time(now: datetime, expected: datetime) -> None:
    assert mc.quote_time(now) == expected


def test_quote_time_reads_any_timezone() -> None:
    utc_saturday = datetime(2026, 11, 14, 17, tzinfo=mc.UTC)
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
    ],
)
def test_latest_completed_session(now: datetime, expected: date) -> None:
    assert mc.latest_completed_session(now) == expected


def test_years_to_expiry_runs_from_the_quote_time_to_the_expiry_close() -> None:
    """Measured from Friday's close on a Saturday, a 7-day option is 7
    days long, not 6 (which would inflate its IV by about 8%)."""
    t0 = mc.quote_time(et(2026, 11, 14, 12))
    assert mc.years_to_expiry(t0, date(2026, 11, 20)) == pytest.approx(7 / 365)


def test_et_date_of_an_epoch_timestamp() -> None:
    # 2026-11-14 01:00 UTC is still 13 November in New York.
    assert mc.et_date(int(datetime(2026, 11, 14, 1, tzinfo=mc.UTC).timestamp())) == date(2026, 11, 13)
