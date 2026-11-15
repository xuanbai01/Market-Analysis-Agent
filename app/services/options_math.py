"""
The math behind every option figure (ADR 0008). Pure functions, no I/O.

Prices are Black-76 on the forward: the forward comes from put-call
parity on the chain itself (``options_chain``), so discrete dividends and
the 15-minute quote delay are already in it, and the model never needs a
dividend yield. American exercise is ignored: the IVs come from the
out-of-the-money side, where the early-exercise premium is negligible.

``math.erf`` gives the normal CDF, so there's no numpy or scipy to pin.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist

_SQRT_2PI = math.sqrt(2 * math.pi)
TRADING_DAYS = 252

# The IV solver's search range and its first guess's clamp.
VOL_FLOOR, VOL_CAP = 1e-3, 5.0
_GUESS_FLOOR, _GUESS_CAP = 0.05, 3.0
_MAX_ITERATIONS = 100
# Below this much time value (per unit of forward) a price says nothing
# about volatility: it's intrinsic plus rounding.
_MIN_TIME_VALUE = 1e-9
# Converged when the price error is this small a share of the time value.
_PRICE_TOLERANCE = 1e-10
_VOL_TOLERANCE = 1e-12
_MIN_VEGA = 1e-12


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2) / _SQRT_2PI


def _d1(forward: float, strike: float, years: float, vol: float) -> float:
    return (math.log(forward / strike) + vol * vol * years / 2) / (vol * math.sqrt(years))


def black76(forward: float, strike: float, years: float, vol: float, discount: float, *, call: bool) -> float:
    """Price of a European option on ``forward``; ``discount`` is e^(-rT)."""
    d1 = _d1(forward, strike, years, vol)
    d2 = d1 - vol * math.sqrt(years)
    if call:
        return discount * (forward * norm_cdf(d1) - strike * norm_cdf(d2))
    return discount * (strike * norm_cdf(-d2) - forward * norm_cdf(-d1))


def vega76(forward: float, strike: float, years: float, vol: float, discount: float) -> float:
    return discount * forward * norm_pdf(_d1(forward, strike, years, vol)) * math.sqrt(years)


def implied_vol(
    price: float, forward: float, strike: float, years: float, discount: float, *, call: bool
) -> float | None:
    """The Black-76 volatility that prices the option at ``price``, or
    None when no volatility in [VOL_FLOOR, VOL_CAP] does (a price at or
    below intrinsic, above the no-arbitrage cap, or no time left), or when
    the price holds too little time value to say anything.

    Newton's method from the Brenner-Subrahmanyam guess, kept inside a
    bracket that every evaluation narrows; a step that would leave the
    bracket, or a vega too small to divide by, bisects instead.
    """
    if years <= 0 or price <= 0 or forward <= 0 or strike <= 0:
        return None
    intrinsic = discount * max(forward - strike if call else strike - forward, 0.0)
    cap = discount * (forward if call else strike)
    if not intrinsic < price < cap or price - intrinsic <= _MIN_TIME_VALUE * forward:
        return None
    tolerance = _PRICE_TOLERANCE * (price - intrinsic)

    def error(vol: float) -> float:
        return black76(forward, strike, years, vol, discount, call=call) - price

    low, high = VOL_FLOOR, VOL_CAP
    if error(low) > 0 or error(high) < 0:
        return None
    guess = math.sqrt(2 * math.pi / years) * price / (discount * forward)
    vol = min(max(guess, _GUESS_FLOOR), _GUESS_CAP)
    for _ in range(_MAX_ITERATIONS):
        diff = error(vol)
        if abs(diff) <= tolerance:
            return vol
        if diff > 0:
            high = vol
        else:
            low = vol
        if high - low <= _VOL_TOLERANCE:
            return vol
        vega = vega76(forward, strike, years, vol, discount)
        step = vol - diff / vega if vega > _MIN_VEGA else math.nan
        vol = step if low < step < high else (low + high) / 2
    return vol


def delta76(forward: float, strike: float, years: float, vol: float) -> float:
    """A call's forward delta, N(d1); a put's is this minus 1."""
    return norm_cdf(_d1(forward, strike, years, vol))


def gamma76(forward: float, strike: float, years: float, vol: float) -> float:
    """The forward gamma, φ(d1) / (F·σ·√T): how fast ``delta76`` moves with
    the forward. The same for a call and a put at one strike."""
    return norm_pdf(_d1(forward, strike, years, vol)) / (forward * vol * math.sqrt(years))


def interpolate(x: float, xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Linear interpolation on ascending ``xs``; None outside them."""
    if not xs or x < xs[0] or x > xs[-1]:
        return None
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            if x1 == x0:
                return ys[i]
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)
    return ys[0]


def constant_maturity_vol(
    points: Sequence[tuple[float, float]], target: float, *, max_extrapolation: float
) -> tuple[float | None, bool]:
    """The volatility at ``target`` years from (years, vol) points, by
    linear interpolation of total variance (vol² · years) between the two
    points around it. With points on one side only, the nearest one stands
    in when it is within ``max_extrapolation`` years of the target, and the
    flag says so. Returns (vol, extrapolated)."""
    ordered = sorted(points)
    below = [p for p in ordered if p[0] <= target]
    above = [p for p in ordered if p[0] >= target]
    if below and above:
        (t1, v1), (t2, v2) = below[-1], above[0]
        if t2 == t1:
            return v1, False
        w1, w2 = v1 * v1 * t1, v2 * v2 * t2
        w = w1 + (w2 - w1) * (target - t1) / (t2 - t1)
        return (math.sqrt(w / target) if w > 0 else None), False
    nearest = min(ordered, key=lambda p: abs(p[0] - target), default=None)
    if nearest is not None and abs(nearest[0] - target) <= max_extrapolation:
        return nearest[1], True
    return None, False


def realized_vol(closes: Sequence[float], window: int) -> float | None:
    """Annualized close-to-close volatility of the last ``window`` daily log
    returns, zero mean (the convention options traders compare IV with)."""
    if len(closes) < window + 1:
        return None
    recent = closes[-(window + 1):]
    if any(c <= 0 for c in recent):
        return None
    squares = sum(math.log(b / a) ** 2 for a, b in zip(recent, recent[1:], strict=False))
    return math.sqrt(TRADING_DAYS / window * squares)


def delta_strike(forward: float, vol: float, years: float, *, call: bool, delta: float = 0.25) -> float:
    """The strike whose Black-76 forward delta is ``delta`` (a call) or
    ``-delta`` (a put) at a flat ``vol``."""
    z = NormalDist().inv_cdf(1 - delta)
    spread = vol * math.sqrt(years)
    return forward * math.exp((z if call else -z) * spread + spread * spread / 2)
