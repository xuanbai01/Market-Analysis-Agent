"""
The fear & greed estimate (app/services/market_sentiment.py).

Series are synthetic so each test states the market it describes: a
calm year, then a last day (or 20 days) that breaks out one way.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services import market_sentiment as ms

DAYS = 420  # > 125-day average + a 252-day rank window


def _series(values: list[float], start: date = date(2025, 1, 1)) -> list[tuple[date, float]]:
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def _wavy(base: float, n: int = DAYS, amplitude: float = 0.02) -> list[float]:
    """A calm market: small oscillation around ``base``."""
    return [base * (1 + amplitude * ((i % 10) - 4.5) / 4.5) for i in range(n)]


def _with_tail(values: list[float], tail: list[float]) -> list[float]:
    return values[: len(values) - len(tail)] + tail


@pytest.mark.parametrize(
    ("score", "rating"),
    [
        (0, "extreme_fear"),
        (24.4, "extreme_fear"),
        (25, "fear"),
        (44, "fear"),
        (45, "neutral"),
        (55.4, "neutral"),
        (56, "greed"),
        (75, "greed"),
        (76, "extreme_greed"),
        (100, "extreme_greed"),
    ],
)
def test_rating_bands_follow_cnn(score: float, rating: str) -> None:
    assert ms.rating_for(score) == rating


def test_percentile_of_latest() -> None:
    assert ms.percentile_of_latest([1, 2, 3, 4]) == 100
    assert ms.percentile_of_latest([4, 3, 2, 1]) == 25
    # Only the last ``window`` values count.
    assert ms.percentile_of_latest([100, 1, 2], window=2) == 100


class TestMomentum:
    def test_breakout_above_the_average_is_greed(self) -> None:
        spx = _series(_with_tail(_wavy(5000), [5600]))
        c = ms.momentum(spx)
        assert c is not None
        assert c.score == 100
        assert "above its 125-day average" in c.description

    def test_drop_below_the_average_is_fear(self) -> None:
        spx = _series(_with_tail(_wavy(5000), [4400]))
        c = ms.momentum(spx)
        assert c is not None
        assert c.score < 1
        assert "below its 125-day average" in c.description

    def test_needs_enough_history(self) -> None:
        assert ms.momentum(_series(_wavy(5000, n=150))) is None


class TestVolatility:
    def test_vix_spike_is_fear(self) -> None:
        c = ms.volatility(_series(_with_tail(_wavy(15), [30])))
        assert c is not None
        assert c.score == 0
        assert "VIX is" in c.description and "above its 50-day average" in c.description

    def test_vix_collapse_is_greed(self) -> None:
        c = ms.volatility(_series(_with_tail(_wavy(15), [9])))
        assert c is not None
        assert c.score > 99


class TestReturnSpreads:
    def test_stocks_trailing_bonds_is_fear(self) -> None:
        spx = _series(_with_tail(_wavy(5000), [5000 * (1 - 0.005 * i) for i in range(1, 21)]))
        bonds = _series(_wavy(95))
        c = ms.safe_haven(spx, bonds)
        assert c is not None
        assert c.score < 5
        assert c.description.startswith("Stocks trail Treasuries by")

    def test_junk_leading_treasuries_is_greed(self) -> None:
        junk = _series(_with_tail(_wavy(80), [80 * (1 + 0.003 * i) for i in range(1, 21)]))
        bonds = _series(_wavy(95))
        c = ms.junk_bond_demand(junk, bonds)
        assert c is not None
        assert c.score > 95
        assert c.description.startswith("High-yield bonds lead Treasuries by")

    def test_only_shared_dates_count(self) -> None:
        """A bond series that starts later is aligned by date, not position."""
        spx = _series(_wavy(5000))
        bonds = _series(_wavy(95, n=DAYS - 100), start=date(2025, 1, 1) + timedelta(days=100))
        c = ms.safe_haven(spx, bonds)
        assert c is not None


class TestEstimate:
    def test_averages_the_components(self) -> None:
        spx = _series(_with_tail(_wavy(5000), [4400]))
        vix = _series(_with_tail(_wavy(15), [30]))
        bonds = _series(_wavy(95))
        junk = _series(_wavy(80))
        est = ms.estimate_sentiment(spx, vix, bonds, junk)
        assert est is not None
        assert len(est.components) == 4
        assert est.score == pytest.approx(
            sum(c.score for c in est.components) / 4, abs=0.05
        )
        assert est.rating == ms.rating_for(est.score)
        assert est.as_of == spx[-1][0]
        assert "not CNN" in est.methodology

    def test_scores_with_two_components(self) -> None:
        """Bond ETFs missing: momentum + volatility still make an estimate."""
        est = ms.estimate_sentiment(_series(_wavy(5000)), _series(_wavy(15)), [], [])
        assert est is not None
        assert {c.key for c in est.components} == {"momentum", "volatility"}

    def test_gives_up_below_two_components(self) -> None:
        assert ms.estimate_sentiment(_series(_wavy(5000)), [], [], []) is None
        assert ms.estimate_sentiment([], [], [], []) is None
