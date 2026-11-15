"""The figures a snapshot stores, from a chain priced with known vols
(ADR 0008): every mid is a Black-76 price, so the right method gets the
vols back exactly."""
from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pytest

from app.services import market_calendar as mc
from app.services import options_math as om
from app.services import options_metrics as metrics
from app.services.options_chain import ChainFetch, ExpiryQuotes, Quote

QUOTED_AT = datetime(2026, 11, 13, 16, tzinfo=mc.ET)  # a Friday close
SPOT, RATE, DIVIDEND = 100.0, 0.04, 0.02
HALF_SPREAD = 0.01


def _forward(expiry: date) -> float:
    years = mc.years_to_expiry(QUOTED_AT, expiry)
    return SPOT * math.exp((RATE - DIVIDEND) * years)


def _chain(
    expiry: date,
    vol_at: Callable[[float], float],
    strikes: list[float] | None = None,
    *,
    forward: float | None = None,
) -> ExpiryQuotes:
    years = mc.years_to_expiry(QUOTED_AT, expiry)
    fwd = forward if forward is not None else _forward(expiry)
    discount = math.exp(-RATE * years)
    calls, puts = [], []
    for k in strikes or [70 + 2.5 * i for i in range(25)]:
        vol = vol_at(math.log(k / fwd))
        for side, out in ((True, calls), (False, puts)):
            price = om.black76(fwd, k, years, vol, discount, call=side)
            bid = max(price - HALF_SPREAD, 0.0)
            out.append(Quote(k, bid, bid + 2 * HALF_SPREAD if bid else 0.0, 10, 100, True))
    return ExpiryQuotes(expiry, tuple(calls), tuple(puts))


def _flat(vol: float) -> Callable[[float], float]:
    return lambda _k: vol


def _fetch(chains: dict[date, ExpiryQuotes], closes: tuple[tuple[date, float], ...] = ()) -> ChainFetch:
    return ChainFetch(
        symbol="TEST", spot=SPOT, market_time=int(QUOTED_AT.timestamp()), dividend_yield=DIVIDEND,
        expiries=tuple(sorted(chains)), chains=chains, closes=closes,
    )


EXP_20 = date(2026, 12, 3)  # 20 days after the quote
EXP_48 = date(2026, 12, 31)


def test_the_forward_comes_from_put_call_parity() -> None:
    smile = metrics.smile(_chain(EXP_20, _flat(0.25)), SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert smile is not None
    assert smile.forward == pytest.approx(_forward(EXP_20), rel=1e-4)
    assert smile.forward_from_parity is True


def test_a_flat_vol_comes_back_at_the_money_and_across_the_smile() -> None:
    smile = metrics.smile(_chain(EXP_20, _flat(0.25)), SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert smile is not None and smile.atm_vol == pytest.approx(0.25, abs=1e-6)
    assert len(smile.points) >= 5
    assert all(v == pytest.approx(0.25, abs=1e-6) for _k, v in smile.points)


def test_the_smile_keeps_strikes_near_the_money_only() -> None:
    smile = metrics.smile(_chain(EXP_20, _flat(0.25)), SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert smile is not None
    reach = metrics.MONEYNESS_SIGMAS * 0.25 * math.sqrt(smile.years)
    assert all(abs(math.log(k / smile.forward)) <= reach + 1e-12 for k, _v in smile.points)
    assert len(smile.points) <= metrics.MAX_STRIKES


def test_a_dense_chain_spreads_its_strikes_across_the_wings() -> None:
    """QQQ lists a strike every dollar: the 25 nearest covered only ±1.8%
    around the money, short of the 25-delta wings, so skew read None
    (live, 2026-11-14). The cap spreads its strikes over the whole window."""
    dense = [70 + 0.5 * i for i in range(121)]
    skewed = lambda k: 0.25 - 0.3 * k  # noqa: E731
    chain = _chain(EXP_20, skewed, dense)
    smile = metrics.smile(chain, SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert smile is not None and len(smile.points) <= metrics.MAX_STRIKES
    reach = metrics.MONEYNESS_SIGMAS * smile.atm_vol * math.sqrt(smile.years)
    logs = [math.log(k / smile.forward) for k, _v in smile.points]
    assert min(logs) <= -0.8 * reach and max(logs) >= 0.8 * reach
    result = metrics.snapshot_metrics(_fetch({EXP_20: chain}), QUOTED_AT, RATE)
    assert result.skew25 is not None


def test_a_forward_far_from_spot_falls_back_and_says_so() -> None:
    """Quotes whose parity forward is 10% off spot are stale or broken."""
    chain = _chain(EXP_20, _flat(0.25), forward=110.0)
    smile = metrics.smile(chain, SPOT, QUOTED_AT, RATE, DIVIDEND)
    assert smile is not None
    assert smile.forward_from_parity is False
    assert smile.forward == pytest.approx(_forward(EXP_20), rel=1e-9)


def test_usable_quotes() -> None:
    assert metrics.usable(Quote(100, 1.00, 1.20, 0, 0, True))
    assert metrics.usable(Quote(100, 0.03, 0.06, 0, 0, True))  # wide in percent, inside $0.05
    assert not metrics.usable(Quote(100, 0.0, 0.10, 0, 0, True))  # no bid
    assert not metrics.usable(Quote(100, 1.00, 1.40, 0, 0, True))  # spread over 25% of mid
    assert not metrics.usable(Quote(100, 1.20, 1.00, 0, 0, True))  # crossed
    assert not metrics.usable(Quote(100, 1.00, 1.20, 0, 0, False))  # adjusted contract


def test_a_chain_without_two_sided_quotes_has_no_smile() -> None:
    dead = ExpiryQuotes(EXP_20, (Quote(100, 0.0, 0.0, 0, 0, True),), (Quote(100, 0.0, 0.0, 0, 0, True),))
    assert metrics.smile(dead, SPOT, QUOTED_AT, RATE, DIVIDEND) is None


def test_snapshot_expiries_bracket_30_and_90_days_and_skip_the_first_week() -> None:
    listed = tuple(QUOTED_AT.date() + timedelta(days=d) for d in (3, 7, 14, 28, 35, 63, 91, 182))
    picked = metrics.snapshot_expiries(listed, QUOTED_AT)
    assert [(d - QUOTED_AT.date()).days for d in picked] == [28, 35, 63, 91]


def test_iv30_interpolates_total_variance_between_the_bracketing_expiries() -> None:
    fetched = _fetch({EXP_20: _chain(EXP_20, _flat(0.20)), EXP_48: _chain(EXP_48, _flat(0.30))})
    result = metrics.snapshot_metrics(fetched, QUOTED_AT, RATE)
    t1, t2 = mc.years_to_expiry(QUOTED_AT, EXP_20), mc.years_to_expiry(QUOTED_AT, EXP_48)
    expected, _ = om.constant_maturity_vol([(t1, 0.20), (t2, 0.30)], 30 / 365, max_extrapolation=0.0)
    assert result.iv30 == pytest.approx(expected, abs=1e-6)
    assert result.iv30_extrapolated is False


def test_skew_reads_the_25_delta_wings_of_the_expiry_nearest_30_days() -> None:
    """A smile linear in ln(K/F): put wing richer than the call wing."""
    slope, atm = -0.3, 0.25
    smile_vol = lambda k: atm + slope * k  # noqa: E731
    fetched = _fetch({EXP_20: _chain(EXP_20, smile_vol), EXP_48: _chain(EXP_48, smile_vol)})
    result = metrics.snapshot_metrics(fetched, QUOTED_AT, RATE)
    years = mc.years_to_expiry(QUOTED_AT, EXP_20)
    z = 0.6744897501960817
    expected = -slope * 2 * z * atm * math.sqrt(years)
    assert result.skew25 == pytest.approx(expected, abs=2e-3)


def test_skew_is_refused_when_the_strikes_do_not_reach_the_wings() -> None:
    narrow = [97.5, 100.0, 102.5]
    fetched = _fetch({EXP_20: _chain(EXP_20, _flat(0.25), narrow)})
    assert metrics.snapshot_metrics(fetched, QUOTED_AT, RATE).skew25 is None


def test_realized_vol_uses_completed_sessions_only() -> None:
    days = [QUOTED_AT.date() - timedelta(days=i) for i in range(70, 0, -1)]
    closes = tuple((d, 100.0 * math.exp(0.01 * (i % 2))) for i, d in enumerate(days))
    later = ((QUOTED_AT.date() + timedelta(days=3), 500.0),)  # a bar after the quote: ignored
    fetched = _fetch({EXP_20: _chain(EXP_20, _flat(0.25))}, closes + later)
    result = metrics.snapshot_metrics(fetched, QUOTED_AT, RATE)
    expected = om.realized_vol([c for _d, c in closes], 20)
    assert result.rv20 == pytest.approx(expected)
    assert result.rv60 is not None


def test_open_interest_and_volume_add_up_over_the_fetched_expiries() -> None:
    fetched = _fetch({EXP_20: _chain(EXP_20, _flat(0.25)), EXP_48: _chain(EXP_48, _flat(0.25))})
    result = metrics.snapshot_metrics(fetched, QUOTED_AT, RATE)
    assert result.call_open_interest == 2 * 25 * 100
    assert result.put_volume == 2 * 25 * 10


def test_nothing_usable_reads_as_no_usable_quotes() -> None:
    dead = ExpiryQuotes(EXP_20, (Quote(100, 0.0, 0.0, 0, 0, True),), (Quote(100, 0.0, 0.0, 0, 0, True),))
    result = metrics.snapshot_metrics(_fetch({EXP_20: dead}), QUOTED_AT, RATE)
    assert result.status == "no_usable_quotes"
    assert result.iv30 is None


def test_the_detail_keeps_the_raw_quotes_to_recompute_from() -> None:
    fetched = _fetch({EXP_20: _chain(EXP_20, _flat(0.25))})
    result = metrics.snapshot_metrics(fetched, QUOTED_AT, RATE)
    detail = result.detail
    assert detail["method_version"] == metrics.METHOD_VERSION
    expiry = detail["expiries"][0]
    assert expiry["expiry"] == EXP_20.isoformat()
    assert expiry["quotes"] and len(expiry["quotes"][0]) == 9  # strike, call bid/ask, put bid/ask, OI, volume
