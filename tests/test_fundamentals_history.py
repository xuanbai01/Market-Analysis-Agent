"""
Unit tests for ``app.services.fundamentals_history``.

The helper takes yfinance's ``quarterly_financials`` and
``quarterly_cashflow`` DataFrames and returns
``dict[str, list[ClaimHistoryPoint]]`` keyed by claim name. Pure
function — no yfinance, no I/O. Tests feed synthetic DataFrames and
assert on the resulting histories.

What we're pinning here:

1. **Period formatting.** ``pd.Timestamp(2024-12-31)`` -> ``"2024-Q4"``,
   not ``"2024-Q12"`` or ``"2024-12"``.
2. **Order.** yfinance returns columns most-recent-first; the helper
   reverses to oldest-first so a chart reads left-to-right naturally.
3. **Defensive math.** NaN rows / missing rows / zero denominators
   degrade to dropped points or empty histories, never raise.
4. **Cross-frame alignment.** When ``quarterly_financials`` and
   ``quarterly_cashflow`` cover slightly different quarters, only the
   intersection produces points for cross-frame metrics (e.g. FCF
   margin = FCF / revenue).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.schemas.research import ClaimHistoryPoint
from app.services.fundamentals_history import (
    _nopat_series,
    _ttm_sum,
    build_fundamentals_history,
    format_period,
)

# ── format_period ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ts,expected",
    [
        (pd.Timestamp("2024-03-31"), "2024-Q1"),
        (pd.Timestamp("2024-06-30"), "2024-Q2"),
        (pd.Timestamp("2024-09-30"), "2024-Q3"),
        (pd.Timestamp("2024-12-31"), "2024-Q4"),
        # NVDA's fiscal calendar (Jan/Apr/Jul/Oct quarter-ends) —
        # we treat the calendar quarter mechanically, not the
        # fiscal one. Keeps the renderer consistent across symbols.
        (pd.Timestamp("2025-01-31"), "2025-Q1"),
        (pd.Timestamp("2025-10-31"), "2025-Q4"),
    ],
)
def test_format_period_quarterly(ts: pd.Timestamp, expected: str) -> None:
    assert format_period(ts) == expected


# ── Fixtures ─────────────────────────────────────────────────────────


def _financials_4q() -> pd.DataFrame:
    """Realistic 4-quarter financials, newest-first per yfinance convention."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        # rows are line items; columns are periods (newest left)
        [
            [100.0, 90.0, 80.0, 70.0],   # Total Revenue
            [70.0, 60.0, 50.0, 45.0],    # Gross Profit
            [30.0, 25.0, 20.0, 18.0],    # Operating Income
            [10.0, 8.0, 6.0, 5.0],       # Net Income
            [1000.0, 1000.0, 1010.0, 1020.0],  # Diluted Average Shares
        ],
        index=[
            "Total Revenue",
            "Gross Profit",
            "Operating Income",
            "Net Income",
            "Diluted Average Shares",
        ],
        columns=cols,
    )


def _cashflow_4q() -> pd.DataFrame:
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [25.0, 22.0, 18.0, 15.0],   # Operating Cash Flow
            [-5.0, -4.0, -3.0, -2.0],   # Capital Expenditure (negative = outflow)
            [20.0, 18.0, 15.0, 13.0],   # Free Cash Flow (yfinance-computed)
        ],
        index=[
            "Operating Cash Flow",
            "Capital Expenditure",
            "Free Cash Flow",
        ],
        columns=cols,
    )


# ── Happy path ───────────────────────────────────────────────────────


def test_returns_all_advertised_keys_when_data_complete() -> None:
    """Every 3.2.A history-bearing claim key gets a populated history
    when the underlying frames cover all quarters. Keys outside the
    3.2.A set (3.2.B + 3.2.C metrics from later phases) are present in
    the output dict but populate empty here because their source rows
    aren't in the basic fixture.
    """
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    phase_3_2_a_keys = {
        "revenue_per_share",
        "gross_profit_per_share",
        "operating_income_per_share",
        "fcf_per_share",
        "ocf_per_share",
        "operating_margin",
        "fcf_margin",
        "gross_margin",
        "profit_margin",
    }
    # All 3.2.A keys present and populated.
    for key in phase_3_2_a_keys:
        assert key in out, f"{key} missing from output"
        assert len(out[key]) == 4, f"{key} should have 4 quarters"
    # The full key set is a superset (3.2.B + 3.2.C add more).
    assert phase_3_2_a_keys <= set(out.keys())


def test_revenue_per_share_math_and_order() -> None:
    """Revenue / Diluted Avg Shares per quarter; ordered oldest-first."""
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    rps = out["revenue_per_share"]
    # _financials_4q: revenue [100,90,80,70] over [Q4,Q3,Q2,Q1] (yfinance newest-first)
    # Diluted shares [1000,1000,1010,1020]. Output should be Q1->Q4.
    assert [p.period for p in rps] == ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]
    assert rps[0] == ClaimHistoryPoint(period="2024-Q1", value=70.0 / 1020.0)
    assert rps[-1] == ClaimHistoryPoint(period="2024-Q4", value=100.0 / 1000.0)


def test_margin_math() -> None:
    """gross_margin = gross_profit / revenue per quarter."""
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    gm = out["gross_margin"]
    # Q4: 70/100 = 0.70.  Q1: 45/70 ≈ 0.6429.
    assert gm[-1].value == pytest.approx(0.70)
    assert gm[0].value == pytest.approx(45.0 / 70.0)


def test_fcf_margin_uses_yfinance_free_cash_flow_row() -> None:
    """Free Cash Flow comes from the yfinance-computed row, not OCF - CapEx,
    so a future change in yfinance's CapEx-sign convention doesn't break us."""
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    fcfm = out["fcf_margin"]
    # Q4: 20/100 = 0.20
    assert fcfm[-1] == ClaimHistoryPoint(period="2024-Q4", value=0.20)


def test_history_ordered_oldest_to_newest() -> None:
    """Renderer convention: history[0] is oldest, history[-1] is current."""
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    for key, history in out.items():
        if not history:
            continue
        periods = [p.period for p in history]
        assert periods == sorted(periods), f"{key} not sorted oldest->newest"


# ── Defensive math ───────────────────────────────────────────────────


def test_none_dataframes_returns_all_empty_histories() -> None:
    out = build_fundamentals_history(None, None)
    for key, history in out.items():
        assert history == [], f"{key} should be empty when no data"


def test_empty_dataframes_returns_all_empty_histories() -> None:
    out = build_fundamentals_history(pd.DataFrame(), pd.DataFrame())
    for history in out.values():
        assert history == []


def test_missing_diluted_shares_skips_per_share_metrics() -> None:
    """Without a per-quarter share count we can't fairly compute per-share
    history. Margin metrics that don't need shares still populate."""
    fin = _financials_4q().drop(index="Diluted Average Shares")

    out = build_fundamentals_history(fin, _cashflow_4q())

    assert out["revenue_per_share"] == []
    assert out["gross_profit_per_share"] == []
    assert out["operating_income_per_share"] == []
    assert out["fcf_per_share"] == []
    assert out["ocf_per_share"] == []
    # Margins are share-independent and should still populate.
    assert len(out["gross_margin"]) == 4
    assert len(out["operating_margin"]) == 4


def test_nan_in_numerator_drops_that_quarter() -> None:
    """A single NaN doesn't kill the whole history — just that point."""
    fin = _financials_4q()
    fin.loc["Total Revenue", pd.Timestamp("2024-09-30")] = float("nan")

    out = build_fundamentals_history(fin, _cashflow_4q())

    rps = out["revenue_per_share"]
    # Q3 dropped; Q1, Q2, Q4 remain.
    assert [p.period for p in rps] == ["2024-Q1", "2024-Q2", "2024-Q4"]


def test_zero_denominator_drops_that_quarter() -> None:
    """A zero-revenue quarter (early-stage company) shouldn't divide-by-zero."""
    fin = _financials_4q()
    fin.loc["Total Revenue", pd.Timestamp("2024-03-31")] = 0.0

    out = build_fundamentals_history(fin, _cashflow_4q())

    gm = out["gross_margin"]
    # Q1 dropped due to zero denominator; Q2-Q4 remain.
    assert [p.period for p in gm] == ["2024-Q2", "2024-Q3", "2024-Q4"]


def test_misaligned_columns_uses_intersection() -> None:
    """If quarterly_cashflow covers different quarters than quarterly_financials,
    cross-frame metrics (fcf_margin) only populate for the intersection.
    Same-frame metrics (gross_margin from financials only) cover all
    available quarters in their frame."""
    fin = _financials_4q()  # Q1-Q4 2024
    # Cashflow only has Q3 + Q4 2024.
    cf_cols = [pd.Timestamp("2024-12-31"), pd.Timestamp("2024-09-30")]
    cf = pd.DataFrame(
        [
            [25.0, 22.0],
            [-5.0, -4.0],
            [20.0, 18.0],
        ],
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
        columns=cf_cols,
    )

    out = build_fundamentals_history(fin, cf)

    # gross_margin uses financials only -> 4 points
    assert len(out["gross_margin"]) == 4
    # fcf_margin needs both -> 2 points (intersection)
    assert [p.period for p in out["fcf_margin"]] == ["2024-Q3", "2024-Q4"]


def test_missing_row_labels_yield_empty_history_for_that_metric() -> None:
    """Drop the Gross Profit row -> gross_margin + gross_profit_per_share empty.
    Other metrics with intact rows still populate."""
    fin = _financials_4q().drop(index="Gross Profit")

    out = build_fundamentals_history(fin, _cashflow_4q())

    assert out["gross_margin"] == []
    assert out["gross_profit_per_share"] == []
    # Unrelated metrics still populate.
    assert len(out["revenue_per_share"]) == 4
    assert len(out["operating_margin"]) == 4


# ── Phase 3.2.B+C: cash flow components + balance sheet trend ────────


def _cashflow_4q_with_components() -> pd.DataFrame:
    """Cashflow including SBC + CapEx for the components stack."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [25.0, 22.0, 18.0, 15.0],     # Operating Cash Flow
            [-5.0, -4.0, -3.0, -2.0],     # Capital Expenditure (negative)
            [20.0, 18.0, 15.0, 13.0],     # Free Cash Flow
            [4.0, 3.5, 3.0, 2.5],         # Stock Based Compensation (positive)
        ],
        index=[
            "Operating Cash Flow",
            "Capital Expenditure",
            "Free Cash Flow",
            "Stock Based Compensation",
        ],
        columns=cols,
    )


def _balance_sheet_4q() -> pd.DataFrame:
    """Synthetic balance sheet with the rows Phase 3.2.C consumes."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [800.0, 750.0, 700.0, 650.0],  # Cash + ST Inv
            [200.0, 220.0, 240.0, 250.0],  # Total Debt
            [3000.0, 2800.0, 2600.0, 2400.0],  # Total Assets
            [1200.0, 1150.0, 1100.0, 1050.0],  # Total Liabilities Net Minority Interest
        ],
        index=[
            "Cash Cash Equivalents And Short Term Investments",
            "Total Debt",
            "Total Assets",
            "Total Liabilities Net Minority Interest",
        ],
        columns=cols,
    )


def test_three_frame_signature_returns_six_more_keys() -> None:
    """Phase 3.2.B+C: build_fundamentals_history accepts a third
    quarterly_balance_sheet param and returns 6 additional history keys
    on top of the 9 from 3.2.A."""
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), _balance_sheet_4q()
    )

    new_keys = {
        # 3.2.B — cash flow components
        "capex_per_share",
        "sbc_per_share",
        # 3.2.C — balance sheet trend
        "cash_and_st_investments_per_share",
        "total_debt_per_share",
        "total_assets_per_share",
        "total_liabilities_per_share",
    }
    assert new_keys <= set(out.keys())
    for key in new_keys:
        assert len(out[key]) == 4, f"{key} should have 4 quarters"


def test_capex_per_share_is_absolute_value() -> None:
    """yfinance reports Capital Expenditure as a negative cash outflow.
    For the cash-flow-components stacked bar, the chart shows magnitude;
    feeding it negative numbers would render below the axis. Take abs()."""
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), _balance_sheet_4q()
    )

    capex = out["capex_per_share"]
    # Q4: |-5| / 1000 = 0.005
    assert capex[-1] == ClaimHistoryPoint(period="2024-Q4", value=0.005)
    # All values should be non-negative regardless of sign in the source.
    assert all(p.value >= 0 for p in capex)


def test_sbc_per_share_passes_signed_value_through() -> None:
    """SBC is reported as positive in yfinance (non-cash addback).
    No abs() needed; it's already in the right sign for the chart."""
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), _balance_sheet_4q()
    )

    sbc = out["sbc_per_share"]
    assert sbc[-1] == ClaimHistoryPoint(period="2024-Q4", value=4.0 / 1000.0)


def test_balance_sheet_per_share_metrics() -> None:
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), _balance_sheet_4q()
    )

    cash = out["cash_and_st_investments_per_share"]
    debt = out["total_debt_per_share"]
    assets = out["total_assets_per_share"]
    liab = out["total_liabilities_per_share"]

    # Q4 2024: Diluted Avg Shares = 1000.
    assert cash[-1] == ClaimHistoryPoint(period="2024-Q4", value=800.0 / 1000.0)
    assert debt[-1] == ClaimHistoryPoint(period="2024-Q4", value=200.0 / 1000.0)
    assert assets[-1] == ClaimHistoryPoint(period="2024-Q4", value=3000.0 / 1000.0)
    assert liab[-1] == ClaimHistoryPoint(period="2024-Q4", value=1200.0 / 1000.0)


def test_balance_sheet_history_oldest_first() -> None:
    """Same convention as the rest: history[0] is oldest, history[-1] newest."""
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), _balance_sheet_4q()
    )

    debt = out["total_debt_per_share"]
    assert [p.period for p in debt] == [
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
    ]


def test_missing_balance_sheet_yields_empty_bs_histories() -> None:
    """No balance sheet -> all BS-trend keys empty. Other histories still
    populate from financials + cashflow."""
    out = build_fundamentals_history(
        _financials_4q(), _cashflow_4q_with_components(), None
    )

    assert out["cash_and_st_investments_per_share"] == []
    assert out["total_debt_per_share"] == []
    assert out["total_assets_per_share"] == []
    assert out["total_liabilities_per_share"] == []
    # Non-BS histories should still populate.
    assert len(out["revenue_per_share"]) == 4
    assert len(out["capex_per_share"]) == 4
    assert len(out["sbc_per_share"]) == 4


def test_balance_sheet_param_optional_for_backwards_compat() -> None:
    """Calling build_fundamentals_history with the old 2-arg signature
    must still work — produces the original 9 history keys, plus the
    6 new ones empty."""
    out = build_fundamentals_history(_financials_4q(), _cashflow_4q())

    # 3.2.A keys still populate.
    assert len(out["revenue_per_share"]) == 4
    assert len(out["gross_margin"]) == 4
    # 3.2.B + 3.2.C keys present in the dict but empty (no BS, no SBC row
    # in the basic cashflow fixture).
    assert "capex_per_share" in out
    assert "cash_and_st_investments_per_share" in out
    assert out["cash_and_st_investments_per_share"] == []


def test_balance_sheet_misalignment_with_financials_uses_intersection() -> None:
    """quarterly_balance_sheet may cover slightly different quarters than
    quarterly_financials (e.g. fiscal-year-end timing). _ratio_history's
    intersection logic handles it; the shorter coverage shows up in the
    history list length."""
    fin = _financials_4q()  # Q1-Q4 2024
    # Balance sheet only has Q3 + Q4 2024.
    bs_cols = [pd.Timestamp("2024-12-31"), pd.Timestamp("2024-09-30")]
    bs = pd.DataFrame(
        [
            [800.0, 750.0],
            [200.0, 220.0],
            [3000.0, 2800.0],
            [1200.0, 1150.0],
        ],
        index=[
            "Cash Cash Equivalents And Short Term Investments",
            "Total Debt",
            "Total Assets",
            "Total Liabilities Net Minority Interest",
        ],
        columns=bs_cols,
    )

    out = build_fundamentals_history(fin, _cashflow_4q_with_components(), bs)

    # BS metrics should only have 2 points (intersection with shares).
    assert [p.period for p in out["total_debt_per_share"]] == [
        "2024-Q3",
        "2024-Q4",
    ]
    # Non-BS metrics still populate fully.
    assert len(out["revenue_per_share"]) == 4


# ── Phase 3.2.D: TTM helpers + ROE/ROIC histories ────────────────────


def _quarterly_with_eq_and_ic_8q() -> tuple[pd.DataFrame, pd.DataFrame]:
    """8 quarters of synthetic financials + balance sheet — enough for
    TTM math (which loses 3 quarters to the rolling-window warm-up)."""
    cols = [
        # newest -> oldest
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2023-09-30"),
        pd.Timestamp("2023-06-30"),
        pd.Timestamp("2023-03-31"),
    ]
    fin = pd.DataFrame(
        [
            # Revenue, GP, Op Inc, NI, Diluted Avg Shares
            [100, 90, 80, 70, 60, 55, 50, 45],
            [70, 60, 50, 45, 40, 36, 32, 28],
            [30, 25, 20, 18, 15, 13, 12, 10],
            [10, 8, 6, 5, 4, 3, 3, 2],
            [1000, 1000, 1010, 1020, 1030, 1040, 1050, 1060],
        ],
        index=[
            "Total Revenue",
            "Gross Profit",
            "Operating Income",
            "Net Income",
            "Diluted Average Shares",
        ],
        columns=cols,
    )
    bs = pd.DataFrame(
        [
            # Stockholders Equity, Invested Capital
            [50.0, 48.0, 46.0, 44.0, 42.0, 40.0, 38.0, 36.0],
            [80.0, 78.0, 76.0, 74.0, 72.0, 70.0, 68.0, 66.0],
        ],
        index=["Stockholders Equity", "Invested Capital"],
        columns=cols,
    )
    return fin, bs


# ── _ttm_sum ─────────────────────────────────────────────────────────


def test_ttm_sum_rolling_4q() -> None:
    """TTM at quarter Q is the sum of Q + 3 prior quarters. The first 3
    quarters of the input have no full window and emit NaN (caller drops
    them via _ratio_history's NaN handling)."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-12-31"),
    ]
    # newest-first: 5, 4, 3, 2, 1
    s = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0], index=cols)

    ttm = _ttm_sum(s)

    # _ttm_sum returns oldest-first sorted, with NaN for warm-up.
    # Oldest 3 quarters lack a full 4Q window -> NaN.
    # Q4 2024 (newest): 1+2+3+4+5? No wait — 4Q window ending at Q4 2024
    # is {Q1, Q2, Q3, Q4 2024}. With sorted order [1, 2, 3, 4, 5] (Q4-2023 first),
    # rolling window 4 would be NaN at Q4-2023, Q1, Q2, Q3 of 2024 (need 4 prior),
    # then valid at Q4-2023+Q1+Q2+Q3 (waiting for 4 in window).
    # Actually pandas rolling with window=4 gives the value at the position
    # that COMPLETES the window. So at position 3 (Q1 2024), the window
    # is [1, 2, 3, 4] -> sum 10. At position 4 (Q4 2024 newest), window is
    # [2, 3, 4, 5] -> sum 14.
    sorted_index = sorted(cols)  # oldest -> newest
    # Trace:
    #   sorted: Q4-23 (1), Q1-24 (2), Q2-24 (3), Q3-24 (4), Q4-24 (5)
    #   window=4 first valid position is index 3 (Q3-24): sum 1+2+3+4=10
    #   next at index 4 (Q4-24): sum 2+3+4+5=14
    assert ttm.loc[sorted_index[0]] != ttm.loc[sorted_index[0]]  # NaN check
    assert ttm.loc[sorted_index[3]] == pytest.approx(10.0)
    assert ttm.loc[sorted_index[4]] == pytest.approx(14.0)


def test_ttm_sum_propagates_nan() -> None:
    """A single NaN in a 4Q window kills that TTM point."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-12-31"),
    ]
    s = pd.Series([5.0, float("nan"), 3.0, 2.0, 1.0], index=cols)

    ttm = _ttm_sum(s)

    sorted_index = sorted(cols)
    # The NaN at Q3-24 falls into 2 windows: ending at Q3-24 (NaN) and
    # ending at Q4-24 (NaN). Both should be NaN.
    val_q3_24 = ttm.loc[sorted_index[3]]
    val_q4_24 = ttm.loc[sorted_index[4]]
    assert pd.isna(val_q3_24)
    assert pd.isna(val_q4_24)


def test_ttm_sum_none_returns_none() -> None:
    """Defensive: None input passes through cleanly."""
    assert _ttm_sum(None) is None


def test_ttm_sum_short_series_all_nan() -> None:
    """Fewer than 4 quarters -> can't compute any TTM. Returns Series
    with all NaN (which _ratio_history then drops, yielding empty
    history)."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
    ]
    s = pd.Series([3.0, 2.0, 1.0], index=cols)

    ttm = _ttm_sum(s)

    assert ttm.isna().all()


# ── _nopat_series ────────────────────────────────────────────────────


@pytest.mark.parametrize("op_income,expected", [(100.0, 79.0), (50.0, 39.5), (0.0, 0.0)])
def test_nopat_series_applies_flat_tax(op_income: float, expected: float) -> None:
    """NOPAT = Op Income × (1 − 0.21). Flat 21% US corporate rate per
    Phase 3.2.D plan; documented in Source.detail."""
    cols = [pd.Timestamp("2024-12-31")]
    s = pd.Series([op_income], index=cols)

    nopat = _nopat_series(s)

    assert nopat.iloc[0] == pytest.approx(expected)


def test_nopat_series_none_returns_none() -> None:
    assert _nopat_series(None) is None


# ── ROE history ──────────────────────────────────────────────────────


def test_roe_history_is_ttm_ni_over_equity() -> None:
    """ROE per quarter = TTM Net Income / Stockholders Equity at that quarter.
    With 8 quarters of input, we get 5 TTM points (lose 3 to warm-up)."""
    fin, bs = _quarterly_with_eq_and_ic_8q()

    out = build_fundamentals_history(
        fin, _cashflow_4q(), bs
    )

    roe = out["roe"]
    # 8 input quarters, lose first 3 to warm-up -> 5 ROE points.
    assert len(roe) == 5
    # Newest quarter Q4-2024: TTM NI = 10+8+6+5 = 29. Equity = 50. ROE = 0.58.
    assert roe[-1].period == "2024-Q4"
    assert roe[-1].value == pytest.approx(29.0 / 50.0)


def test_roe_empty_when_equity_missing() -> None:
    """Without Stockholders Equity row, no ROE history."""
    fin, bs = _quarterly_with_eq_and_ic_8q()
    bs_missing_eq = bs.drop(index="Stockholders Equity")

    out = build_fundamentals_history(fin, _cashflow_4q(), bs_missing_eq)

    assert out["roe"] == []


def test_roe_empty_when_balance_sheet_missing() -> None:
    """Without quarterly_balance_sheet at all, no ROE history."""
    fin, _ = _quarterly_with_eq_and_ic_8q()

    out = build_fundamentals_history(fin, _cashflow_4q(), None)

    assert out["roe"] == []


# ── ROIC history ─────────────────────────────────────────────────────


def test_roic_history_is_ttm_nopat_over_invested_capital() -> None:
    """ROIC per quarter = TTM (Op Income × 0.79) / Invested Capital."""
    fin, bs = _quarterly_with_eq_and_ic_8q()

    out = build_fundamentals_history(fin, _cashflow_4q(), bs)

    roic = out["roic"]
    assert len(roic) == 5
    # Newest quarter Q4-2024: TTM Op Inc = 30+25+20+18 = 93. NOPAT = 93*0.79 = 73.47.
    # Invested Capital = 80. ROIC = 73.47 / 80 = 0.9184.
    assert roic[-1].period == "2024-Q4"
    assert roic[-1].value == pytest.approx(93.0 * 0.79 / 80.0)


def test_roic_empty_when_invested_capital_missing() -> None:
    """yfinance doesn't always expose Invested Capital. Degrade to []
    rather than try to manually compute (multiple conventions in finance
    literature; pick a single source of truth)."""
    fin, bs = _quarterly_with_eq_and_ic_8q()
    bs_no_ic = bs.drop(index="Invested Capital")

    out = build_fundamentals_history(fin, _cashflow_4q(), bs_no_ic)

    assert out["roic"] == []


def test_roic_empty_when_operating_income_missing() -> None:
    """Without Op Income, NOPAT can't be computed."""
    fin, bs = _quarterly_with_eq_and_ic_8q()
    fin_no_oi = fin.drop(index="Operating Income")

    out = build_fundamentals_history(fin_no_oi, _cashflow_4q(), bs)

    assert out["roic"] == []


def test_ttm_metrics_handle_short_history_gracefully() -> None:
    """4 quarters of data produces exactly 1 TTM point (the newest)."""
    fin, bs = _quarterly_with_eq_and_ic_8q()
    # Slice to 4 quarters only.
    fin_4q = fin.iloc[:, :4]
    bs_4q = bs.iloc[:, :4]

    out = build_fundamentals_history(fin_4q, _cashflow_4q(), bs_4q)

    assert len(out["roe"]) == 1
    assert len(out["roic"]) == 1
    # Both should be the newest quarter's TTM.
    assert out["roe"][0].period == "2024-Q4"
    assert out["roic"][0].period == "2024-Q4"


def test_ttm_metrics_empty_when_only_three_quarters() -> None:
    """3 quarters can't produce a TTM (window=4 needs 4 quarters)."""
    fin, bs = _quarterly_with_eq_and_ic_8q()
    fin_3q = fin.iloc[:, :3]
    bs_3q = bs.iloc[:, :3]

    out = build_fundamentals_history(fin_3q, _cashflow_4q(), bs_3q)

    assert out["roe"] == []
    assert out["roic"] == []
