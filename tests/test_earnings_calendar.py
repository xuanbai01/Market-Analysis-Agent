"""When a company reports and which session trades on it (ADR 0008): the
options page's earnings move, and the next date the dashboard shows."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from app.services import earnings_calendar as ec
from app.services import market_calendar as mc


def et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=mc.ET)


@pytest.mark.parametrize(
    ("when", "timing"),
    [
        (et(2026, 10, 27, 6, 30), "before_open"),  # KO
        (et(2026, 10, 27, 9, 29), "before_open"),
        (et(2026, 10, 27, 12), "during"),
        (et(2026, 11, 17, 16), "after_close"),  # NVDA
        (et(2026, 11, 17, 0), "unknown"),  # a date with no time
    ],
)
def test_timing_from_the_et_hour(when: datetime, timing: str) -> None:
    assert ec.timing_of(when) == timing


@pytest.mark.parametrize(
    ("day", "timing", "expected"),
    [
        (date(2026, 11, 17), "after_close", (date(2026, 11, 18), date(2026, 11, 18))),
        (date(2026, 10, 27), "before_open", (date(2026, 10, 27), date(2026, 10, 27))),
        (date(2026, 10, 27), "during", (date(2026, 10, 27), date(2026, 10, 27))),
        # Unknown: the report could trade the same day or the next.
        (date(2026, 11, 17), "unknown", (date(2026, 11, 17), date(2026, 11, 18))),
        # After a Friday close: Monday trades on it.
        (date(2026, 11, 13), "after_close", (date(2026, 11, 16), date(2026, 11, 16))),
        # Before the open on Thanksgiving (a holiday): Friday trades on it.
        (date(2026, 11, 26), "before_open", (date(2026, 11, 27), date(2026, 11, 27))),
    ],
)
def test_reaction_session(day: date, timing: str, expected: tuple[date, date]) -> None:
    assert ec.reaction_sessions(day, timing) == expected  # type: ignore[arg-type]


def _frame(rows: list[tuple[datetime, float | None]]) -> pd.DataFrame:
    """yfinance's earnings_dates shape: a tz-aware index, Reported EPS NaN
    for a report still to come."""
    index = pd.DatetimeIndex([pd.Timestamp(w) for w, _ in rows], name="Earnings Date")
    return pd.DataFrame(
        {
            "EPS Estimate": [1.0] * len(rows),
            "Reported EPS": [float("nan") if r is None else r for _w, r in rows],
            "Surprise(%)": [0.0] * len(rows),
        },
        index=index,
    )


NVDA_FRAME = _frame([
    (et(2026, 11, 17, 16), None),
    (et(2026, 8, 26, 16), 1.05),
    (et(2026, 5, 20, 16), 0.96),
])


def test_announcements_read_the_frame_oldest_first() -> None:
    found = ec.announcements(NVDA_FRAME)
    assert [a.when.date() for a in found] == [date(2026, 5, 20), date(2026, 8, 26), date(2026, 11, 17)]
    assert [a.reported for a in found] == [True, True, False]
    assert {a.timing for a in found} == {"after_close"}


def test_announcements_of_nothing() -> None:
    assert ec.announcements(None) == []
    assert ec.announcements(pd.DataFrame()) == []


def test_the_schedule_names_the_next_report_with_its_timing_and_the_past_ones() -> None:
    schedule = ec.schedule(NVDA_FRAME, calendar={"Earnings Date": [date(2026, 11, 17)]})
    assert schedule.next is not None
    assert (schedule.next.when.date(), schedule.next.timing) == (date(2026, 11, 17), "after_close")
    assert [a.when.date() for a in schedule.past] == [date(2026, 5, 20), date(2026, 8, 26)]


def test_a_next_date_only_the_calendar_knows_has_unknown_timing() -> None:
    frame = _frame([(et(2026, 8, 26, 16), 1.05)])
    schedule = ec.schedule(frame, calendar={"Earnings Date": [date(2026, 11, 17)]})
    assert schedule.next is not None
    assert (schedule.next.when.date(), schedule.next.timing) == (date(2026, 11, 17), "unknown")


# The shared rule (moved from earnings.py, unchanged).

def test_a_stale_calendar_date_gives_way_to_the_next_scheduled_row() -> None:
    """KO's calendar kept 2026-10-27 after reporting that day."""
    frame = _frame([(et(2027, 2, 9, 8), None), (et(2026, 10, 27, 6), 0.82)])
    assert ec.next_report_date({"Earnings Date": [date(2026, 10, 27)]}, frame, "2026-10-27") == "2027-02-09"


def test_a_calendar_date_after_the_latest_report_is_kept() -> None:
    frame = _frame([(et(2026, 10, 27, 6), 0.82)])
    assert ec.next_report_date({"Earnings Date": [date(2027, 2, 10)]}, frame, "2026-10-27") == "2027-02-10"


def test_the_schedule_is_cached_per_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_frames(symbol: str) -> tuple[pd.DataFrame, dict[str, object]]:
        calls.append(symbol)
        return NVDA_FRAME, {"Earnings Date": [date(2026, 11, 17)]}

    ec.clear_cache()
    monkeypatch.setattr(ec, "fetch_frames", fake_frames)
    first = ec.fetch_schedule("NVDA")
    again = ec.fetch_schedule("NVDA")
    assert first == again and calls == ["NVDA"]
    ec.clear_cache()


def test_a_failed_fetch_is_an_empty_schedule_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_symbol: str) -> tuple[pd.DataFrame, dict[str, object]]:
        raise RuntimeError("yahoo")

    ec.clear_cache()
    monkeypatch.setattr(ec, "fetch_frames", broken)
    assert ec.fetch_schedule("NVDA") == ec.Schedule(next=None, past=())
    ec.clear_cache()


def test_a_naive_index_is_read_as_new_york_time() -> None:
    """DeepSeek on PR 110: astimezone on a naive time uses the machine's
    zone (UTC on Fly), which would turn a 16:00 report into "during"."""
    frame = _frame([(datetime(2026, 8, 26, 16), 1.05)])
    found = ec.announcements(frame)
    assert found[0].timing == "after_close" and found[0].when.hour == 16
