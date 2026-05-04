"""
Layout-signal derivation for adaptive dashboard layouts. Phase 4.5.A.

Pure function: ``derive_layout_signals(report) -> LayoutSignals``. Reads
claim values via description matching (same philosophy as the frontend
extractors and the rest of the orchestrator) and returns the typed
``LayoutSignals`` Pydantic object the dashboard renders against.

## Why this is a separate module from research_orchestrator

The orchestrator composes the report. Signal derivation is a single-
input single-output transform on the assembled report — easier to test
in isolation, easier to reuse for the cached-row backfill, and keeps
the orchestrator focused on tool fan-out + section assembly.

## Why no LLM involvement

These signals drive layout *substitution* (the hero swaps Forward P/E
to P/Sales when the company is unprofitable, the page header grows a
"LIQUIDITY WATCH" pill when runway < 6Q, etc.). Layout decisions must
be stable across cache hits and across re-runs. A heuristic over
deterministic claim values is the right contract; an LLM-derived
"vibes-based distress score" would jitter under the same fundamentals.

## Healthy default everywhere

Every helper returns the healthy/None value when:
- the required claim is absent (e.g. report is missing fundamentals)
- the required claim's value is non-numeric or None
- the required history is too short (< 4Q for cash runway, < 3 points
  for slope-based signals)

This matters: ``LayoutSignals()`` with all defaults represents "we
couldn't derive anything, fall back to healthy layout", which is
strictly better UX than guessing wrong on a thin report.
"""
from __future__ import annotations

from typing import Any

from app.schemas.research import (
    Claim,
    ClaimHistoryPoint,
    LayoutSignals,
    ResearchReport,
)

# Description strings — kept in sync with the producer modules:
#   - app/services/fundamentals.py::_DESCRIPTIONS
#   - app/services/earnings.py::_DESCRIPTIONS
# Drift fails loudly because the derivation returns the healthy default
# when the description doesn't match — the dashboard would render as
# healthy regardless of the underlying distress. The orchestrator unit
# tests pin the realistic distressed fixture so any rename surfaces.

_DESC_OPERATING_MARGIN = "Operating margin"
_DESC_NET_PROFIT_MARGIN = "Net profit margin"
_DESC_GROSS_MARGIN = "Gross margin"
_DESC_CASH_PER_SHARE = "Cash + short-term investments per share"
_DESC_DEBT_PER_SHARE = "Total debt per share"
_DESC_FCF_PER_SHARE = "Free cash flow per share"
_DESC_EPS_ACTUAL = "Reported EPS (latest quarter)"
_DESC_BEAT_COUNT = (
    "Number of EPS beats over the last 20 quarters (or fewer if"
    " history is shorter)"
)

_BEAT_RATE_THRESHOLD = 0.30
_RUNWAY_FCF_TTM_QUARTERS = 4
_SLOPE_MIN_POINTS = 3


def _find_claim(report: ResearchReport, description: str) -> Claim | None:
    for section in report.sections:
        for claim in section.claims:
            if claim.description == description:
                return claim
    return None


def _numeric_value(claim: Claim | None) -> float | None:
    if claim is None:
        return None
    v: Any = claim.value
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    return None


def _is_unprofitable_ttm(report: ResearchReport) -> bool:
    """True when either margin claim is strictly negative.

    Uses snapshot value, not history — the signal is about the *latest*
    state, not a long-run trend (the trend-based signals like
    ``debt_rising_cash_falling`` cover that angle separately).
    """
    op_m = _numeric_value(_find_claim(report, _DESC_OPERATING_MARGIN))
    np_m = _numeric_value(_find_claim(report, _DESC_NET_PROFIT_MARGIN))
    if op_m is not None and op_m < 0:
        return True
    if np_m is not None and np_m < 0:
        return True
    return False


def _beat_rate_below_threshold(report: ResearchReport) -> bool:
    """True when EPS beat count / max-history-window is < 30%."""
    count = _numeric_value(_find_claim(report, _DESC_BEAT_COUNT))
    eps_claim = _find_claim(report, _DESC_EPS_ACTUAL)
    if count is None or eps_claim is None:
        return False
    history_len = len(eps_claim.history)
    if history_len <= 0:
        return False
    denom = min(20, history_len)
    return (count / denom) < _BEAT_RATE_THRESHOLD


def _cash_runway_quarters(report: ResearchReport) -> float | None:
    """Quarters of runway = max(net_cash, 0) / |FCF TTM burn|.

    Returns ``None`` when:
    - FCF TTM is non-negative (cash-flow-positive — runway N/A)
    - FCF history has fewer than 4 quarters (can't compute TTM)
    - Cash or debt claim is missing
    """
    cash = _numeric_value(_find_claim(report, _DESC_CASH_PER_SHARE))
    debt = _numeric_value(_find_claim(report, _DESC_DEBT_PER_SHARE))
    fcf_claim = _find_claim(report, _DESC_FCF_PER_SHARE)

    if cash is None or debt is None or fcf_claim is None:
        return None
    if len(fcf_claim.history) < _RUNWAY_FCF_TTM_QUARTERS:
        return None

    last_4q = fcf_claim.history[-_RUNWAY_FCF_TTM_QUARTERS:]
    fcf_ttm = sum(point.value for point in last_4q)
    if fcf_ttm >= 0:
        return None

    burn = abs(fcf_ttm)
    net_cash = cash - debt
    if net_cash <= 0:
        # Already in deficit AND burning — the runway is effectively zero.
        return 0.0
    return net_cash / burn


def _gross_margin_negative(report: ResearchReport) -> bool:
    gm = _numeric_value(_find_claim(report, _DESC_GROSS_MARGIN))
    return gm is not None and gm < 0


def _linear_slope(history: list[ClaimHistoryPoint]) -> float | None:
    """Plain ordinary-least-squares slope with x = index, y = value.

    Returns ``None`` when history has fewer than ``_SLOPE_MIN_POINTS``
    points OR when the regression denominator is zero (every x equal
    — only possible when n == 1 since indices are distinct, but guard
    explicitly for robustness).
    """
    n = len(history)
    if n < _SLOPE_MIN_POINTS:
        return None
    xs = list(range(n))
    ys = [p.value for p in history]
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys, strict=True))
    sum_xx = sum(x * x for x in xs)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None
    return (n * sum_xy - sum_x * sum_y) / denom


def _debt_rising_cash_falling(report: ResearchReport) -> bool:
    """True when debt slope > 0 AND cash slope < 0 over the same window."""
    cash_claim = _find_claim(report, _DESC_CASH_PER_SHARE)
    debt_claim = _find_claim(report, _DESC_DEBT_PER_SHARE)
    if cash_claim is None or debt_claim is None:
        return False
    cash_slope = _linear_slope(cash_claim.history)
    debt_slope = _linear_slope(debt_claim.history)
    if cash_slope is None or debt_slope is None:
        return False
    return debt_slope > 0 and cash_slope < 0


def derive_layout_signals(report: ResearchReport) -> LayoutSignals:
    """Compute the adaptive-layout flags from a ``ResearchReport``.

    Pure: doesn't mutate ``report``, doesn't read external state.
    Returns a fresh ``LayoutSignals`` instance with the derived flags.
    """
    return LayoutSignals(
        is_unprofitable_ttm=_is_unprofitable_ttm(report),
        beat_rate_below_30pct=_beat_rate_below_threshold(report),
        cash_runway_quarters=_cash_runway_quarters(report),
        gross_margin_negative=_gross_margin_negative(report),
        debt_rising_cash_falling=_debt_rising_cash_falling(report),
    )
