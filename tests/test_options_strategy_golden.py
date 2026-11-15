"""The strategy builder's numbers, worked out here by a different route
(ADR 0008, PR4).

The builder (``frontend/src/lib/options-strategy.ts``) gets the chance that
the stock ends above a strike in closed form, skew included, and the
probability of profit from the breakevens. This file gets the same figures
from ``app.services.options_math`` the long way: the chance of ending
above K as the slope of Black-76 call prices along the smile (a finite
difference), and the probability of profit by summing that distribution
over a fine price grid where the payoff is positive. The results are
stored in a JSON file the frontend tests read, so the two languages are
held to each other.

Regenerate after a deliberate change:
``UPDATE_STRATEGY_GOLDEN=1 uv run pytest tests/test_options_strategy_golden.py``.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from app.services import options_math as om

GOLDEN = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "options-strategy.golden.json"

# (ln(K/F), IV): a put-skewed short-dated smile like NVDA's, and a flat one.
SMILES: dict[str, dict[str, Any]] = {
    "skewed": {
        "forward": 163.03,
        "years": 28 / 365,
        "points": [(-0.3, 0.80), (-0.15, 0.66), (-0.05, 0.61), (0.0, 0.60), (0.05, 0.595), (0.15, 0.60), (0.3, 0.68)],
    },
    "flat": {"forward": 100.0, "years": 1.0, "points": [(-0.5, 0.2), (0.5, 0.2)]},
}

NORM_XS = [-3.0, -1.5, -0.1, 0.0, 0.25, 1.0, 2.5]

_SKEWED_KNOTS = [SMILES["skewed"]["forward"] * math.exp(x) for x in (-0.15, -0.05, 0.05)]
# Between the smile's points, and on them: a real leg's strike is one of
# them, where the chance above takes the mean of the slopes either side.
PROB_ABOVE = (
    [("skewed", k) for k in (120.0, 141.0, 150.0, 158.0, 170.0, 185.0, 200.0, *_SKEWED_KNOTS)]
    + [("flat", 100.0), ("flat", 120.0)]
)

POP: list[dict[str, Any]] = [
    {"smile": "skewed", "legs": [("call", 1, 165.0, 10.0)]},
    {"smile": "skewed", "legs": [("put", -1, 150.0, 5.3), ("put", 1, 140.0, 2.8)]},
    {
        "smile": "skewed",
        "legs": [("put", 1, 135.0, 2.0), ("put", -1, 145.0, 3.9), ("call", -1, 185.0, 3.7), ("call", 1, 195.0, 2.1)],
    },
    {"smile": "flat", "legs": [("put", 1, 100.0, 7.0)]},
]

_GRID = 20_000
_TAIL_SIGMAS = 10


def _vol(smile: dict[str, Any], strike: float) -> float:
    """Linear in ln(K/F) between the points, flat beyond them."""
    xs = [p[0] for p in smile["points"]]
    ys = [p[1] for p in smile["points"]]
    x = math.log(strike / smile["forward"])
    inside = om.interpolate(x, xs, ys)
    if inside is not None:
        return inside
    return ys[0] if x < xs[0] else ys[-1]


def _call(smile: dict[str, Any], strike: float) -> float:
    return om.black76(smile["forward"], strike, smile["years"], _vol(smile, strike), 1.0, call=True)


def _prob_above(smile: dict[str, Any], strike: float) -> float:
    """−dC/dK along the smile: the risk-neutral chance of ending above K.
    On a smile point the difference straddles the kink, which is the mean
    of the slopes either side; a small step keeps the error out of sight."""
    h = 1e-6 * smile["forward"]
    return -(_call(smile, strike + h) - _call(smile, strike - h)) / (2 * h)


def _payoff(legs: list[tuple[str, int, float, float]], price: float) -> float:
    cost = sum(side * premium for _kind, side, _k, premium in legs)
    value = sum(
        side * (max(price - k, 0.0) if kind == "call" else max(k - price, 0.0)) for kind, side, k, _p in legs
    )
    return value - cost


def _positive_share(a: float, b: float, pa: float, pb: float) -> float:
    """The share of [a, b] where a payoff linear between pa and pb is positive."""
    if pa > 0 and pb > 0:
        return 1.0
    if pa <= 0 and pb <= 0:
        return 0.0
    root = a + (b - a) * pa / (pa - pb)
    return (root - a) / (b - a) if pa > 0 else (b - root) / (b - a)


def _pop(smile: dict[str, Any], legs: list[tuple[str, int, float, float]]) -> float:
    spread = _TAIL_SIGMAS * max(p[1] for p in smile["points"]) * math.sqrt(smile["years"])
    lo, hi = math.log(smile["forward"]) - spread, math.log(smile["forward"]) + spread
    grid = [math.exp(lo + (hi - lo) * i / _GRID) for i in range(_GRID + 1)]
    above = [_prob_above(smile, s) for s in grid]
    pays = [_payoff(legs, s) for s in grid]
    prob = (1 - above[0]) * (pays[0] > 0) + above[-1] * (pays[-1] > 0)  # the far tails
    for i in range(_GRID):
        prob += (above[i] - above[i + 1]) * _positive_share(grid[i], grid[i + 1], pays[i], pays[i + 1])
    return prob


def golden() -> dict[str, Any]:
    return {
        "generated_by": "tests/test_options_strategy_golden.py, from app.services.options_math",
        "smiles": {name: {**s, "points": [list(p) for p in s["points"]]} for name, s in SMILES.items()},
        "norm_cdf": [{"x": x, "p": om.norm_cdf(x)} for x in NORM_XS],
        "prob_above": [{"smile": name, "strike": k, "prob": _prob_above(SMILES[name], k)} for name, k in PROB_ABOVE],
        "pop": [
            {
                "smile": case["smile"],
                "legs": [{"kind": kind, "side": side, "strike": k, "premium": p} for kind, side, k, p in case["legs"]],
                "pop": _pop(SMILES[case["smile"]], case["legs"]),
            }
            for case in POP
        ],
    }


def _numbers(value: Any) -> list[float]:
    if isinstance(value, dict):
        return [n for key in sorted(value) for n in _numbers(value[key])]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return [float(value)] if isinstance(value, int | float) and not isinstance(value, bool) else []


def test_the_golden_file_is_what_python_computes() -> None:
    computed = golden()
    if os.environ.get("UPDATE_STRATEGY_GOLDEN"):
        GOLDEN.write_text(json.dumps(computed, indent=2) + "\n", encoding="utf-8")
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _numbers(stored) == pytest.approx(_numbers(computed), rel=1e-9, abs=1e-12)


def test_a_flat_smile_gives_the_textbook_answer() -> None:
    """With no skew the chance of ending above K is N(d2); checks the route."""
    flat = SMILES["flat"]
    d2 = (math.log(100 / 100) - 0.2**2 / 2) / 0.2
    assert _prob_above(flat, 100.0) == pytest.approx(om.norm_cdf(d2), abs=1e-8)


def test_the_brute_force_pop_matches_a_closed_form_case() -> None:
    """A long put on a flat smile profits below its breakeven: N(−d2)."""
    k, premium = 100.0, 7.0
    breakeven = k - premium
    d2 = (math.log(100 / breakeven) - 0.2**2 / 2) / 0.2
    assert _pop(SMILES["flat"], [("put", 1, k, premium)]) == pytest.approx(1 - om.norm_cdf(d2), abs=1e-6)
