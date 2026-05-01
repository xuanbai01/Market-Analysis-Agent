"""
Quarterly history fan-out for the fundamentals tool (Phase 3.2.A).

Pure helper: takes yfinance's ``quarterly_financials`` and
``quarterly_cashflow`` DataFrames, returns
``dict[str, list[ClaimHistoryPoint]]`` keyed by the same claim keys
``app.services.fundamentals`` exposes — but only those that are
history-bearing in this PR.

Returned histories are ordered **oldest → newest**. yfinance returns
columns most-recent-first; we reverse for chart-rendering convenience
(a sparkline reading left-to-right shows time flowing forward).

## Defensive math

Free-data sources are messy. Each metric's history independently
collapses to ``[]`` rather than partially populating with bad values:

- ``None`` / empty DataFrame → all histories empty.
- Missing row label → that metric's history empty.
- NaN in numerator or denominator for a single quarter → drop that
  quarter only; other quarters still populate.
- Denominator == 0 → drop that quarter (no divide-by-zero into cache).
- Misaligned indexes (e.g. ``quarterly_financials`` covers Q1–Q4 but
  ``quarterly_cashflow`` only has Q3–Q4) → cross-frame metrics use the
  intersection; same-frame metrics use the full coverage.

## Why per-share denominator is "Diluted Average Shares"

``info["sharesOutstanding"]`` is a single point-in-time value and
applying it to historical quarters silently lies for any company that
buys back or issues stock between then and now. The
``Diluted Average Shares`` row in ``quarterly_financials`` gives the
weighted-average diluted share count *for that quarter*, matching the
Diluted EPS convention. When the row is missing for a symbol, all
per-share metrics for that symbol degrade to ``[]`` rather than
producing wrong numbers from a wrong denominator.

## Why FCF reads the yfinance row, not OCF − CapEx

``quarterly_cashflow.loc["Free Cash Flow"]`` is computed by yfinance
already. Re-deriving it as ``OCF - |CapEx|`` requires us to track
yfinance's CapEx-sign convention (positive vs negative), which has
drifted between releases. Reading their computed row sidesteps that.
"""
from __future__ import annotations

from typing import Any

from app.schemas.research import ClaimHistoryPoint

# Phase 3.2.D — flat US corporate tax rate used for NOPAT computation.
# Per-quarter Tax Provision / Pretax Income gives nonsense in loss /
# credit quarters (negative effective rate, NaN, etc.); a flat rate is
# simpler, chart-readable, and an industry-standard analyst shortcut.
# When/if international names land, swap for info["effectiveTaxRate"]
# with this as a fallback.
DEFAULT_TAX_RATE: float = 0.21


# Claim keys this helper produces history for. Spans Phase 3.2.A
# (per-share growth + margins), 3.2.B+C (cash flow components +
# balance sheet trend), and 3.2.D (ROE + ROIC TTM).
HISTORY_KEYS: tuple[str, ...] = (
    # 3.2.A — per-share growth
    "revenue_per_share",
    "gross_profit_per_share",
    "operating_income_per_share",
    "fcf_per_share",
    "ocf_per_share",
    # 3.2.A — margin trends (incl. existing claims that gained history)
    "operating_margin",
    "fcf_margin",
    "gross_margin",
    "profit_margin",
    # 3.2.B — cash flow components (joins Capital Allocation section)
    "capex_per_share",
    "sbc_per_share",
    # 3.2.C — balance sheet trend (joins Quality section)
    "cash_and_st_investments_per_share",
    "total_debt_per_share",
    "total_assets_per_share",
    "total_liabilities_per_share",
    # Phase 3.2.D — TTM capital efficiency. ``roe`` extends the existing
    # info-derived snapshot with quarterly history; ``roic`` is a new
    # claim with no info source (snapshot = history[-1]).
    "roe",
    "roic",
)


def format_period(timestamp: Any) -> str:
    """Render a ``pd.Timestamp`` as ``YYYY-QN``.

    Quarter is computed from the calendar month of the timestamp,
    not the fiscal calendar — different symbols have different fiscal
    years (NVDA's Q1 ends in April), and we keep the renderer
    consistent across symbols by using calendar quarters everywhere.
    """
    quarter = (timestamp.month - 1) // 3 + 1
    return f"{timestamp.year}-Q{quarter}"


def _row_or_none(df: Any, label: str) -> Any:
    """Pull a row by label as a Series, or ``None`` on any miss.

    yfinance's row labels drift across versions and symbols (e.g.
    ``"Capital Expenditure"`` vs ``"CapitalExpenditure"``); a missing
    row is "data unavailable" — we never raise.
    """
    if df is None:
        return None
    if getattr(df, "empty", True):
        return None
    if label not in df.index:
        return None
    return df.loc[label]


def _series_to_history(series: Any) -> list[ClaimHistoryPoint]:
    """Build a history list from a Series indexed by Timestamp.

    yfinance returns columns most-recent-first. We iterate in that
    order, then reverse for the oldest→newest chart-rendering
    convention. NaN values are dropped; the resulting list may be
    shorter than the input series length.
    """
    import pandas as pd  # noqa: PLC0415 — heavy import, lazy

    points: list[ClaimHistoryPoint] = []
    for col, val in series.items():
        if pd.isna(val):
            continue
        try:
            numeric = float(val)
        except (TypeError, ValueError):
            continue
        points.append(
            ClaimHistoryPoint(period=format_period(col), value=numeric)
        )
    points.reverse()  # newest-first → oldest-first
    return points


def _ratio_history(numerator: Any, denominator: Any) -> list[ClaimHistoryPoint]:
    """Build a per-quarter ratio history from two Series.

    Drops a quarter when:
    - the quarter isn't in both series (intersection only)
    - either side is NaN
    - the denominator is exactly 0 (avoids divide-by-zero into cache)

    Returned oldest→newest.
    """
    if numerator is None or denominator is None:
        return []
    import pandas as pd  # noqa: PLC0415

    common = numerator.index.intersection(denominator.index)
    points: list[ClaimHistoryPoint] = []
    for col in common:
        n = numerator[col]
        d = denominator[col]
        if pd.isna(n) or pd.isna(d):
            continue
        try:
            n_f = float(n)
            d_f = float(d)
        except (TypeError, ValueError):
            continue
        if d_f == 0.0:
            continue
        points.append(
            ClaimHistoryPoint(period=format_period(col), value=n_f / d_f)
        )
    # ``intersection`` doesn't guarantee order; sort by Timestamp so
    # the resulting list is oldest-first regardless of yfinance's
    # column ordering quirks.
    points.sort(key=lambda p: p.period)
    return points


def _ttm_sum(series: Any) -> Any:
    """Trailing-12-month rolling sum over a quarterly Series.

    yfinance returns columns most-recent-first; we sort ascending before
    rolling so the window goes oldest -> newest. The first 3 quarters
    have no full 4-quarter window and emit NaN; ``_ratio_history``
    drops those when building the chartable list. ``min_periods=4``
    enforces the strict-window semantics (no partial-window sums).

    A single NaN within a window propagates to the window's TTM (also
    NaN), so a missing-quarter point invalidates the 4 windows that
    would have included it. This is correct — a fabricated TTM with
    one missing input would lie about the trend.
    """
    if series is None:
        return None

    sorted_series = series.sort_index()
    return sorted_series.rolling(window=4, min_periods=4).sum()


def _nopat_series(operating_income: Any, tax_rate: float = DEFAULT_TAX_RATE) -> Any:
    """Net Operating Profit After Tax = Op Income × (1 − tax rate).

    Flat tax rate (default 21%) over per-quarter Tax Provision /
    Pretax Income — see ``DEFAULT_TAX_RATE`` for the rationale.
    """
    if operating_income is None:
        return None
    return operating_income * (1.0 - tax_rate)


def build_fundamentals_history(
    quarterly_financials: Any,
    quarterly_cashflow: Any,
    quarterly_balance_sheet: Any = None,
) -> dict[str, list[ClaimHistoryPoint]]:
    """Compute all Phase 3.2 histories from yfinance's quarterly frames.

    The ``quarterly_balance_sheet`` parameter is optional (defaults to
    None) so callers from before Phase 3.2.C work unchanged — they just
    get the four balance-sheet histories empty.

    Always returns a dict with every key in ``HISTORY_KEYS``; missing-
    data metrics get ``[]``. The caller's iteration is constant-shape
    regardless of how complete the upstream frames are.
    """
    out: dict[str, list[ClaimHistoryPoint]] = {k: [] for k in HISTORY_KEYS}

    revenue = _row_or_none(quarterly_financials, "Total Revenue")
    gross_profit = _row_or_none(quarterly_financials, "Gross Profit")
    operating_income = _row_or_none(quarterly_financials, "Operating Income")
    net_income = _row_or_none(quarterly_financials, "Net Income")
    diluted_shares = _row_or_none(
        quarterly_financials, "Diluted Average Shares"
    )

    operating_cash_flow = _row_or_none(
        quarterly_cashflow, "Operating Cash Flow"
    )
    free_cash_flow = _row_or_none(quarterly_cashflow, "Free Cash Flow")
    capex = _row_or_none(quarterly_cashflow, "Capital Expenditure")
    sbc = _row_or_none(quarterly_cashflow, "Stock Based Compensation")

    cash_and_st_inv = _row_or_none(
        quarterly_balance_sheet,
        "Cash Cash Equivalents And Short Term Investments",
    )
    total_debt = _row_or_none(quarterly_balance_sheet, "Total Debt")
    total_assets = _row_or_none(quarterly_balance_sheet, "Total Assets")
    total_liabilities = _row_or_none(
        quarterly_balance_sheet, "Total Liabilities Net Minority Interest"
    )
    stockholders_equity = _row_or_none(
        quarterly_balance_sheet, "Stockholders Equity"
    )
    invested_capital = _row_or_none(
        quarterly_balance_sheet, "Invested Capital"
    )

    # Per-share metrics — all need diluted_shares as denominator.
    if diluted_shares is not None:
        out["revenue_per_share"] = _ratio_history(revenue, diluted_shares)
        out["gross_profit_per_share"] = _ratio_history(
            gross_profit, diluted_shares
        )
        out["operating_income_per_share"] = _ratio_history(
            operating_income, diluted_shares
        )
        out["ocf_per_share"] = _ratio_history(
            operating_cash_flow, diluted_shares
        )
        out["fcf_per_share"] = _ratio_history(free_cash_flow, diluted_shares)
        # Phase 3.2.B — cash flow components.
        # CapEx: yfinance reports as negative outflow; chart shows
        # magnitude, so abs() before the divide. Series.abs() is
        # element-wise; NaN stays NaN.
        if capex is not None:
            out["capex_per_share"] = _ratio_history(capex.abs(), diluted_shares)
        out["sbc_per_share"] = _ratio_history(sbc, diluted_shares)
        # Phase 3.2.C — balance sheet per-share metrics.
        out["cash_and_st_investments_per_share"] = _ratio_history(
            cash_and_st_inv, diluted_shares
        )
        out["total_debt_per_share"] = _ratio_history(total_debt, diluted_shares)
        out["total_assets_per_share"] = _ratio_history(
            total_assets, diluted_shares
        )
        out["total_liabilities_per_share"] = _ratio_history(
            total_liabilities, diluted_shares
        )

    # Margin metrics — same-frame divisions where possible. ``revenue``
    # comes from quarterly_financials; for cross-frame margins
    # (fcf_margin = FCF / Revenue) we cross frames intentionally.
    out["gross_margin"] = _ratio_history(gross_profit, revenue)
    out["operating_margin"] = _ratio_history(operating_income, revenue)
    out["profit_margin"] = _ratio_history(net_income, revenue)
    out["fcf_margin"] = _ratio_history(free_cash_flow, revenue)

    # Phase 3.2.D — TTM ROE + ROIC. Both need a 4-quarter window of
    # income-statement data plus a point-in-time balance-sheet
    # denominator. The first 3 quarters of input lose their TTM
    # numerator to the warm-up; ``_ratio_history`` drops those NaNs.
    if net_income is not None and stockholders_equity is not None:
        out["roe"] = _ratio_history(_ttm_sum(net_income), stockholders_equity)
    if operating_income is not None and invested_capital is not None:
        nopat = _nopat_series(operating_income)
        out["roic"] = _ratio_history(_ttm_sum(nopat), invested_capital)

    return out


def latest_value(history: list[ClaimHistoryPoint]) -> float | None:
    """Return ``history[-1].value`` or None for an empty history.

    Used by ``fetch_fundamentals`` to populate the point-in-time
    ``Claim.value`` for the new history-bearing claims — the latest
    quarter's value is the natural snapshot.
    """
    if not history:
        return None
    return history[-1].value
