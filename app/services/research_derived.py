"""
Derived comparison claims — the "so what" inputs for the synthesis call.

ADR 0007. The data tools return levels ("operating margin 33.4%"). Prose
that interprets needs comparisons: change over time, gap to peers, one
metric against another. If the model computed those itself the numbers
would match no claim and fail the factuality rubric, so they are
computed here, deterministically, and added to each section as ordinary
claims sourced ``computed.analytics`` with the formula in
``Source.detail``.

Rules every function follows:

- **Emit only what is meaningful.** Missing inputs, too little history,
  or a zero/negative denominator → no claim (never a None-valued one).
- **State the basis.** TTM figures sum the last four quarters; a
  year-over-year change compares a quarter with the same quarter a year
  earlier (five points back) and names both periods.
- **Pure.** Inputs are the tools' ``dict[str, Claim]`` outputs; no I/O.
- **Respect the business model.** For banks, free cash flow, capex,
  gross margin and net debt describe the loan book and deposit funding,
  not the business, so those comparisons are skipped (JPM's "−42% FCF
  margin" read as distress in the first eval).
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.schemas.research import Claim, ClaimHistoryPoint, ClaimUnit, Source

DERIVED_TOOL = "computed.analytics"
QUARTERS_PER_YEAR = 4
# Sectors whose balance sheet is the product (see module docstring).
BALANCE_SHEET_SECTORS = frozenset({"banks"})

Claims = Mapping[str, Claim]


# ── Input helpers ────────────────────────────────────────────────────


def _claims(output: Any) -> Claims:
    return output if isinstance(output, Mapping) else {}


def _num(claims: Claims, key: str) -> float | None:
    claim = claims.get(key)
    if claim is None:
        return None
    v = claim.value
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def _is_balance_sheet_business(claims: Claims) -> bool:
    sector = claims.get("sector_tag")
    return sector is not None and sector.value in BALANCE_SHEET_SECTORS


def is_balance_sheet_business(fundamentals: Any) -> bool:
    """Whether ``fetch_fundamentals``' output tags a bank (see module docstring)."""
    return _is_balance_sheet_business(_claims(fundamentals))


def _history(claims: Claims, key: str) -> list[ClaimHistoryPoint]:
    claim = claims.get(key)
    return list(claim.history) if claim is not None else []


def _ttm(claims: Claims, key: str) -> float | None:
    """Sum of the last four quarterly points (trailing twelve months)."""
    points = _history(claims, key)
    if len(points) < QUARTERS_PER_YEAR:
        return None
    return sum(p.value for p in points[-QUARTERS_PER_YEAR:])


def _year_apart(claims: Claims, key: str) -> tuple[ClaimHistoryPoint, ClaimHistoryPoint] | None:
    """The latest point and the same quarter one year earlier."""
    points = _history(claims, key)
    if len(points) <= QUARTERS_PER_YEAR:
        return None
    return points[-QUARTERS_PER_YEAR - 1], points[-1]


def _fetched_at(*sources: Claims) -> datetime:
    """Newest fetch time among the inputs — when the derivation became true."""
    times = [c.source.fetched_at for claims in sources for c in claims.values()]
    return max(times) if times else datetime.now(UTC)


def _claim(
    description: str,
    value: float,
    unit: ClaimUnit,
    formula: str,
    *inputs: Claims,
) -> Claim:
    return Claim(
        description=description,
        value=value,
        unit=unit,
        source=Source(tool=DERIVED_TOOL, fetched_at=_fetched_at(*inputs), detail=formula),
    )


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """numerator / denominator, only over a positive denominator."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


# ── Quality ──────────────────────────────────────────────────────────

_MARGIN_LABELS = {"operating_margin": "Operating margin", "fcf_margin": "Free cash flow margin"}
_GROWTH_LABELS = {
    "revenue_per_share": "Revenue per share",
    "operating_income_per_share": "Operating income per share",
}


def quality_claims(fundamentals: Any) -> list[Claim]:
    f = _claims(fundamentals)
    out: list[Claim] = []

    bank = _is_balance_sheet_business(f)
    # Margin change vs the same quarter last year, in points.
    for key, label in _MARGIN_LABELS.items():
        pair = _year_apart(f, key)
        if pair and not (bank and key == "fcf_margin"):
            then, now = pair
            out.append(_claim(
                f"{label} change, {then.period} → {now.period}",
                now.value - then.value,
                "percentage_points",
                f"{key}[{now.period}] − {key}[{then.period}]",
                f,
            ))

    # Per-share growth vs the same quarter last year (positive base only).
    for key, label in _GROWTH_LABELS.items():
        pair = _year_apart(f, key)
        if pair and pair[0].value > 0:
            then, now = pair
            out.append(_claim(
                f"{label} growth, {then.period} → {now.period}",
                now.value / then.value - 1,
                "fraction",
                f"{key}[{now.period}] / {key}[{then.period}] − 1",
                f,
            ))

    if bank:
        return out

    fcf_margin_ttm = _ratio(_ttm(f, "fcf_per_share"), _ttm(f, "revenue_per_share"))
    if fcf_margin_ttm is not None:
        out.append(_claim(
            "Free cash flow margin (trailing 4 quarters)",
            fcf_margin_ttm,
            "fraction",
            "Σ4Q fcf_per_share / Σ4Q revenue_per_share",
            f,
        ))
        conversion = _ratio(fcf_margin_ttm, _num(f, "profit_margin"))
        if conversion is not None:
            out.append(_claim(
                "Free cash flow ÷ net income (trailing 12 months)",
                conversion,
                "ratio",
                "TTM FCF margin / info.profitMargins",
                f,
            ))

    debt, cash = _num(f, "total_debt_per_share"), _num(f, "cash_and_st_investments_per_share")
    if debt is not None and cash is not None:
        net_debt = debt - cash
        out.append(_claim(
            "Net debt per share (debt minus cash; negative = net cash)",
            net_debt,
            "usd_per_share",
            "total_debt_per_share − cash_and_st_investments_per_share (latest quarter)",
            f,
        ))
        if net_debt > 0:
            years = _ratio(net_debt, _ttm(f, "ocf_per_share"))
            if years is not None:
                out.append(_claim(
                    "Net debt ÷ trailing-12-month operating cash flow (years to repay)",
                    years,
                    "ratio",
                    "net debt per share / Σ4Q ocf_per_share",
                    f,
                ))
    return out


# ── Capital allocation ───────────────────────────────────────────────


def capital_allocation_claims(fundamentals: Any) -> list[Claim]:
    f = _claims(fundamentals)
    out: list[Claim] = []
    # yfinance's dividendYield is percent-form (2.9 = 2.9%); work in fractions.
    dividend_yield_pct = _num(f, "dividend_yield")
    dividend_yield = dividend_yield_pct / 100 if dividend_yield_pct else None
    trailing_pe = _num(f, "trailing_pe")

    if dividend_yield and trailing_pe and trailing_pe > 0:
        out.append(_claim(
            "Dividend payout ratio (forward dividend ÷ trailing earnings)",
            dividend_yield * trailing_pe,
            "fraction",
            "info.dividendYield/100 × info.trailingPE",
            f,
        ))

    buyback_yield = _num(f, "buyback_yield")
    if dividend_yield is not None and buyback_yield is not None:
        out.append(_claim(
            "Shareholder yield (forward dividend + latest-year buybacks)",
            dividend_yield + buyback_yield,
            "fraction",
            "info.dividendYield/100 + buyback_yield",
            f,
        ))

    if _is_balance_sheet_business(f):
        return out

    fcf_margin_ttm = _ratio(_ttm(f, "fcf_per_share"), _ttm(f, "revenue_per_share"))
    fcf_yield = _ratio(fcf_margin_ttm, _num(f, "p_s"))
    if fcf_yield is not None:
        out.append(_claim(
            "Free cash flow yield (trailing 12 months)",
            fcf_yield,
            "fraction",
            "TTM FCF margin / price-to-sales (= TTM FCF / market cap)",
            f,
        ))
        if dividend_yield and fcf_yield > 0:
            out.append(_claim(
                "Free cash flow ÷ dividends paid (coverage)",
                fcf_yield / dividend_yield,
                "ratio",
                "TTM FCF yield / forward dividend yield",
                f,
            ))

    capex_ttm = _ttm(f, "capex_per_share")
    capex_intensity = _ratio(capex_ttm, _ttm(f, "revenue_per_share"))
    if capex_intensity is not None:
        out.append(_claim(
            "Capex as % of revenue (trailing 12 months)",
            capex_intensity,
            "fraction",
            "Σ4Q capex_per_share / Σ4Q revenue_per_share",
            f,
        ))
    capex_of_ocf = _ratio(capex_ttm, _ttm(f, "ocf_per_share"))
    if capex_of_ocf is not None:
        out.append(_claim(
            "Capex as % of operating cash flow (trailing 12 months)",
            capex_of_ocf,
            "fraction",
            "Σ4Q capex_per_share / Σ4Q ocf_per_share",
            f,
        ))
    pair = _year_apart(f, "capex_per_share")
    if pair and pair[0].value > 0:
        then, now = pair
        out.append(_claim(
            f"Capex per share growth, {then.period} → {now.period}",
            now.value / then.value - 1,
            "fraction",
            f"capex_per_share[{now.period}] / capex_per_share[{then.period}] − 1",
            f,
        ))
    sbc_of_fcf = _ratio(_ttm(f, "sbc_per_share"), _ttm(f, "fcf_per_share"))
    if sbc_of_fcf is not None:
        out.append(_claim(
            "Stock-based compensation as % of free cash flow (trailing 12 months)",
            sbc_of_fcf,
            "fraction",
            "Σ4Q sbc_per_share / Σ4Q fcf_per_share",
            f,
        ))
    return out


# ── Valuation ────────────────────────────────────────────────────────

_PEER_MULTIPLES = {
    "trailing_pe": "Trailing P/E",
    "p_s": "Price-to-sales",
    "ev_ebitda": "EV/EBITDA",
}


def valuation_claims(fundamentals: Any, peers: Any = None) -> list[Claim]:
    f, p = _claims(fundamentals), _claims(peers)
    out: list[Claim] = []

    for key, label in _PEER_MULTIPLES.items():
        own, median = _num(f, key), _num(p, f"median.{key}")
        if own and own > 0 and median and median > 0:
            out.append(_claim(
                f"{label} vs peer median of {median:.2f}: premium (+) or discount (−)",
                own / median - 1,
                "fraction",
                f"{key} / median.{key} − 1",
                f,
                p,
            ))

    own_gm, median_gm = _num(f, "gross_margin"), _num(p, "median.gross_margin")
    if own_gm is not None and median_gm is not None and not _is_balance_sheet_business(f):
        out.append(_claim(
            f"Gross margin vs peer median of {median_gm * 100:.2f}%",
            own_gm - median_gm,
            "percentage_points",
            "gross_margin − median.gross_margin",
            f,
            p,
        ))

    trailing, forward = _num(f, "trailing_pe"), _num(f, "forward_pe")
    if trailing and forward and trailing > 0 and forward > 0:
        out.append(_claim(
            "Earnings growth implied by forward vs trailing P/E",
            trailing / forward - 1,
            "fraction",
            "trailing_pe / forward_pe − 1 (= forward EPS / trailing EPS − 1)",
            f,
        ))
    return out


# ── Earnings ─────────────────────────────────────────────────────────


def earnings_claims(earnings: Any) -> list[Claim]:
    e = _claims(earnings)
    out: list[Claim] = []
    eps = _history(e, "eps_actual")

    if len(eps) >= 2 * QUARTERS_PER_YEAR:
        recent = sum(p.value for p in eps[-QUARTERS_PER_YEAR:])
        prior = sum(p.value for p in eps[-2 * QUARTERS_PER_YEAR : -QUARTERS_PER_YEAR])
        if prior > 0:
            out.append(_claim(
                "EPS growth, last 4 quarters vs the 4 before",
                recent / prior - 1,
                "fraction",
                "Σ eps_actual[−4:] / Σ eps_actual[−8:−4] − 1",
                e,
            ))

    pair = _year_apart(e, "eps_actual")
    if pair and pair[0].value > 0:
        then, now = pair
        out.append(_claim(
            f"EPS growth, {then.period} → {now.period}",
            now.value / then.value - 1,
            "fraction",
            f"eps_actual[{now.period}] / eps_actual[{then.period}] − 1",
            e,
        ))

    surprises = _history(e, "eps_surprise_pct")
    if surprises:
        streak = 0
        for point in reversed(surprises):
            if point.value <= 0:
                break
            streak += 1
        out.append(_claim(
            "Consecutive quarters beating consensus (latest backwards)",
            streak,
            "count",
            "count of trailing eps_surprise_pct > 0",
            e,
        ))

    # Latest surprise against the long-run average, so "above/below its
    # usual beat" is a claim rather than the model's comparison (it once
    # called 5.78% "below" a 4.41% average). Surprises are percent-form.
    latest, average = _num(e, "eps_surprise_pct"), _num(e, "last_20q.avg_surprise_pct")
    if latest is not None and average is not None:
        out.append(_claim(
            "Latest EPS surprise minus the 20-quarter average surprise",
            (latest - average) / 100,
            "percentage_points",
            "eps_surprise_pct − last_20q.avg_surprise_pct",
            e,
        ))
    return out


# ── Long-term growth (SEC annual history, 2026-11) ───────────────────

_ANNUAL_LABELS = {
    "revenue_per_share_annual": "Revenue per share",
    "operating_income_per_share_annual": "Operating income per share",
    "fcf_per_share_annual": "Free cash flow per share",
    "eps_diluted_annual": "Diluted EPS",
}
# Fewer annual points than this is too short a span to call a trend.
MIN_ANNUAL_POINTS = 5


def long_term_growth_claims(annual: Any, fundamentals: Any) -> list[Claim]:
    """Compound annual growth of each annual per-share series between its
    first and last named years ("Revenue per share, compound annual
    growth, 2015 → 2025"). Only over positive endpoints and at least
    ``MIN_ANNUAL_POINTS`` years; banks skip free cash flow."""
    a = _claims(annual)
    bank = _is_balance_sheet_business(_claims(fundamentals))
    out: list[Claim] = []
    for key, label in _ANNUAL_LABELS.items():
        if bank and key == "fcf_per_share_annual":
            continue
        points = _history(a, key)
        if len(points) < MIN_ANNUAL_POINTS:
            continue
        first, last = points[0], points[-1]
        years = int(last.period) - int(first.period)
        if years <= 0 or first.value <= 0 or last.value <= 0:
            continue
        out.append(_claim(
            f"{label}, compound annual growth, {first.period} → {last.period}",
            (last.value / first.value) ** (1 / years) - 1,
            "fraction",
            f"({key}[{last.period}] ÷ {key}[{first.period}])^(1/{years}) − 1",
            a,
        ))
    return out
