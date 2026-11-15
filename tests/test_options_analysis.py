"""The options page's figures (ADR 0008), from chains priced with known
vols (the metrics tests' builders)."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest

from app.schemas.options import PastMove
from app.services import market_calendar as mc
from app.services import options_analysis as oa
from app.services import options_metrics as metrics
from app.services.earnings_calendar import Announcement, Schedule
from app.services.options_chain import ExpiryQuotes, Quote
from app.services.options_earnings import EventMove
from tests.test_options_metrics import (
    DIVIDEND,
    EXP_20,
    EXP_48,
    QUOTED_AT,
    RATE,
    SPOT,
    _chain,
    _flat,
)

TODAY = QUOTED_AT.date()


def _smile(chain: ExpiryQuotes) -> metrics.Smile:
    s = metrics.smile(chain, SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert s is not None
    return s


def test_report_expiries_aim_at_the_targets_and_include_the_snapshots() -> None:
    """The snapshot's expiries (around 30 and 90 days: 28, 35, 63, 91) are
    read too, so today's IV30 is the stored history's IV30."""
    listed = tuple(TODAY + timedelta(days=d) for d in (3, 5, 7, 10, 14, 17, 21, 28, 35, 42, 49, 63, 91, 182, 364, 728))
    picked = oa.report_expiries(listed, QUOTED_AT, None)
    assert [(d - TODAY).days for d in picked] == [3, 7, 14, 28, 35, 42, 63, 91, 182, 364]


def test_report_expiries_also_bracket_the_report() -> None:
    listed = tuple(TODAY + timedelta(days=d) for d in (3, 5, 7, 10, 14, 17, 21, 28, 35, 42, 49, 63, 91, 182, 364))
    reaction = TODAY + timedelta(days=17)
    picked = oa.report_expiries(listed, QUOTED_AT, (reaction, reaction))
    assert [(d - TODAY).days for d in picked] == [3, 7, 10, 14, 17, 21, 28, 35, 42, 63, 91, 182, 364]


def test_an_expiry_summary_has_the_one_sigma_range_and_the_straddle() -> None:
    chain = _chain(EXP_20, _flat(0.25))
    s = _smile(chain)
    summary = oa.expiry_summary(chain, s, None, QUOTED_AT)
    spread = 0.25 * math.sqrt(s.years)
    assert summary.expected_move == pytest.approx(spread, abs=1e-6)
    assert summary.low == pytest.approx(s.forward * math.exp(-spread), rel=1e-6)
    assert summary.high == pytest.approx(s.forward * math.exp(spread), rel=1e-6)
    assert summary.straddle_strike == 100.0
    call = next(q for q in chain.calls if q.strike == 100.0)
    put = next(q for q in chain.puts if q.strike == 100.0)
    assert summary.straddle == pytest.approx(call.mid + put.mid)
    assert summary.days == pytest.approx(20.0)
    assert summary.sessions == 13  # 16-20 Nov, 23-25 and 27 Nov (Thanksgiving off), 30 Nov-3 Dec
    assert summary.includes_earnings is False


def test_an_expiry_after_the_reaction_includes_the_report() -> None:
    chain = _chain(EXP_20, _flat(0.25))
    reaction = EXP_20 - timedelta(days=2)
    assert oa.expiry_summary(chain, _smile(chain), (reaction, reaction), QUOTED_AT).includes_earnings is True


def test_the_default_expiry_is_the_one_nearest_30_days_at_least_a_week_out() -> None:
    near = TODAY + timedelta(days=3)
    smiles = [_smile(_chain(d, _flat(0.25))) for d in (near, EXP_20, EXP_48)]
    assert oa.default_smile(smiles).expiry == EXP_20  # type: ignore[union-attr]
    assert oa.default_smile([]) is None


def test_the_chain_table_near_the_money() -> None:
    chain = _chain(EXP_20, _flat(0.25))
    s = _smile(chain)
    table = oa.expiry_chain(chain, s)
    strikes = [r.strike for r in table.rows]
    assert strikes == sorted(strikes) and len(strikes) <= oa.MAX_ROWS
    reach = metrics.MONEYNESS_SIGMAS * s.atm_vol * math.sqrt(s.years)
    assert all(abs(math.log(k / s.forward)) <= reach + 1e-12 for k in strikes)
    for row in table.rows:
        assert row.call_delta is not None and 0 < row.call_delta < 1
        assert row.put_delta == pytest.approx(row.call_delta - 1)
        assert row.call_iv == pytest.approx(0.25, abs=1e-4)
    assert {p.side for p in table.smile if p.strike < s.forward} == {"put"}
    assert {p.side for p in table.smile if p.strike >= s.forward} == {"call"}
    assert table.open_interest and all(p.call == 100 and p.put == 100 for p in table.open_interest)


def test_put_call_ratios_over_the_expiries_read() -> None:
    q = lambda oi, vol: Quote(100.0, 1.0, 1.1, vol, oi, True)  # noqa: E731
    chains = [ExpiryQuotes(EXP_20, (q(100, 10),), (q(200, 30),)), ExpiryQuotes(EXP_48, (q(100, 10),), (q(200, 30),))]
    assert oa.put_call_ratios(chains) == (pytest.approx(2.0), pytest.approx(3.0))
    assert oa.put_call_ratios([ExpiryQuotes(EXP_20, (q(0, 0),), (q(5, 5),))]) == (None, None)


def _history(n: int) -> list[tuple[date, float]]:
    return [(date(2026, 1, 1) + timedelta(days=i), 0.10 + 0.001 * i) for i in range(n)]


@pytest.mark.parametrize(("n", "has_percentile", "has_rank"), [(62, False, False), (63, True, False), (125, True, False), (126, True, True)])
def test_percentile_from_63_sessions_and_rank_from_126(n: int, has_percentile: bool, has_rank: bool) -> None:
    history = oa.iv_history(_history(n), 0.15)
    assert history.sessions == n and history.since == date(2026, 1, 1)
    assert (history.percentile is not None) is has_percentile
    assert (history.rank is not None) is has_rank


def test_percentile_and_rank_place_todays_iv30_among_the_stored_ones() -> None:
    points = _history(200)  # 0.100 .. 0.299
    history = oa.iv_history(points, 0.20)
    assert history.percentile == pytest.approx(100 * 101 / 200)  # 0.100..0.200 at or below
    assert history.rank == pytest.approx(100 * (0.20 - 0.10) / (0.299 - 0.10))
    assert oa.iv_history(points, None).percentile is None


def test_claims_carry_units_and_skip_what_is_missing() -> None:
    at = datetime(2026, 11, 15, tzinfo=mc.ET)
    found = oa.claims(
        iv30=0.25, iv90=None, rv20=0.20, rv60=None, skew25=0.05, default=None, put_call_oi=1.5,
        earnings=None, history=oa.iv_history([], 0.25), at=at,
    )
    by_name = {c.description: c for c in found}
    assert by_name["Implied volatility, 30 days (IV30)"].unit == "fraction"
    assert by_name["IV30 minus realized volatility (20 sessions)"].value == pytest.approx(0.05)
    assert by_name["IV30 minus realized volatility (20 sessions)"].unit == "percentage_points"
    assert by_name["25-delta skew, expiry nearest 30 days (put IV minus call IV)"].unit == "percentage_points"
    assert by_name["Put/call open interest, expiries read"].unit == "ratio"
    assert not any("90 days" in d for d in by_name)
    assert all(c.source.tool == "computed.options" for c in found)


def test_the_earnings_block() -> None:
    nxt = Announcement(datetime(2026, 11, 17, 16, tzinfo=mc.ET), "after_close", False)
    past_reports = (Announcement(datetime(2026, 8, 26, 16, tzinfo=mc.ET), "after_close", True),)
    event = EventMove(0.08, 0.0638, 0.4, "two_after", None, (date(2026, 11, 18), date(2026, 11, 27)))
    past = [PastMove(announced=date(2026, 8, 26), timing="after_close", move=-0.06),
            PastMove(announced=date(2026, 5, 20), timing="after_close", move=0.02)]
    block = oa.earnings_block(Schedule(nxt, past_reports), event, past, 160.0, estimated=False)
    assert block is not None
    assert (block.next_date, block.next_timing, block.reaction_date) == (date(2026, 11, 17), "after_close", date(2026, 11, 18))
    assert block.implied_move_usd == pytest.approx(160.0 * 0.0638)
    assert block.past_mean_abs == pytest.approx(0.04)
    assert block.method == "two_after"


def test_a_fund_has_no_earnings_block() -> None:
    event = EventMove(None, None, None, None, "no earnings date", ())
    assert oa.earnings_block(None, event, [], 100.0, estimated=False) is None
