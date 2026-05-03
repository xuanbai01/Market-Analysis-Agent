"""
Tests for the fetch_fundamentals tool. The async entry point is exercised
through a registered fake provider (no real yfinance call); the yfinance
provider's math is exercised separately via a mocked ``yfinance.Ticker``.

What we're pinning here:

1. Shape — every advertised claim key is present in the response, even
   when the upstream value is missing. Stable shape lets the agent
   compose prompts without per-symbol branching.
2. Provenance — every Claim carries a Source with the right tool id,
   per-key detail, and a fresh fetched_at timestamp.
3. Provider isolation — unknown provider raises before any work happens.
4. Observability — one log_external_call record per call, with claim
   counts in the output_summary.
5. Math — buyback yield, SBC %, and gross-margin trend are computed
   correctly from cashflow / financials DataFrames, including the cases
   where the row is missing or the denominator is zero.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.schemas.research import Claim
from app.services.fundamentals import (
    CLAIM_KEYS,
    PROVIDERS,
    _fetch_yfinance_fundamentals,
    fetch_fundamentals,
)


def _fake_raw(**overrides: Any) -> dict[str, Any]:
    """A fully-populated raw dict matching CLAIM_KEYS — override fields per test."""
    base: dict[str, Any] = {
        "trailing_pe": 25.0,
        "forward_pe": 22.5,
        "p_s": 18.3,
        "ev_ebitda": 30.1,
        "peg": 1.4,
        "roe": 0.115,
        "gross_margin": 0.745,
        "profit_margin": 0.55,
        "dividend_yield": 0.0001,
        "short_ratio": 1.2,
        "shares_short": 250_000_000,
        "market_cap": 4_000_000_000_000,
        "buyback_yield": 0.005,
        "sbc_pct_revenue": 0.04,
        "gross_margin_trend_1y": 0.018,
        # Phase 3.2.A — point-in-time values for the history-bearing claims.
        # These are the most-recent quarter's value (or current snapshot for
        # margins). The history list is provided separately via the
        # provider's tuple return shape.
        "revenue_per_share": 0.10,
        "gross_profit_per_share": 0.07,
        "operating_income_per_share": 0.03,
        "fcf_per_share": 0.02,
        "ocf_per_share": 0.025,
        "operating_margin": 0.30,
        "fcf_margin": 0.20,
        # Phase 3.2.B — cash flow components (Capital Allocation section)
        "capex_per_share": 0.005,
        "sbc_per_share": 0.004,
        # Phase 3.2.C — balance sheet trend (Quality section)
        "cash_and_st_investments_per_share": 0.80,
        "total_debt_per_share": 0.20,
        "total_assets_per_share": 3.00,
        "total_liabilities_per_share": 1.20,
        # Phase 3.2.D — ROIC TTM (Quality section). roe stays in the
        # legacy block above; this is the new derived metric.
        "roic": 0.92,
        # Phase 4.1 — header metadata + 52W band for the hero card.
        "name": "NVIDIA Corporation",
        "sector_tag": "megacap_tech",
        "fifty_two_week_high": 921.04,
        "fifty_two_week_low": 410.18,
    }
    # Sanity: the fixture must list every advertised key, otherwise tests
    # silently miss whichever key was added without updating the fixture.
    assert set(base) == set(CLAIM_KEYS), "fixture out of sync with CLAIM_KEYS"
    base.update(overrides)
    return base


def _fake_provider(
    values: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
) -> Any:
    """Build a sync provider callable matching the new tuple return shape.

    Phase 3.2.A: providers return ``(values, history_map)`` — the history
    map is empty by default so existing tests (which only care about
    point-in-time values) stay terse.
    """
    def _provider(_sym: str) -> tuple[dict[str, Any], dict[str, Any]]:
        return (values if values is not None else _fake_raw()), (history or {})

    return _provider


# ── async entry point ─────────────────────────────────────────────────


async def test_returns_claim_for_each_known_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_fundamentals("NVDA", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for claim in result.values():
        assert isinstance(claim, Claim)


async def test_claims_carry_provider_scoped_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source.tool reflects the provider id; detail varies per claim."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_fundamentals("NVDA", provider="fake")

    pe = result["trailing_pe"]
    assert pe.source.tool == "fake.fundamentals"
    assert "trailingPE" in pe.source.detail  # info-derived → references the .info key
    assert pe.value == 25.0

    bb = result["buyback_yield"]
    assert bb.source.tool == "fake.fundamentals"
    assert "computed" in bb.source.detail.lower()  # computed → flagged in detail


async def test_fetched_at_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    before = datetime.now(UTC)
    result = await fetch_fundamentals("NVDA", provider="fake")
    after = datetime.now(UTC)

    fetched_at = result["trailing_pe"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched_at <= after + timedelta(seconds=1)
    # All claims share one fetched_at — they came from one provider call.
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1


async def test_missing_fields_become_none_valued_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A None value still produces a Claim — keeps the shape stable."""
    raw = _fake_raw(trailing_pe=None, peg=None)
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(raw))

    result = await fetch_fundamentals("NVDA", provider="fake")

    assert "trailing_pe" in result
    assert result["trailing_pe"].value is None
    assert result["peg"].value is None
    # Untouched fields still have their values.
    assert result["roe"].value == 0.115


async def test_provider_returning_partial_dict_fills_missing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that omits a key entirely should still produce a None Claim."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider({"trailing_pe": 25.0}))

    result = await fetch_fundamentals("NVDA", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    assert result["trailing_pe"].value == 25.0
    assert result["roe"].value is None
    assert result["buyback_yield"].value is None


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_fundamentals("NVDA", provider="not-registered")


async def test_symbol_uppercased_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(sym: str) -> tuple[dict[str, Any], dict[str, Any]]:
        seen.append(sym)
        return _fake_raw(), {}

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_fundamentals("nvda", provider="fake")

    assert seen == ["NVDA"]


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    raw = _fake_raw(trailing_pe=None, peg=None)
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(raw))

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_fundamentals("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.fundamentals"
    assert r.input_summary == {"symbol": "NVDA", "provider": "fake"}
    # Output summary records both total claims and how many had data.
    assert r.output_summary["claim_count"] == len(CLAIM_KEYS)
    assert r.output_summary["non_null_count"] == len(CLAIM_KEYS) - 2
    assert r.outcome == "ok"


async def test_provider_exception_is_logged_and_propagated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One tool, one round trip — a provider failure surfaces to the caller.

    Unlike news_ingestion's multi-provider fan-out, fundamentals is single
    -provider. There's nothing to fall back to, so failures must propagate.
    """
    import logging

    def _broken(_sym: str) -> dict[str, Any]:
        raise RuntimeError("yfinance is down")

    monkeypatch.setitem(PROVIDERS, "fake", _broken)

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="yfinance is down"):
            await fetch_fundamentals("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"
    assert records[0].exception_class == "RuntimeError"


# ── yfinance provider math ────────────────────────────────────────────


def _financials_df(
    *, revenue: list[float | None], gross_profit: list[float | None]
) -> pd.DataFrame:
    """Build a yfinance-shaped income-statement DataFrame.

    yfinance returns rows indexed by metric label and columns indexed by
    fiscal-period end date, most-recent first. We use string column
    labels here — the provider only uses ``.iloc`` positionally.
    """
    cols = [f"FY{i}" for i in range(len(revenue))]
    return pd.DataFrame(
        {col: [rev, gp] for col, rev, gp in zip(cols, revenue, gross_profit, strict=True)},
        index=["Total Revenue", "Gross Profit"],
    )


def _cashflow_df(
    *,
    repurchases: float | None = None,
    sbc: float | None = None,
    revenue_for_sbc: float | None = None,
) -> pd.DataFrame:
    """Build a yfinance-shaped cashflow DataFrame, single (latest) column."""
    rows: dict[str, list[float | None]] = {}
    if repurchases is not None:
        rows["Repurchase Of Capital Stock"] = [repurchases]
    if sbc is not None:
        rows["Stock Based Compensation"] = [sbc]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, index=["FY0"]).T


def _patch_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    info: dict[str, Any],
    financials: pd.DataFrame | None = None,
    cashflow: pd.DataFrame | None = None,
    quarterly_financials: pd.DataFrame | None = None,
    quarterly_cashflow: pd.DataFrame | None = None,
    quarterly_balance_sheet: pd.DataFrame | None = None,
) -> None:
    """Install a fake yfinance module so the lazy import inside the provider hits it.

    Phase 3.2.A: ``quarterly_financials`` and ``quarterly_cashflow`` are
    required to populate ``Claim.history``. They default to empty
    DataFrames so existing tests (which only care about the legacy
    point-in-time fields) keep working without per-test fan-out.

    Phase 3.2.C: ``quarterly_balance_sheet`` likewise — required for BS
    trend histories, default empty.
    """
    import sys
    from unittest.mock import MagicMock

    fake_ticker = MagicMock()
    fake_ticker.info = info
    fake_ticker.financials = financials if financials is not None else pd.DataFrame()
    fake_ticker.cashflow = cashflow if cashflow is not None else pd.DataFrame()
    fake_ticker.quarterly_financials = (
        quarterly_financials if quarterly_financials is not None else pd.DataFrame()
    )
    fake_ticker.quarterly_cashflow = (
        quarterly_cashflow if quarterly_cashflow is not None else pd.DataFrame()
    )
    fake_ticker.quarterly_balance_sheet = (
        quarterly_balance_sheet
        if quarterly_balance_sheet is not None
        else pd.DataFrame()
    )

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker

    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


def test_yfinance_passes_info_fields_through(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {
        "trailingPE": 25.0,
        "forwardPE": 22.5,
        "priceToSalesTrailing12Months": 18.3,
        "enterpriseToEbitda": 30.1,
        "trailingPegRatio": 1.4,
        "returnOnEquity": 0.115,
        "grossMargins": 0.745,
        "profitMargins": 0.55,
        "dividendYield": 0.0001,
        "shortRatio": 1.2,
        "sharesShort": 250_000_000,
        "marketCap": 4_000_000_000_000,
    }
    _patch_yfinance(monkeypatch, info=info)

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["trailing_pe"] == 25.0
    assert raw["forward_pe"] == 22.5
    assert raw["p_s"] == 18.3
    assert raw["ev_ebitda"] == 30.1
    assert raw["peg"] == 1.4
    assert raw["roe"] == 0.115
    assert raw["market_cap"] == 4_000_000_000_000


def test_yfinance_missing_info_keys_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, info={"trailingPE": 25.0})

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["trailing_pe"] == 25.0
    assert raw["forward_pe"] is None
    assert raw["roe"] is None


def test_yfinance_buyback_yield_uses_absolute_repurchases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance reports stock repurchases as a negative cash outflow.

    The signed convention would give a negative buyback "yield"; we
    take abs() so 5% buybacks read as 0.05, not -0.05.
    """
    _patch_yfinance(
        monkeypatch,
        info={"marketCap": 1_000_000_000},
        cashflow=_cashflow_df(repurchases=-50_000_000),
    )

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["buyback_yield"] == pytest.approx(0.05)


def test_yfinance_buyback_yield_none_when_market_cap_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero or missing market cap → None, not a divide-by-zero."""
    _patch_yfinance(
        monkeypatch, info={}, cashflow=_cashflow_df(repurchases=-50_000_000)
    )

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["buyback_yield"] is None


def test_yfinance_sbc_pct_revenue_from_cashflow_and_financials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(
        monkeypatch,
        info={},
        financials=_financials_df(revenue=[1_000.0], gross_profit=[700.0]),
        cashflow=_cashflow_df(sbc=40.0),
    )

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["sbc_pct_revenue"] == pytest.approx(0.04)


def test_yfinance_sbc_pct_revenue_none_when_revenue_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(monkeypatch, info={}, cashflow=_cashflow_df(sbc=40.0))

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["sbc_pct_revenue"] is None


def test_yfinance_gross_margin_trend_yoy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Latest GM is 70%, prior is 65%; trend should be +0.05 (5 pp)."""
    _patch_yfinance(
        monkeypatch,
        info={},
        financials=_financials_df(
            revenue=[1_000.0, 1_000.0],
            gross_profit=[700.0, 650.0],
        ),
    )

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["gross_margin_trend_1y"] == pytest.approx(0.05)


def test_yfinance_gross_margin_trend_none_with_only_one_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Need two periods to compute a YoY delta — one period gives None."""
    _patch_yfinance(
        monkeypatch,
        info={},
        financials=_financials_df(revenue=[1_000.0], gross_profit=[700.0]),
    )

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["gross_margin_trend_1y"] is None


def test_yfinance_handles_completely_empty_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol with no financials at all (delisted, brand-new IPO, etc.)
    must not raise — every key returns None, the agent decides what to do."""
    _patch_yfinance(monkeypatch, info={})

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert set(raw.keys()) == set(CLAIM_KEYS)
    assert all(v is None for v in raw.values())


# ── Phase 3.2.A: history-bearing fields ──────────────────────────────


def _quarterly_financials_4q() -> pd.DataFrame:
    """4 quarters of synthetic income-statement data, newest-first."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
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


def _quarterly_cashflow_4q() -> pd.DataFrame:
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [25.0, 22.0, 18.0, 15.0],
            [-5.0, -4.0, -3.0, -2.0],
            [20.0, 18.0, 15.0, 13.0],
        ],
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
        columns=cols,
    )


def test_yfinance_returns_latest_quarter_value_for_new_per_share_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point-in-time ``value`` for new history-bearing claims is the
    most-recent quarter's figure. The renderer pairs this with the
    sparkline (history[-1] == value, by construction)."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_4q(),
        quarterly_cashflow=_quarterly_cashflow_4q(),
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    # Latest quarter (column 0): Q4 2024.
    assert raw["revenue_per_share"] == pytest.approx(100.0 / 1000.0)
    assert raw["gross_profit_per_share"] == pytest.approx(70.0 / 1000.0)
    assert raw["operating_income_per_share"] == pytest.approx(30.0 / 1000.0)
    assert raw["fcf_per_share"] == pytest.approx(20.0 / 1000.0)
    assert raw["ocf_per_share"] == pytest.approx(25.0 / 1000.0)
    assert raw["operating_margin"] == pytest.approx(30.0 / 100.0)
    assert raw["fcf_margin"] == pytest.approx(20.0 / 100.0)


def test_yfinance_returns_history_for_history_bearing_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider's tuple's second element is the history map. The 9
    Phase 3.2.A history-bearing claims each carry a list ordered
    oldest-to-newest. Other keys (3.2.B + 3.2.C) are present in the
    map but empty because the basic fixture doesn't include their
    source rows."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_4q(),
        quarterly_cashflow=_quarterly_cashflow_4q(),
    )

    _, history = _fetch_yfinance_fundamentals("NVDA")

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
    assert phase_3_2_a_keys <= set(history.keys())
    for key in phase_3_2_a_keys:
        hist = history[key]
        assert len(hist) == 4, f"{key} should have 4 quarters"
        assert hist[0].period == "2024-Q1"
        assert hist[-1].period == "2024-Q4"


async def test_history_propagates_to_claim_dot_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: provider's history map gets attached to the right Claim's
    ``.history`` field; non-history-bearing claims get ``[]``."""
    from app.schemas.research import ClaimHistoryPoint

    history_map = {
        "revenue_per_share": [
            ClaimHistoryPoint(period="2024-Q1", value=0.07),
            ClaimHistoryPoint(period="2024-Q4", value=0.10),
        ],
        "gross_margin": [
            ClaimHistoryPoint(period="2024-Q1", value=0.65),
            ClaimHistoryPoint(period="2024-Q4", value=0.70),
        ],
    }
    monkeypatch.setitem(
        PROVIDERS, "fake", _fake_provider(_fake_raw(), history=history_map)
    )

    result = await fetch_fundamentals("NVDA", provider="fake")

    assert len(result["revenue_per_share"].history) == 2
    assert result["revenue_per_share"].history[-1].value == 0.10
    assert len(result["gross_margin"].history) == 2
    assert result["gross_margin"].history[-1].value == 0.70
    # Claims that the provider didn't supply history for: empty list
    # (NOT None — see app/schemas/research.py default_factory rationale).
    assert result["trailing_pe"].history == []
    assert result["market_cap"].history == []


async def test_no_history_provided_means_empty_history_on_every_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backwards-compat path: a provider that returns ``({}, {})`` for
    history (or omits it entirely) yields claims with ``history == []``."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(_fake_raw()))

    result = await fetch_fundamentals("NVDA", provider="fake")

    for claim in result.values():
        assert claim.history == []


# ── Phase 3.2.B+C: cash flow components + balance sheet trend ────────


def _qcf_with_components_4q() -> pd.DataFrame:
    """Cashflow with the rows Phase 3.2.B consumes."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [25.0, 22.0, 18.0, 15.0],
            [-5.0, -4.0, -3.0, -2.0],
            [20.0, 18.0, 15.0, 13.0],
            [4.0, 3.5, 3.0, 2.5],
        ],
        index=[
            "Operating Cash Flow",
            "Capital Expenditure",
            "Free Cash Flow",
            "Stock Based Compensation",
        ],
        columns=cols,
    )


def _qbs_4q() -> pd.DataFrame:
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    return pd.DataFrame(
        [
            [800.0, 750.0, 700.0, 650.0],
            [200.0, 220.0, 240.0, 250.0],
            [3000.0, 2800.0, 2600.0, 2400.0],
            [1200.0, 1150.0, 1100.0, 1050.0],
        ],
        index=[
            "Cash Cash Equivalents And Short Term Investments",
            "Total Debt",
            "Total Assets",
            "Total Liabilities Net Minority Interest",
        ],
        columns=cols,
    )


def test_yfinance_returns_capex_and_sbc_per_share_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.2.B: capex_per_share + sbc_per_share appear in the
    history map, computed from quarterly_cashflow rows."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_4q(),
        quarterly_cashflow=_qcf_with_components_4q(),
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    assert "capex_per_share" in history
    assert "sbc_per_share" in history
    assert len(history["capex_per_share"]) == 4
    assert len(history["sbc_per_share"]) == 4
    # Snapshot uses absolute value for CapEx (chart displays magnitude).
    assert raw["capex_per_share"] == pytest.approx(5.0 / 1000.0)
    assert raw["sbc_per_share"] == pytest.approx(4.0 / 1000.0)


def test_yfinance_returns_balance_sheet_per_share_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.2.C: 4 balance-sheet per-share metrics appear in the
    history map, computed from quarterly_balance_sheet rows."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_4q(),
        quarterly_balance_sheet=_qbs_4q(),
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    bs_keys = {
        "cash_and_st_investments_per_share",
        "total_debt_per_share",
        "total_assets_per_share",
        "total_liabilities_per_share",
    }
    for key in bs_keys:
        assert key in history, f"{key} missing from history map"
        assert len(history[key]) == 4
    # Snapshot values match the latest quarter.
    assert raw["cash_and_st_investments_per_share"] == pytest.approx(0.80)
    assert raw["total_debt_per_share"] == pytest.approx(0.20)
    assert raw["total_assets_per_share"] == pytest.approx(3.00)
    assert raw["total_liabilities_per_share"] == pytest.approx(1.20)


def test_yfinance_balance_sheet_metrics_none_when_frame_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol where yfinance doesn't return quarterly_balance_sheet —
    BS metrics should be None / [] without raising."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_4q(),
        # quarterly_balance_sheet defaults to empty DataFrame
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    assert raw["cash_and_st_investments_per_share"] is None
    assert raw["total_debt_per_share"] is None
    assert raw["total_assets_per_share"] is None
    assert raw["total_liabilities_per_share"] is None
    assert history["cash_and_st_investments_per_share"] == []
    assert history["total_debt_per_share"] == []


# ── Phase 3.2.D: ROE + ROIC TTM histories ────────────────────────────


def _quarterly_financials_8q() -> pd.DataFrame:
    """8 quarters — TTM metrics need 4 prior quarters of warm-up."""
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2023-09-30"),
        pd.Timestamp("2023-06-30"),
        pd.Timestamp("2023-03-31"),
    ]
    return pd.DataFrame(
        [
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


def _quarterly_balance_sheet_8q() -> pd.DataFrame:
    cols = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2023-09-30"),
        pd.Timestamp("2023-06-30"),
        pd.Timestamp("2023-03-31"),
    ]
    return pd.DataFrame(
        [
            [50.0, 48.0, 46.0, 44.0, 42.0, 40.0, 38.0, 36.0],
            [80.0, 78.0, 76.0, 74.0, 72.0, 70.0, 68.0, 66.0],
        ],
        index=["Stockholders Equity", "Invested Capital"],
        columns=cols,
    )


def test_yfinance_attaches_ttm_history_to_existing_roe_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.2.D: the existing ``roe`` claim's snapshot stays from
    info.returnOnEquity, but it now gets a TTM-based quarterly history
    attached. Mirrors the gross_margin / profit_margin pattern."""
    _patch_yfinance(
        monkeypatch,
        info={"returnOnEquity": 0.55},
        quarterly_financials=_quarterly_financials_8q(),
        quarterly_balance_sheet=_quarterly_balance_sheet_8q(),
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    # Snapshot still from info.
    assert raw["roe"] == 0.55
    # 8 quarters of NI/Equity -> 5 TTM ROE points after warm-up.
    assert "roe" in history
    assert len(history["roe"]) == 5


def test_yfinance_returns_roic_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.2.D: roic is a NEW history-bearing claim. Snapshot value
    is the latest TTM ROIC (= history[-1].value); no info source."""
    _patch_yfinance(
        monkeypatch,
        info={},
        quarterly_financials=_quarterly_financials_8q(),
        quarterly_balance_sheet=_quarterly_balance_sheet_8q(),
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    assert "roic" in history
    assert len(history["roic"]) == 5
    # Snapshot matches history[-1] by construction.
    assert raw["roic"] == pytest.approx(history["roic"][-1].value)
    # Q4-2024: TTM Op Inc = 93, NOPAT = 93*0.79, IC = 80, ROIC = 0.9184.
    assert raw["roic"] == pytest.approx(93.0 * 0.79 / 80.0)


def test_yfinance_roic_none_when_invested_capital_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Invested Capital row -> roic snapshot is None and history empty.
    Other metrics (incl. ROE) still populate when their sources are present."""
    bs = _quarterly_balance_sheet_8q().drop(index="Invested Capital")
    _patch_yfinance(
        monkeypatch,
        info={"returnOnEquity": 0.55},
        quarterly_financials=_quarterly_financials_8q(),
        quarterly_balance_sheet=bs,
    )

    raw, history = _fetch_yfinance_fundamentals("NVDA")

    assert raw["roic"] is None
    assert history["roic"] == []
    # ROE survives because Stockholders Equity still present.
    assert len(history["roe"]) == 5


# ── Phase 4.1 — header metadata + 52W band ───────────────────────────


async def test_claim_keys_includes_phase_4_1_additions() -> None:
    """name / sector_tag / fifty_two_week_high / fifty_two_week_low all
    surface in CLAIM_KEYS so the hero card can read them."""
    for key in ("name", "sector_tag", "fifty_two_week_high", "fifty_two_week_low"):
        assert key in CLAIM_KEYS, f"{key} missing from CLAIM_KEYS"


async def test_name_and_sector_tag_carry_string_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """name + sector_tag are string-valued claims (not numeric)."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())
    result = await fetch_fundamentals("NVDA", provider="fake")

    assert result["name"].value == "NVIDIA Corporation"
    assert result["sector_tag"].value == "megacap_tech"
    # No history on metadata claims.
    assert result["name"].history == []
    assert result["sector_tag"].history == []


async def test_fifty_two_week_band_carries_numeric_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """52W high/low are numeric claims for the hero meta line."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())
    result = await fetch_fundamentals("NVDA", provider="fake")

    assert result["fifty_two_week_high"].value == 921.04
    assert result["fifty_two_week_low"].value == 410.18


def test_yfinance_pulls_name_and_52w_from_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance provider sources name from info.longName, 52W from
    info.fiftyTwoWeekHigh / fiftyTwoWeekLow, sector_tag from the
    sectors resolver (industry → curated map)."""
    info = {
        "longName": "NVIDIA Corporation",
        "industry": "Semiconductors",
        "fiftyTwoWeekHigh": 921.04,
        "fiftyTwoWeekLow": 410.18,
        # All other info fields fall through to None elsewhere
    }
    _patch_yfinance(monkeypatch, info=info)

    raw, _ = _fetch_yfinance_fundamentals("NVDA")

    assert raw["name"] == "NVIDIA Corporation"
    assert raw["fifty_two_week_high"] == pytest.approx(921.04)
    assert raw["fifty_two_week_low"] == pytest.approx(410.18)
    # sector_tag derives from the industry → curated sectors map.
    # We don't pin a specific value (the sectors map evolves); we just
    # confirm a non-None resolution for a known-mapped industry.
    assert raw["sector_tag"] is not None


def test_yfinance_metadata_none_when_info_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty info → all 4 metadata fields default to None gracefully."""
    _patch_yfinance(monkeypatch, info={})
    raw, _ = _fetch_yfinance_fundamentals("UNKNOWN")
    assert raw["name"] is None
    assert raw["fifty_two_week_high"] is None
    assert raw["fifty_two_week_low"] is None
    # sector_tag may resolve via the symbol map (curated names short-
    # circuit industry resolution); we don't assert here since "UNKNOWN"
    # isn't in any curated list.
