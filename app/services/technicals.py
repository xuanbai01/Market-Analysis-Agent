"""
Technical indicators. Pure functions — given a list of closing prices
(oldest first, newest last) they return a number or None. No I/O, no
DB, no state. Makes them trivially testable and cheap to call inline
from `get_latest_snapshot`.

Indicators implemented:

  - SMA(N): simple moving average over the last N closes.
  - RSI(14): relative strength index using a simple arithmetic mean of
    gains and losses (not Wilder's exponential smoothing). The simple
    variant is well-defined, matches most textbook explanations, and
    avoids the "first-value bootstrap" ambiguity of Wilder's recursion.
    We can swap to Wilder's later if the difference starts mattering —
    the two agree within ~1 point for a stable trend.
"""
from __future__ import annotations

from statistics import fmean

from app.schemas.market import Technicals

# How many bars back the slowest indicator needs. The repository fetches
# this many rows so all four technicals can be computed in one query.
LOOKBACK_BARS = 200
RSI_PERIOD = 14


def sma(closes: list[float], period: int) -> float | None:
    """Mean of the last ``period`` closes, or None if there aren't enough."""
    if len(closes) < period:
        return None
    return fmean(closes[-period:])


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """
    RSI(period) on the last ``period`` price changes (requires
    ``period + 1`` closes). Returns a value in [0, 100], or None if we
    don't have enough history.

    Edge cases:
      - all gains, no losses → 100.0 (saturated up)
      - all losses, no gains → 0.0   (saturated down)
      - perfectly flat        → 50.0 (neutral; no momentum either way)
    """
    if len(closes) < period + 1:
        return None

    window = closes[-(period + 1):]
    changes = [window[i] - window[i - 1] for i in range(1, len(window))]
    gains = [max(c, 0.0) for c in changes]
    losses = [-min(c, 0.0) for c in changes]
    avg_gain = fmean(gains)
    avg_loss = fmean(losses)

    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_technicals(closes: list[float]) -> Technicals:
    """Bundle the four standard technicals into the API response schema."""
    return Technicals(
        rsi=rsi(closes, RSI_PERIOD),
        sma20=sma(closes, 20),
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
    )
