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
    }
    # Sanity: the fixture must list every advertised key, otherwise tests
    # silently miss whichever key was added without updating the fixture.
    assert set(base) == set(CLAIM_KEYS), "fixture out of sync with CLAIM_KEYS"
    base.update(overrides)
    return base


# ── async entry point ─────────────────────────────────────────────────


async def test_returns_claim_for_each_known_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_fundamentals("NVDA", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for claim in result.values():
        assert isinstance(claim, Claim)


async def test_claims_carry_provider_scoped_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source.tool reflects the provider id; detail varies per claim."""
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_fundamentals("NVDA", provider="fake")

    pe = result["trailing_pe"]
    assert pe.source.tool == "fake.fundamentals"
    assert "trailingPE" in pe.source.detail  # info-derived → references the .info key
    assert pe.value == 25.0

    bb = result["buyback_yield"]
    assert bb.source.tool == "fake.fundamentals"
    assert "computed" in bb.source.detail.lower()  # computed → flagged in detail


async def test_fetched_at_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

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
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

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
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: {"trailing_pe": 25.0})

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

    def _capture(sym: str) -> dict[str, Any]:
        seen.append(sym)
        return _fake_raw()

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_fundamentals("nvda", provider="fake")

    assert seen == ["NVDA"]


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    raw = _fake_raw(trailing_pe=None, peg=None)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

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
) -> None:
    """Install a fake yfinance module so the lazy import inside the provider hits it."""
    import sys
    from unittest.mock import MagicMock

    fake_ticker = MagicMock()
    fake_ticker.info = info
    fake_ticker.financials = financials if financials is not None else pd.DataFrame()
    fake_ticker.cashflow = cashflow if cashflow is not None else pd.DataFrame()

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

    raw = _fetch_yfinance_fundamentals("NVDA")

    assert raw["trailing_pe"] == 25.0
    assert raw["forward_pe"] == 22.5
    assert raw["p_s"] == 18.3
    assert raw["ev_ebitda"] == 30.1
    assert raw["peg"] == 1.4
    assert raw["roe"] == 0.115
    assert raw["market_cap"] == 4_000_000_000_000


def test_yfinance_missing_info_keys_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, info={"trailingPE": 25.0})

    raw = _fetch_yfinance_fundamentals("NVDA")

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

    raw = _fetch_yfinance_fundamentals("NVDA")

    assert raw["buyback_yield"] == pytest.approx(0.05)


def test_yfinance_buyback_yield_none_when_market_cap_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero or missing market cap → None, not a divide-by-zero."""
    _patch_yfinance(
        monkeypatch, info={}, cashflow=_cashflow_df(repurchases=-50_000_000)
    )

    raw = _fetch_yfinance_fundamentals("NVDA")

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

    raw = _fetch_yfinance_fundamentals("NVDA")

    assert raw["sbc_pct_revenue"] == pytest.approx(0.04)


def test_yfinance_sbc_pct_revenue_none_when_revenue_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(monkeypatch, info={}, cashflow=_cashflow_df(sbc=40.0))

    raw = _fetch_yfinance_fundamentals("NVDA")

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

    raw = _fetch_yfinance_fundamentals("NVDA")

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

    raw = _fetch_yfinance_fundamentals("NVDA")

    assert raw["gross_margin_trend_1y"] is None


def test_yfinance_handles_completely_empty_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol with no financials at all (delisted, brand-new IPO, etc.)
    must not raise — every key returns None, the agent decides what to do."""
    _patch_yfinance(monkeypatch, info={})

    raw = _fetch_yfinance_fundamentals("NVDA")

    assert set(raw.keys()) == set(CLAIM_KEYS)
    assert all(v is None for v in raw.values())
