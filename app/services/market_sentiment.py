"""
A fear & greed estimate from free daily prices.

CNN's Fear & Greed Index has no public API and refuses automated
clients, so the market strip shows our own estimate instead, built the
way CNN describes its index: several market indicators, each ranked
against its own past year, averaged into 0 (extreme fear) – 100
(extreme greed). It is labelled as an estimate everywhere it appears.

Four of CNN's seven indicators can be built from free daily closes:

  momentum          S&P 500 vs its 125-day average      higher = greed
  volatility        VIX vs its 50-day average           higher = fear
  safe_haven        S&P 500 minus Treasuries, 20-day return
                                                        higher = greed
  junk_bond_demand  high-yield minus Treasuries, 20-day return
                                                        higher = greed

(Breadth, new highs vs lows and put/call need data we don't have.)

Each indicator's latest value is scored as its percentile among the
last year of values; the estimate is the mean of the components that
have enough history. Pure functions over ``[(date, close), ...]``
lists, ascending by date — no network, no pandas.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.schemas.market_overview import (
    SentimentComponent,
    SentimentEstimate,
    SentimentRating,
)

Series = Sequence[tuple[date, float]]

RANK_WINDOW = 252  # trading days in a year
MIN_RANKED_POINTS = 60  # fewer and a percentile is noise
MOMENTUM_AVERAGE_DAYS = 125
VOLATILITY_AVERAGE_DAYS = 50
RETURN_DAYS = 20
MIN_COMPONENTS = 2

METHODOLOGY = (
    "Our estimate, not CNN's index. Each indicator is ranked against its own "
    "past year (0 = most fearful, 100 = most greedy) and the ranks are averaged."
)

# Upper bound (inclusive) of each rating band, on the rounded score.
_RATING_BANDS: tuple[tuple[int, SentimentRating], ...] = (
    (24, "extreme_fear"),
    (44, "fear"),
    (55, "neutral"),
    (75, "greed"),
    (100, "extreme_greed"),
)


def rating_for(score: float) -> SentimentRating:
    rounded = round(score)
    for upper, rating in _RATING_BANDS:
        if rounded <= upper:
            return rating
    return "extreme_greed"


def percentile_of_latest(values: Sequence[float], window: int = RANK_WINDOW) -> float:
    """Share of the last ``window`` values at or below the latest one, in %."""
    recent = values[-window:]
    latest = recent[-1]
    return 100.0 * sum(1 for v in recent if v <= latest) / len(recent)


def _vs_moving_average(series: Series, days: int) -> list[tuple[date, float]]:
    """Each close relative to its trailing ``days``-day average (0.02 = 2% above)."""
    out: list[tuple[date, float]] = []
    closes = [c for _, c in series]
    running = sum(closes[:days])
    for i in range(days - 1, len(closes)):
        if i >= days:
            running += closes[i] - closes[i - days]
        average = running / days
        out.append((series[i][0], closes[i] / average - 1))
    return out


def _trailing_returns(series: Series, days: int) -> dict[date, float]:
    return {
        series[i][0]: series[i][1] / series[i - days][1] - 1
        for i in range(days, len(series))
    }


def _return_spread(lead: Series, lag: Series, days: int) -> list[tuple[date, float]]:
    """``lead``'s trailing return minus ``lag``'s, on the dates both traded."""
    a = _trailing_returns(lead, days)
    b = _trailing_returns(lag, days)
    return [(d, a[d] - b[d]) for d in sorted(a.keys() & b.keys())]


def _score(indicator: list[tuple[date, float]], *, higher_is_greed: bool) -> float | None:
    if len(indicator) < MIN_RANKED_POINTS:
        return None
    pct = percentile_of_latest([v for _, v in indicator])
    return pct if higher_is_greed else 100.0 - pct


def _abs_pct(value: float) -> str:
    return f"{abs(value) * 100:.1f}%"


def momentum(spx: Series) -> SentimentComponent | None:
    indicator = _vs_moving_average(spx, MOMENTUM_AVERAGE_DAYS)
    score = _score(indicator, higher_is_greed=True)
    if score is None:
        return None
    latest = indicator[-1][1]
    side = "above" if latest >= 0 else "below"
    return SentimentComponent(
        key="momentum",
        label="Market momentum",
        score=round(score, 1),
        description=f"S&P 500 is {_abs_pct(latest)} {side} its {MOMENTUM_AVERAGE_DAYS}-day average",
    )


def volatility(vix: Series) -> SentimentComponent | None:
    indicator = _vs_moving_average(vix, VOLATILITY_AVERAGE_DAYS)
    score = _score(indicator, higher_is_greed=False)
    if score is None:
        return None
    latest = indicator[-1][1]
    side = "above" if latest >= 0 else "below"
    return SentimentComponent(
        key="volatility",
        label="Volatility",
        score=round(score, 1),
        description=f"VIX is {_abs_pct(latest)} {side} its {VOLATILITY_AVERAGE_DAYS}-day average",
    )


def safe_haven(spx: Series, treasuries: Series) -> SentimentComponent | None:
    indicator = _return_spread(spx, treasuries, RETURN_DAYS)
    score = _score(indicator, higher_is_greed=True)
    if score is None:
        return None
    latest = indicator[-1][1]
    verb = "lead" if latest >= 0 else "trail"
    return SentimentComponent(
        key="safe_haven",
        label="Safe-haven demand",
        score=round(score, 1),
        description=f"Stocks {verb} Treasuries by {abs(latest) * 100:.1f} pts over {RETURN_DAYS} days",
    )


def junk_bond_demand(high_yield: Series, treasuries: Series) -> SentimentComponent | None:
    indicator = _return_spread(high_yield, treasuries, RETURN_DAYS)
    score = _score(indicator, higher_is_greed=True)
    if score is None:
        return None
    latest = indicator[-1][1]
    verb = "lead" if latest >= 0 else "trail"
    return SentimentComponent(
        key="junk_bond_demand",
        label="Junk-bond demand",
        score=round(score, 1),
        description=f"High-yield bonds {verb} Treasuries by {abs(latest) * 100:.1f} pts over {RETURN_DAYS} days",
    )


def estimate_sentiment(
    spx: Series,
    vix: Series,
    treasuries: Series,
    high_yield: Series,
) -> SentimentEstimate | None:
    """The composite, or None when fewer than two components can be scored."""
    components = [
        c
        for c in (
            momentum(spx),
            volatility(vix),
            safe_haven(spx, treasuries),
            junk_bond_demand(high_yield, treasuries),
        )
        if c is not None
    ]
    if len(components) < MIN_COMPONENTS or not spx:
        return None
    score = sum(c.score for c in components) / len(components)
    return SentimentEstimate(
        score=round(score, 1),
        rating=rating_for(score),
        components=components,
        as_of=spx[-1][0],
        methodology=METHODOLOGY,
    )
