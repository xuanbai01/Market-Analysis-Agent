"""Positioning for one expiry: open interest, max pain, gamma and delta
exposure, the walls and the gamma flip, on chains small enough to check
by hand."""
from __future__ import annotations

import math
from datetime import date

import pytest

from app.services import options_math as om
from app.services import options_positioning as op
from app.services.options_chain import ExpiryQuotes, Quote
from app.services.options_metrics import Smile

EXPIRY = date(2026, 12, 18)


def q(strike: float, oi: int) -> Quote:
    return Quote(strike=strike, bid=1.0, ask=1.1, volume=0, open_interest=oi, regular=True)


def chain(calls: dict[float, int], puts: dict[float, int]) -> ExpiryQuotes:
    return ExpiryQuotes(
        expiry=EXPIRY,
        calls=tuple(q(k, oi) for k, oi in sorted(calls.items())),
        puts=tuple(q(k, oi) for k, oi in sorted(puts.items())),
    )


def smile(forward: float = 100.0, vol: float = 0.2, years: float = 0.25, strikes=(90.0, 100.0, 110.0)) -> Smile:
    return Smile(
        expiry=EXPIRY, years=years, forward=forward, forward_from_parity=True, discount=1.0,
        atm_vol=vol, points=tuple((k, vol) for k in strikes), quotes=(),
    )


def test_gamma_is_the_slope_of_delta() -> None:
    f, k, t, v, h = 100.0, 105.0, 0.25, 0.3, 1e-3
    slope = (om.delta76(f + h, k, t, v) - om.delta76(f - h, k, t, v)) / (2 * h)
    assert om.gamma76(f, k, t, v) == pytest.approx(slope, rel=1e-6)
    # At the money: N(d1) with d1 = σ√T/2.
    assert om.delta76(100.0, 100.0, 0.25, 0.2) == pytest.approx(om.norm_cdf(0.05))


def test_max_pain_is_the_settle_that_pays_holders_least() -> None:
    # Settle 90: puts at 100 pay 10 × 10 = 100. Settle 100: nothing. Settle 110: calls at 100 pay 100.
    c = chain(calls={100.0: 10, 110.0: 50}, puts={90.0: 40, 100.0: 10})
    assert op.max_pain(c) == 100.0
    assert op.max_pain(chain({}, {})) is None
    assert op.max_pain(chain({100.0: 0}, {100.0: 0})) is None


def test_max_pain_in_one_pass_matches_every_settle_tried() -> None:
    """The running sums against the plain definition, on an uneven chain."""
    calls = {80.0: 5, 95.0: 120, 100.0: 40, 102.5: 300, 120.0: 75, 150.0: 9}
    puts = {60.0: 30, 85.0: 200, 95.0: 60, 100.0: 15, 110.0: 5}
    strikes = sorted(calls.keys() | puts.keys())

    def payout(settle: float) -> float:
        return sum(oi * max(settle - k, 0) for k, oi in calls.items()) + sum(oi * max(k - settle, 0) for k, oi in puts.items())

    assert op.max_pain(chain(calls, puts)) == min(strikes, key=payout)


def test_the_headline_figures_agree_with_the_full_positioning() -> None:
    c = chain(calls={100.0: 300, 105.0: 900, 110.0: 200}, puts={90.0: 200, 95.0: 800, 100.0: 100})
    full = op.positioning(c, smile(), spot=100.0)
    pain, net = op.headline(c, smile())
    assert pain == full.max_pain
    assert net == pytest.approx(full.net_gex, rel=1e-9)


def test_the_headline_of_an_expiry_with_no_open_interest_is_empty() -> None:
    assert op.headline(chain({100.0: 0}, {100.0: 0}), smile()) == (None, None)


def test_gamma_exposure_at_the_money_matches_its_closed_form() -> None:
    # F = S = 100, σ√T = 0.1, d1 = 0.05: Γ·F² per contract-share = φ(0.05) / 0.1 × 100.
    p = op.positioning(chain({100.0: 1000}, {}), smile(), spot=100.0)
    expected = om.norm_pdf(0.05) / 0.1 * 100 * 1000
    assert p.net_gex == pytest.approx(expected, rel=1e-9)
    assert p.call_gex == pytest.approx(expected, rel=1e-9)
    assert p.put_gex == 0
    # Delta exposure: N(d1)·F per share, ×1000 contracts... per 1% move: N(d1)·F·OI.
    assert p.net_dex == pytest.approx(om.norm_cdf(0.05) * 100 * 1000, rel=1e-9)


def test_puts_count_against_gamma_and_carry_negative_delta() -> None:
    p = op.positioning(chain({}, {100.0: 1000}), smile(), spot=100.0)
    assert p.net_gex < 0 and p.put_gex == p.net_gex
    assert p.net_dex == pytest.approx((om.norm_cdf(0.05) - 1) * 100 * 1000, rel=1e-9)


def test_walls_and_totals() -> None:
    c = chain(calls={100.0: 300, 105.0: 900, 110.0: 200}, puts={90.0: 200, 95.0: 800, 100.0: 100})
    p = op.positioning(c, smile(), spot=100.0)
    assert (p.call_open_interest, p.put_open_interest) == (1400, 1100)
    assert p.put_call == pytest.approx(1100 / 1400)
    assert p.call_wall == 105.0
    assert p.put_wall == 95.0
    assert [(t.strike, t.side, t.open_interest) for t in p.top[:3]] == [(105.0, "call", 900), (95.0, "put", 800), (100.0, "call", 300)]


def test_the_gamma_flip_sits_between_put_and_call_open_interest() -> None:
    # Puts at 95 and calls at 105, equal size: net gamma is negative below
    # 100 and positive above, crossing near 100.
    p = op.positioning(chain({105.0: 1000}, {95.0: 1000}), smile(strikes=(80.0, 100.0, 120.0)), spot=100.0)
    assert p.gamma_flip is not None
    assert 98.0 < p.gamma_flip < 102.0


def test_no_flip_when_gamma_never_changes_sign() -> None:
    p = op.positioning(chain({100.0: 500, 110.0: 500}, {}), smile(), spot=100.0)
    assert p.gamma_flip is None


def test_no_flip_when_calls_and_puts_match_at_every_strike() -> None:
    p = op.positioning(chain({95.0: 700, 105.0: 300}, {95.0: 700, 105.0: 300}), smile(), spot=100.0)
    assert p.net_gex == pytest.approx(0.0, abs=1e-6)
    assert p.gamma_flip is None


def test_strikes_beyond_the_smile_take_its_nearest_iv() -> None:
    c = chain(calls={150.0: 1000}, puts={60.0: 1000})
    p = op.positioning(c, smile(), spot=100.0)  # the smile spans 90 to 110 only
    assert math.isfinite(p.net_gex)
    assert {e.strike for e in p.exposure} == {60.0, 150.0}


def test_an_expiry_with_no_open_interest() -> None:
    p = op.positioning(chain({100.0: 0}, {100.0: 0}), smile(), spot=100.0)
    assert (p.call_open_interest, p.put_open_interest, p.put_call) == (0, 0, None)
    assert (p.max_pain, p.call_wall, p.put_wall, p.gamma_flip) == (None, None, None, None)
    assert p.net_gex == 0 and p.top == [] and p.exposure == []


def test_exposure_rows_are_limited_to_the_strikes_shown() -> None:
    c = chain(calls={100.0: 10, 105.0: 10, 150.0: 10}, puts={})
    p = op.positioning(c, smile(), spot=100.0, shown={100.0, 105.0})
    assert [e.strike for e in p.exposure] == [100.0, 105.0]
    # Totals and nets still count every strike.
    assert p.call_open_interest == 30


def test_the_assumption_is_stated_for_gamma_and_delta_is_the_options_own() -> None:
    p = op.positioning(chain({100.0: 10}, {}), smile(), spot=100.0)
    assert "dealer" in p.assumption.lower()
    assert "delta exposure is the open options' own delta" in p.assumption.lower()
