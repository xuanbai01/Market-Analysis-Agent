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
