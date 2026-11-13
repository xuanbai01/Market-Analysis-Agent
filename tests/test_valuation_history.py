"""
Year-end valuation multiples (app/services/valuation_history.py, 2026-11).

"Is this expensive against its own history" was the oldest unmet ask
(ADR 0004). A multiple at a fiscal year-end is that day's close divided
by that year's per-share figure. Fixtures use round numbers so every
expected value can be checked by hand.
"""
from __future__ import annotations

import pytest

from app.schemas.research import ClaimHistoryPoint
from app.services import valuation_history as vh


def points(**by_year: float) -> list[ClaimHistoryPoint]:
    return [ClaimHistoryPoint(period=year.removeprefix("y"), value=value) for year, value in by_year.items()]


def by_year(series: list[ClaimHistoryPoint]) -> dict[str, float]:
    return {p.period: round(p.value, 4) for p in series}


# Closes around three December year-ends and one September year-end.
CLOSES = [
    ("2023-12-28", 96.0),
    ("2023-12-29", 100.0),  # last trading day of 2023
    ("2024-01-02", 99.0),
    ("2024-09-27", 150.0),
    ("2024-12-31", 120.0),
    ("2025-12-31", 90.0),
]
ENDS = {2023: "2023-12-31", 2024: "2024-12-31", 2025: "2025-12-31"}


def test_close_on_or_before_takes_the_last_trading_day_up_to_the_date() -> None:
    # 2023-12-31 was a Sunday: the close of Friday the 29th.
    assert vh.close_on_or_before(CLOSES, "2023-12-31") == 100.0
    assert vh.close_on_or_before(CLOSES, "2024-09-27") == 150.0


def test_close_on_or_before_refuses_a_stale_price() -> None:
    """A close from months earlier is not that date's price: a ticker that
    listed later, or a gap in the feed, yields nothing rather than a guess."""
    assert vh.close_on_or_before(CLOSES, "2024-06-30") is None
    assert vh.close_on_or_before(CLOSES, "2020-12-31") is None
    assert vh.close_on_or_before([], "2024-12-31") is None


def test_multiples_are_the_year_end_close_over_that_years_per_share_figure() -> None:
    per_share = {
        "eps_diluted_annual": points(y2023=5.0, y2024=6.0, y2025=4.5),
        "revenue_per_share_annual": points(y2023=50.0, y2024=60.0, y2025=45.0),
        "fcf_per_share_annual": points(y2023=4.0, y2024=5.0, y2025=3.0),
    }
    series = vh.multiples_series(per_share, ENDS, CLOSES)

    assert by_year(series["pe_annual"]) == {"2023": 20.0, "2024": 20.0, "2025": 20.0}
    assert by_year(series["ps_annual"]) == {"2023": 2.0, "2024": 2.0, "2025": 2.0}
    assert by_year(series["pfcf_annual"]) == {"2023": 25.0, "2024": 24.0, "2025": 30.0}


def test_a_fiscal_year_is_priced_at_its_own_period_end() -> None:
    """Apple's year ends in late September; NVDA's in late January."""
    series = vh.multiples_series(
        {"eps_diluted_annual": points(y2024=6.0)},
        {2024: "2024-09-28"},  # a Saturday: Friday the 27th closes at 150
        CLOSES,
    )
    assert by_year(series["pe_annual"]) == {"2024": 25.0}


def test_a_loss_year_has_no_earnings_multiple_but_keeps_price_to_sales() -> None:
    per_share = {
        "eps_diluted_annual": points(y2023=-2.0, y2024=6.0),
        "revenue_per_share_annual": points(y2023=50.0, y2024=60.0),
        "fcf_per_share_annual": points(y2023=-1.0, y2024=5.0),
    }
    series = vh.multiples_series(per_share, ENDS, CLOSES)

    assert by_year(series["pe_annual"]) == {"2024": 20.0}
    assert by_year(series["pfcf_annual"]) == {"2024": 24.0}
    assert by_year(series["ps_annual"]) == {"2023": 2.0, "2024": 2.0}


def test_a_multiple_over_a_near_zero_figure_is_left_out_as_not_meaningful() -> None:
    """EPS of one cent prices at 10,000x, which says nothing and would
    flatten every other year on the chart."""
    series = vh.multiples_series(
        {"eps_diluted_annual": points(y2023=0.01, y2024=6.0)},
        ENDS,
        CLOSES,
    )
    assert by_year(series["pe_annual"]) == {"2024": 20.0}
    assert vh.MAX_MEANINGFUL_MULTIPLE == pytest.approx(200.0)


def test_a_year_with_no_period_end_or_no_price_is_skipped() -> None:
    series = vh.multiples_series(
        {"revenue_per_share_annual": points(y2019=40.0, y2022=45.0, y2024=60.0)},
        {2019: "2019-12-31", 2024: "2024-12-31"},  # no end for 2022; no close near 2019
        CLOSES,
    )
    assert by_year(series["ps_annual"]) == {"2024": 2.0}


def test_every_multiple_key_is_always_present() -> None:
    series = vh.multiples_series({}, {}, [])
    assert set(series) == set(vh.MULTIPLE_KEYS)
    assert all(points == [] for points in series.values())
