"""
Fundamentals tool. Pulls a flat ``dict[str, Claim]`` of valuation,
quality, capital-allocation, and short-interest signals for one symbol
in a single round trip.

Shape contract: every key in ``CLAIM_KEYS`` is present in the response,
even when the upstream value is missing — the corresponding ``Claim``
just has ``value=None``. Stable shape lets the agent compose prompts
without per-symbol branching.

Provider model mirrors ``app.services.data_ingestion``: the registered
provider is a sync callable that returns ``dict[str, ClaimValue | None]``
of pre-computed values, and the async entry point handles the
event-loop offload + observability + Claim/Source stamping. Single-
provider per call: a failure propagates rather than fabricating
fundamentals from a fallback. The agent decides whether to retry or
degrade with the tools it has.

Deferred (intentionally out of scope for the first version):
- ROIC — needs invested-capital construction (debt + equity − cash) and
  NOPAT (operating income × (1 − tax)). Worth a follow-up tool when we
  also pull tax-rate data.
- Multi-year capital-allocation history — buyback / dividend / SBC over
  3-5 years. The synth call does fine with one-year point estimates;
  add the time-series only if eval scoring asks for it.
- Sector-relative versions (P/E vs sector median, etc.) — needs the
  peers tool. Layer on after ``fetch_peers`` lands.

Unit conventions: yfinance reports margins / yields as decimal
fractions (0.745 = 74.5% gross margin). We pass those through unchanged
— the synth layer formats. The one exception that matters is
``dividendYield``, which yfinance has historically inconsistently
reported as either a fraction (0.025) or a percentage (2.5); we still
pass through. Document the gotcha rather than guess at normalization.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, ClaimHistoryPoint, ClaimValue, Source
from app.services.fundamentals_history import (
    HISTORY_KEYS,
    build_fundamentals_history,
    latest_value,
)

# ── Stable claim contract ─────────────────────────────────────────────
# Order matters only for deterministic iteration in tests / logs; the
# agent reads by key, not position.
CLAIM_KEYS: tuple[str, ...] = (
    # Valuation
    "trailing_pe",
    "forward_pe",
    "p_s",
    "ev_ebitda",
    "peg",
    # Quality (legacy point-in-time)
    "roe",
    "gross_margin",
    "profit_margin",
    # Quality (Phase 3.2.A — per-share growth, history-bearing)
    "revenue_per_share",
    "gross_profit_per_share",
    "operating_income_per_share",
    "fcf_per_share",
    "ocf_per_share",
    # Quality (Phase 3.2.A — margin trends, history-bearing)
    "operating_margin",
    "fcf_margin",
    # Quality (Phase 3.2.C — balance sheet trend, history-bearing)
    "cash_and_st_investments_per_share",
    "total_debt_per_share",
    "total_assets_per_share",
    "total_liabilities_per_share",
    # Capital allocation + sentiment
    "dividend_yield",
    "short_ratio",
    "shares_short",
    "market_cap",
    "buyback_yield",
    "sbc_pct_revenue",
    # Capital allocation (Phase 3.2.B — cash flow components, history-bearing)
    "capex_per_share",
    "sbc_per_share",
    # Trend (legacy single-value YoY delta — kept alongside history)
    "gross_margin_trend_1y",
)

# Human-readable descriptions for the Claim itself. The agent's prompt
# may quote these verbatim so they should read like analyst column
# headers, not internal ids.
_DESCRIPTIONS: dict[str, str] = {
    "trailing_pe": "P/E ratio (trailing 12 months)",
    "forward_pe": "P/E ratio (forward, analyst consensus)",
    "p_s": "Price-to-sales ratio (trailing 12 months)",
    "ev_ebitda": "Enterprise value to EBITDA",
    "peg": "PEG ratio (P/E to growth, trailing)",
    "roe": "Return on equity",
    "gross_margin": "Gross margin",
    "profit_margin": "Net profit margin",
    "revenue_per_share": "Revenue per share",
    "gross_profit_per_share": "Gross profit per share",
    "operating_income_per_share": "Operating income per share",
    "fcf_per_share": "Free cash flow per share",
    "ocf_per_share": "Operating cash flow per share",
    "operating_margin": "Operating margin",
    "fcf_margin": "Free cash flow margin",
    "cash_and_st_investments_per_share": (
        "Cash + short-term investments per share"
    ),
    "total_debt_per_share": "Total debt per share",
    "total_assets_per_share": "Total assets per share",
    "total_liabilities_per_share": "Total liabilities per share",
    "capex_per_share": "Capital expenditure per share",
    "sbc_per_share": "Stock-based compensation per share",
    "dividend_yield": "Forward dividend yield",
    "short_ratio": "Short interest, days-to-cover",
    "shares_short": "Shares sold short",
    "market_cap": "Market capitalization",
    "buyback_yield": "Buyback yield (latest fiscal year)",
    "sbc_pct_revenue": "Stock-based compensation as % of revenue (latest fiscal year)",
    "gross_margin_trend_1y": "Gross margin, year-over-year change",
}

# Per-claim Source.detail. Format is intentionally human-readable —
# this string is rendered into the report as part of the citation, so
# "info.trailingPE" beats "tpe" and "computed: ..." beats a code path.
_DETAILS: dict[str, str] = {
    "trailing_pe": "info.trailingPE",
    "forward_pe": "info.forwardPE",
    "p_s": "info.priceToSalesTrailing12Months",
    "ev_ebitda": "info.enterpriseToEbitda",
    "peg": "info.trailingPegRatio",
    "roe": "info.returnOnEquity",
    "gross_margin": "info.grossMargins",
    "profit_margin": "info.profitMargins",
    "revenue_per_share": (
        "computed: quarterly_financials.TotalRevenue / DilutedAverageShares"
    ),
    "gross_profit_per_share": (
        "computed: quarterly_financials.GrossProfit / DilutedAverageShares"
    ),
    "operating_income_per_share": (
        "computed: quarterly_financials.OperatingIncome / DilutedAverageShares"
    ),
    "fcf_per_share": (
        "computed: quarterly_cashflow.FreeCashFlow / DilutedAverageShares"
    ),
    "ocf_per_share": (
        "computed: quarterly_cashflow.OperatingCashFlow / DilutedAverageShares"
    ),
    "operating_margin": (
        "computed: quarterly_financials.OperatingIncome / TotalRevenue"
    ),
    "fcf_margin": (
        "computed: quarterly_cashflow.FreeCashFlow / quarterly_financials.TotalRevenue"
    ),
    "cash_and_st_investments_per_share": (
        "computed: quarterly_balance_sheet.CashCashEquivalentsAndShortTermInvestments"
        " / DilutedAverageShares"
    ),
    "total_debt_per_share": (
        "computed: quarterly_balance_sheet.TotalDebt / DilutedAverageShares"
    ),
    "total_assets_per_share": (
        "computed: quarterly_balance_sheet.TotalAssets / DilutedAverageShares"
    ),
    "total_liabilities_per_share": (
        "computed: quarterly_balance_sheet.TotalLiabilitiesNetMinorityInterest"
        " / DilutedAverageShares"
    ),
    "capex_per_share": (
        "computed: |quarterly_cashflow.CapitalExpenditure| / DilutedAverageShares"
    ),
    "sbc_per_share": (
        "computed: quarterly_cashflow.StockBasedCompensation / DilutedAverageShares"
    ),
    "dividend_yield": "info.dividendYield",
    "short_ratio": "info.shortRatio",
    "shares_short": "info.sharesShort",
    "market_cap": "info.marketCap",
    "buyback_yield": "computed: |cashflow.RepurchaseOfCapitalStock| / info.marketCap",
    "sbc_pct_revenue": "computed: cashflow.StockBasedCompensation / financials.TotalRevenue",
    "gross_margin_trend_1y": (
        "computed: financials.GrossProfit/TotalRevenue, year-over-year delta"
    ),
}

# yfinance .info key for each info-derived claim. The remaining three
# claims are computed from financials/cashflow DataFrames below.
_INFO_KEYS: dict[str, str] = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "p_s": "priceToSalesTrailing12Months",
    "ev_ebitda": "enterpriseToEbitda",
    "peg": "trailingPegRatio",
    "roe": "returnOnEquity",
    "gross_margin": "grossMargins",
    "profit_margin": "profitMargins",
    "dividend_yield": "dividendYield",
    "short_ratio": "shortRatio",
    "shares_short": "sharesShort",
    "market_cap": "marketCap",
}


# Provider signature (Phase 3.2.A): (symbol) -> (values, history_map).
# - values: {claim_key: ClaimValue | None}, point-in-time snapshot.
# - history_map: {claim_key: list[ClaimHistoryPoint]}, sparkline data.
# Sync — yfinance is blocking; the async entry point hands it to
# ``to_thread``. The two-element shape lets one provider call produce
# both the snapshot and the history without duplicate yfinance fetches.
FundamentalsProvider = Callable[
    [str],
    tuple[
        dict[str, ClaimValue | None],
        dict[str, list[ClaimHistoryPoint]],
    ],
]


def _safe_loc(df: Any, row_label: str, col_idx: int = 0) -> float | None:
    """
    Defensive ``df.loc[row_label].iloc[col_idx]`` returning None on any
    miss: empty frame, missing row, out-of-range column, NaN, or a value
    that doesn't coerce to float. yfinance's row labels drift (a
    ``Repurchase Of Capital Stock`` may be missing for some symbols, may
    appear as ``RepurchaseOfCapitalStock`` for others); we treat any
    lookup failure as "data unavailable" rather than raising.
    """
    if df is None or getattr(df, "empty", True):
        return None
    try:
        val = df.loc[row_label].iloc[col_idx]
    except (KeyError, IndexError, AttributeError):
        return None
    # pandas isna handles NaN; import is cheap once, only when we have a frame.
    import pandas as pd  # noqa: PLC0415

    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fetch_yfinance_fundamentals(
    symbol: str,
) -> tuple[
    dict[str, ClaimValue | None], dict[str, list[ClaimHistoryPoint]]
]:
    """
    Pull ``.info``, ``.financials``, ``.cashflow``, ``.quarterly_financials``,
    ``.quarterly_cashflow`` from yfinance once, then read or compute every
    claim's point-in-time value AND its quarterly history (Phase 3.2.A).
    yfinance is imported lazily so the test suite can swap in a fake
    module without paying the pandas/numpy import cost.

    Returns ``(raw_values, history_map)``. The history map is computed
    via ``app.services.fundamentals_history.build_fundamentals_history``;
    point-in-time values for the new history-bearing claims are taken
    as ``history[-1].value`` (latest quarter) so the snapshot and the
    sparkline's last point always agree.
    """
    import yfinance  # noqa: PLC0415

    ticker = yfinance.Ticker(symbol)
    info: dict[str, Any] = getattr(ticker, "info", {}) or {}
    financials = getattr(ticker, "financials", None)
    cashflow = getattr(ticker, "cashflow", None)
    quarterly_financials = getattr(ticker, "quarterly_financials", None)
    quarterly_cashflow = getattr(ticker, "quarterly_cashflow", None)
    quarterly_balance_sheet = getattr(
        ticker, "quarterly_balance_sheet", None
    )

    # Build the history map first — its latest values feed the snapshot
    # for new claims, keeping snapshot and history[-1] consistent.
    history_map = build_fundamentals_history(
        quarterly_financials, quarterly_cashflow, quarterly_balance_sheet
    )

    raw: dict[str, ClaimValue | None] = {}

    # 1. .info passthroughs — yfinance returns the value, ``None``, or
    #    omits the key entirely. ``.get`` collapses the latter two.
    for claim_key, info_key in _INFO_KEYS.items():
        raw[claim_key] = info.get(info_key)

    # 2. Buyback yield. yfinance reports stock repurchases as a negative
    #    cash outflow; abs() so a 5% buyback reads as 0.05, not -0.05.
    market_cap = info.get("marketCap")
    repurchases = _safe_loc(cashflow, "Repurchase Of Capital Stock")
    if market_cap and repurchases is not None:
        raw["buyback_yield"] = abs(repurchases) / market_cap
    else:
        raw["buyback_yield"] = None

    # 3. SBC as % of revenue. Revenue from the income statement,
    #    SBC from the cashflow statement (where it lives canonically).
    revenue = _safe_loc(financials, "Total Revenue")
    sbc = _safe_loc(cashflow, "Stock Based Compensation")
    if revenue and sbc is not None:
        raw["sbc_pct_revenue"] = sbc / revenue
    else:
        raw["sbc_pct_revenue"] = None

    # 4. Gross margin YoY delta. Need two fiscal periods. yfinance
    #    indexes columns most-recent-first (col 0 = latest).
    rev_now = _safe_loc(financials, "Total Revenue", 0)
    gp_now = _safe_loc(financials, "Gross Profit", 0)
    rev_prior = _safe_loc(financials, "Total Revenue", 1)
    gp_prior = _safe_loc(financials, "Gross Profit", 1)
    if rev_now and gp_now is not None and rev_prior and gp_prior is not None:
        raw["gross_margin_trend_1y"] = (gp_now / rev_now) - (gp_prior / rev_prior)
    else:
        raw["gross_margin_trend_1y"] = None

    # 5. Phase 3.2.A/B/C snapshot values for the new history-bearing
    #    claims. Snapshot = latest quarter (history[-1].value). For the
    #    two legacy claims that gained .history (gross_margin /
    #    profit_margin), we keep the .info-derived snapshot — it's the
    #    user-facing TTM figure. The sparkline shows quarterly drift
    #    around it.
    for key in (
        # 3.2.A
        "revenue_per_share",
        "gross_profit_per_share",
        "operating_income_per_share",
        "fcf_per_share",
        "ocf_per_share",
        "operating_margin",
        "fcf_margin",
        # 3.2.B
        "capex_per_share",
        "sbc_per_share",
        # 3.2.C
        "cash_and_st_investments_per_share",
        "total_debt_per_share",
        "total_assets_per_share",
        "total_liabilities_per_share",
    ):
        raw[key] = latest_value(history_map.get(key, []))

    return raw, history_map


PROVIDERS: dict[str, FundamentalsProvider] = {
    "yfinance": _fetch_yfinance_fundamentals,
}


async def fetch_fundamentals(
    symbol: str,
    *,
    provider: str = "yfinance",
) -> dict[str, Claim]:
    """
    Fetch one symbol's fundamentals as ``dict[str, Claim]``.

    Each claim carries a fresh ``Source(tool="<provider>.fundamentals",
    fetched_at=now, detail=...)``. All claims share one ``fetched_at``
    because they came from a single provider call — that's the
    contract for ``Section.last_updated``.

    Single-provider per call: a failure propagates. The agent has other
    tools (peers, EDGAR, news) to lean on if fundamentals are
    unavailable for a symbol; silently swallowing the error here would
    only hide the gap.
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    service_id = f"{provider}.fundamentals"

    with log_external_call(
        service_id, {"symbol": target, "provider": provider}
    ) as call:
        raw, history_map = await asyncio.to_thread(fetch, target)
        non_null = sum(1 for k in CLAIM_KEYS if raw.get(k) is not None)
        history_count = sum(1 for k in HISTORY_KEYS if history_map.get(k))
        call.record_output(
            {
                "claim_count": len(CLAIM_KEYS),
                "non_null_count": non_null,
                # How many history-bearing claims actually got history
                # populated. Useful for spotting yfinance drift in
                # the observability stream.
                "history_populated_count": history_count,
            }
        )

    fetched_at = datetime.now(UTC)
    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_DESCRIPTIONS[key],
            value=raw.get(key),
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=_DETAILS[key],
            ),
            history=history_map.get(key, []),
        )
    return out
