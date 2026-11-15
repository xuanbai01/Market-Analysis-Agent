"""Black-76 pricing and the inversions behind every option figure (ADR 0008)."""
from __future__ import annotations

import math

import pytest

from app.services import options_math as om

# Hull, Options, Futures and Other Derivatives, the standard example:
# S=42, K=40, r=10%, sigma=20%, T=0.5, no dividends.
S, K, R, SIGMA, T = 42.0, 40.0, 0.10, 0.20, 0.5
F, DF = S * math.exp(R * T), math.exp(-R * T)


def test_black76_prices_the_textbook_example() -> None:
    assert om.black76(F, K, T, SIGMA, DF, call=True) == pytest.approx(4.7594, abs=1e-4)
    assert om.black76(F, K, T, SIGMA, DF, call=False) == pytest.approx(0.8086, abs=1e-4)


def test_black76_satisfies_put_call_parity() -> None:
    call = om.black76(F, K, T, SIGMA, DF, call=True)
    put = om.black76(F, K, T, SIGMA, DF, call=False)
    assert call - put == pytest.approx(DF * (F - K), abs=1e-12)


@pytest.mark.parametrize("vol", [0.05, 0.2, 0.6, 1.5, 3.0])
@pytest.mark.parametrize("years", [1 / 365, 30 / 365, 1.0, 2.0])
@pytest.mark.parametrize("log_moneyness", [-0.5, -0.1, 0.0, 0.1, 0.5])
@pytest.mark.parametrize("call", [True, False])
def test_implied_vol_round_trips(vol: float, years: float, log_moneyness: float, call: bool) -> None:
    forward, discount = 100.0, math.exp(-0.04 * years)
    strike = forward * math.exp(log_moneyness)
    price = om.black76(forward, strike, years, vol, discount, call=call)
    intrinsic = discount * max(forward - strike, 0.0) if call else discount * max(strike - forward, 0.0)
    solved = om.implied_vol(price, forward, strike, years, discount, call=call)
    if price - intrinsic < 1e-9:
        # Nothing left above intrinsic to invert (deep in or out of the money,
        # tiny time): the solver says so instead of guessing.
        assert solved is None or solved == pytest.approx(vol, rel=1e-3)
    else:
        assert solved == pytest.approx(vol, rel=1e-6)


@pytest.mark.parametrize(
    ("price", "call"),
    [
        (DF * (F - K) - 0.01, True),  # below intrinsic
        (DF * F + 0.01, True),  # above the forward's value
        (DF * K + 0.01, False),
        (0.0, True),
    ],
)
def test_implied_vol_refuses_prices_outside_the_no_arbitrage_bounds(price: float, call: bool) -> None:
    assert om.implied_vol(price, F, K, T, DF, call=call) is None


def test_implied_vol_needs_time_left() -> None:
    assert om.implied_vol(1.0, F, K, 0.0, DF, call=True) is None


def test_interpolate_is_exact_at_nodes_and_linear_between() -> None:
    xs, ys = [-0.2, 0.0, 0.3], [0.30, 0.25, 0.28]
    assert om.interpolate(0.0, xs, ys) == 0.25
    assert om.interpolate(-0.1, xs, ys) == pytest.approx(0.275)
    assert om.interpolate(0.4, xs, ys) is None
    assert om.interpolate(-0.3, xs, ys) is None


def test_constant_maturity_vol_interpolates_total_variance() -> None:
    t1, t2, tau = 20 / 365, 48 / 365, 30 / 365
    vol, extrapolated = om.constant_maturity_vol([(t1, 0.20), (t2, 0.30)], tau, max_extrapolation=45 / 365)
    w = 0.20**2 * t1 + (0.30**2 * t2 - 0.20**2 * t1) * (tau - t1) / (t2 - t1)
    assert vol == pytest.approx(math.sqrt(w / tau))
    assert extrapolated is False


def test_constant_maturity_vol_is_flat_under_flat_vol() -> None:
    vol, _ = om.constant_maturity_vol([(10 / 365, 0.25), (60 / 365, 0.25)], 30 / 365, max_extrapolation=0.0)
    assert vol == pytest.approx(0.25)


def test_constant_maturity_vol_takes_one_side_only_within_reach_and_says_so() -> None:
    # ``max_extrapolation`` is the distance from the target: for IV30, a lone
    # expiry stands in only if it is within 15 days of 30.
    reach = 15 / 365
    near = om.constant_maturity_vol([(40 / 365, 0.22)], 30 / 365, max_extrapolation=reach)
    assert near == (0.22, True)
    far = om.constant_maturity_vol([(70 / 365, 0.22)], 30 / 365, max_extrapolation=reach)
    assert far == (None, False)
    assert om.constant_maturity_vol([], 30 / 365, max_extrapolation=reach) == (None, False)


def test_realized_vol_is_annualized_zero_mean_close_to_close() -> None:
    # Alternating +1% / -1% log returns: daily sd 0.01, annualized 0.01 * sqrt(252).
    closes = [100.0]
    for i in range(20):
        closes.append(closes[-1] * math.exp(0.01 if i % 2 == 0 else -0.01))
    assert om.realized_vol(closes, 20) == pytest.approx(0.01 * math.sqrt(252))


def test_realized_vol_needs_one_more_close_than_returns() -> None:
    assert om.realized_vol([100.0] * 20, 20) is None
    assert om.realized_vol([100.0, 0.0] * 11, 20) is None  # a non-positive close


@pytest.mark.parametrize("call", [True, False])
def test_delta_strike_has_a_quarter_delta(call: bool) -> None:
    forward, vol, years = 100.0, 0.3, 30 / 365
    strike = om.delta_strike(forward, vol, years, call=call)
    d1 = (math.log(forward / strike) + vol * vol * years / 2) / (vol * math.sqrt(years))
    delta = om.norm_cdf(d1) if call else om.norm_cdf(d1) - 1
    assert delta == pytest.approx(0.25 if call else -0.25, abs=1e-9)
    assert (strike > forward) is call
