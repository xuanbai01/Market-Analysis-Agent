"""The earnings move the options price, and the moves past reports made
(ADR 0008). Smiles are built from a known model: a per-session variance
for 40% vol, plus an 8% one-standard-deviation report move on the
reaction session; the right method gets both back."""
from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from app.services import market_calendar as mc
from app.services import options_earnings as oe
from app.services.earnings_calendar import Announcement
from app.services.options_metrics import Smile

QUOTED_AT = datetime(2026, 11, 13, 16, tzinfo=mc.ET)  # Friday's close
BASE_VOL, EVENT_SIGMA = 0.40, 0.08
PER_SESSION = BASE_VOL**2 / 252


def _smile(expiry: date, reaction: date | None, event: float = EVENT_SIGMA) -> Smile:
    years = mc.years_to_expiry(QUOTED_AT, expiry)
    sessions = mc.sessions_between(QUOTED_AT.date(), expiry)
    w = PER_SESSION * sessions + (event**2 if reaction and expiry >= reaction else 0.0)
    return Smile(expiry, years, 100.0, True, 1.0, math.sqrt(w / years), (), ())


WEEKLIES = [date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 27), date(2026, 12, 4)]


def test_two_expiries_after_the_report_give_the_event_and_the_base() -> None:
    """NVDA, after the close on Tue 17 Nov: Wednesday trades on it. The
    only expiry before it is Monday, one session out, too short to trust,
    so the move comes from two expiries after (18 Nov and 27 Nov)."""
    reaction = date(2026, 11, 18)
    smiles = [_smile(e, reaction) for e in WEEKLIES]
    move = oe.event_move(smiles, QUOTED_AT, (reaction, reaction), estimated=False)
    assert move.refused is None
    assert move.method == "two_after"
    assert move.expiries == (date(2026, 11, 18), date(2026, 11, 27))
    assert move.event_sigma == pytest.approx(EVENT_SIGMA, rel=1e-9)
    assert move.base_vol == pytest.approx(BASE_VOL, rel=1e-9)
    assert move.implied_move == pytest.approx(math.sqrt(2 / math.pi) * EVENT_SIGMA, rel=1e-9)


def test_an_expiry_before_and_one_after_give_the_event() -> None:
    reaction = date(2026, 12, 2)  # after the close on 1 Dec
    smiles = [_smile(e, reaction) for e in WEEKLIES]
    move = oe.event_move(smiles, QUOTED_AT, (reaction, reaction), estimated=False)
    assert move.method == "before_and_after"
    assert move.expiries == (date(2026, 11, 27), date(2026, 12, 4))
    assert move.event_sigma == pytest.approx(EVENT_SIGMA, rel=1e-9)
    assert move.base_vol == pytest.approx(BASE_VOL, rel=1e-9)


def test_unknown_timing_needs_expiries_clear_of_both_possible_sessions() -> None:
    """Reported on 1 Dec at an unknown time: 1 Dec or 2 Dec trades on it."""
    smiles = [_smile(e, date(2026, 12, 1)) for e in WEEKLIES]
    move = oe.event_move(smiles, QUOTED_AT, (date(2026, 12, 1), date(2026, 12, 2)), estimated=False)
    assert move.expiries == (date(2026, 11, 27), date(2026, 12, 4))


def test_a_report_months_out_is_refused_not_guessed() -> None:
    """AAPL reports 28 Jan; its first expiry after is 97 days out, and a
    straddle that long says little about the report itself."""
    smiles = [_smile(e, None) for e in WEEKLIES] + [_smile(date(2027, 2, 19), date(2027, 1, 29))]
    move = oe.event_move(smiles, QUOTED_AT, (date(2027, 1, 29), date(2027, 1, 29)), estimated=False)
    assert move.event_sigma is None and move.implied_move is None
    assert "days out" in (move.refused or "")


def test_negative_event_variance_is_refused() -> None:
    reaction = date(2026, 12, 2)
    smiles = [_smile(e, reaction, event=0.0) for e in WEEKLIES]
    # A cheaper vol after the report than before it: no room for an event.
    smiles[-1] = Smile(date(2026, 12, 4), smiles[-1].years, 100.0, True, 1.0, 0.30, (), ())
    move = oe.event_move(smiles, QUOTED_AT, (reaction, reaction), estimated=False)
    assert move.event_sigma is None
    assert move.refused is not None


def test_an_estimated_date_next_to_an_expiry_is_refused() -> None:
    reaction = date(2026, 12, 2)
    smiles = [_smile(e, reaction) for e in WEEKLIES]
    move = oe.event_move(smiles, QUOTED_AT, (reaction, reaction), estimated=True)
    assert move.event_sigma is None
    assert "estimate" in (move.refused or "")


def test_no_report_date_is_refused() -> None:
    move = oe.event_move([_smile(e, None) for e in WEEKLIES], QUOTED_AT, None, estimated=False)
    assert move.refused == "no earnings date"


def _a(y: int, m: int, d: int, hh: int) -> Announcement:
    when = datetime(y, m, d, hh, tzinfo=mc.ET)
    from app.services.earnings_calendar import timing_of

    return Announcement(when, timing_of(when), True)


CLOSES = (
    (date(2026, 8, 25), 100.0),
    (date(2026, 8, 26), 101.0),  # NVDA reports after this close
    (date(2026, 8, 27), 95.0),
    (date(2026, 10, 26), 60.0),  # KO reports before the next open
    (date(2026, 10, 27), 63.0),
    (date(2026, 10, 28), 62.0),
)


def test_past_moves_measure_each_report_across_its_reaction() -> None:
    moves = oe.past_moves([_a(2026, 8, 26, 16), _a(2026, 10, 27, 6)], CLOSES)
    assert [(m.announced, m.timing) for m in moves] == [
        (date(2026, 8, 26), "after_close"),
        (date(2026, 10, 27), "before_open"),
    ]
    assert moves[0].move == pytest.approx(math.log(95.0 / 101.0))
    assert moves[1].move == pytest.approx(math.log(63.0 / 60.0))


def test_an_unknown_time_spans_the_session_before_to_the_session_after() -> None:
    moves = oe.past_moves([_a(2026, 8, 26, 0)], CLOSES)
    assert moves[0].move == pytest.approx(math.log(95.0 / 100.0))
    assert moves[0].spans_extra_day is True


def test_a_report_without_its_closes_is_skipped() -> None:
    assert oe.past_moves([_a(2026, 9, 10, 16)], CLOSES) == []


def test_only_the_last_eight_reports_are_kept() -> None:
    days = [date(2024, 1, 2 + i) for i in range(10)]
    closes = tuple((d, 100.0 + i) for i, d in enumerate(days)) + ((date(2024, 1, 12), 111.0),)
    reports = [_a(d.year, d.month, d.day, 16) for d in days if mc.is_session(d)]
    moves = oe.past_moves(reports, closes)
    assert len(moves) <= oe.PAST_LIMIT
    assert moves == sorted(moves, key=lambda m: m.announced)
