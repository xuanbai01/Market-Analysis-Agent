"""
Annual per-share history from SEC XBRL (2026-11).

yfinance's statements stop at ~5 quarters, so the per-share growth card
could only say "+7.4% year over year". SEC filings go back a decade, but
their share counts are as filed: NVDA's CY2018 diluted shares (filed Feb
2021) predate its 4:1 (2021) and 10:1 (2024) splits. These tests pin the
split adjustment, the per-share maths and the claim shape.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import annual_history as ah


def raw(**overrides: Any) -> dict[str, Any]:
    """NVDA-shaped raw facts: shares as filed, two later splits."""
    base: dict[str, Any] = {
        "revenue": {2018: (11.7e9, "2021-02-26"), 2019: (10.9e9, "2022-03-18"), 2025: (216e9, "2026-02-25")},
        "operating_income": {2018: (3.8e9, "2021-02-26"), 2025: (130e9, "2026-02-25")},
        "ocf": {2019: (4.8e9, "2022-03-18"), 2025: (100e9, "2026-02-25")},
        "capex": {2019: (0.5e9, "2022-03-18"), 2025: (3.4e9, "2026-02-25")},
        # As filed: 625M before both splits, 2.472B after the 4:1 only.
        "shares": {2018: (625e6, "2021-02-26"), 2019: (2_472e6, "2022-03-18"), 2025: (24_514e6, "2026-02-25")},
        "eps": {2018: (6.63, "2021-02-26"), 2025: (4.90, "2026-02-25")},
        "splits": [("2021-07-20", 4.0), ("2024-06-10", 10.0)],
    }
    base.update(overrides)
    return base


def by_year(points: list[Any]) -> dict[str, float]:
    return {p.period: round(p.value, 4) for p in points}


def test_share_counts_and_eps_are_adjusted_for_splits_after_their_filing() -> None:
    series = ah.per_share_series(raw())
    # 625M × 4 × 10 = 25.0B shares → 11.7B / 25.0B = $0.468
    assert by_year(series["revenue_per_share_annual"])["2018"] == pytest.approx(0.468, abs=1e-3)
    # 2.472B × 10 = 24.72B → 10.9B / 24.72B
    assert by_year(series["revenue_per_share_annual"])["2019"] == pytest.approx(10.9 / 24.72, abs=1e-3)
    # EPS filed before both splits: 6.63 / 40
    assert by_year(series["eps_diluted_annual"])["2018"] == pytest.approx(6.63 / 40, abs=1e-4)
    assert by_year(series["eps_diluted_annual"])["2025"] == pytest.approx(4.90)


def test_free_cash_flow_needs_both_operating_cash_flow_and_capex() -> None:
    series = ah.per_share_series(raw())
    fcf = by_year(series["fcf_per_share_annual"])
    assert set(fcf) == {"2019", "2025"}  # 2018 has no OCF / capex
    assert fcf["2025"] == pytest.approx((100e9 - 3.4e9) / 24_514e6, abs=1e-4)


def test_the_window_is_the_latest_eleven_years() -> None:
    """Eleven annual points span ten years of growth."""
    years = range(2005, 2026)
    data = raw(
        revenue={y: (float(y), "2026-02-01") for y in years},
        shares={y: (1.0, "2026-02-01") for y in years},
        operating_income={},
        ocf={},
        capex={},
        eps={},
        splits=[],
    )
    periods = [p.period for p in ah.per_share_series(data)["revenue_per_share_annual"]]
    assert periods == [str(y) for y in range(2015, 2026)]


def test_an_unadjusted_split_cuts_the_history_at_the_jump() -> None:
    """Without split data a 10× share jump would read as a 90% collapse in
    revenue per share; the years before the jump are dropped instead."""
    data = raw(splits=[])
    periods = [p.period for p in ah.per_share_series(data)["revenue_per_share_annual"]]
    assert periods == ["2025"]


def test_claims_keep_a_stable_shape() -> None:
    claims = ah.build_claims(ah.per_share_series(raw()))
    assert set(claims) == set(ah.CLAIM_KEYS)
    # The year-end multiples are part of the shape even with no prices.
    assert set(ah.CLAIM_KEYS) == set(ah.PER_SHARE_KEYS) | {"pe_annual", "ps_annual", "pfcf_annual"}
    assert claims["pe_annual"].value is None
    assert claims["pe_annual"].unit == "ratio"
    rev = claims["revenue_per_share_annual"]
    assert rev.description == "Revenue per share, annual (SEC filings)"
    assert rev.unit == "usd_per_share"
    assert rev.source.tool == "sec.xbrl"
    assert rev.value == pytest.approx(216e9 / 24_514e6)
    assert [p.period for p in rev.history] == ["2018", "2019", "2025"]
    # Operating income has 2 points; a series with fewer is empty, not dropped.
    empty = ah.build_claims(ah.per_share_series(raw(operating_income={2025: (1.0, "2026-02-25")})))
    assert empty["operating_income_per_share_annual"].value is None
    assert empty["operating_income_per_share_annual"].history == []


def test_goods_revenue_fills_missing_years_only_without_services_revenue() -> None:
    """KO tagged its whole revenue SalesRevenueGoodsNet until 2016; for a
    company that also files services revenue, goods is only part of it."""
    revenue = {2016: (41.9e9, "2019-02-22")}
    goods = {2015: (44.3e9, "2018-02-23"), 2014: (45.9e9, "2017-02-24"), 2016: (41.0e9, "2019-02-22")}
    services = {2014: (1.0e9, "2017-02-24")}
    merged = ah.merge_goods_revenue(revenue, goods=goods, services=services)
    assert merged == {2015: (44.3e9, "2018-02-23"), 2016: (41.9e9, "2019-02-22")}


async def test_fetch_uses_the_provider_and_uppercases_the_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake(symbol: str) -> dict[str, Any]:
        seen.append(symbol)
        return raw()

    monkeypatch.setitem(ah.PROVIDERS, "fake", fake)
    claims = await ah.fetch_annual_history("nvda", provider="fake")
    assert seen == ["NVDA"]
    assert claims["revenue_per_share_annual"].history


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        await ah.fetch_annual_history("NVDA", provider="nope")


# ── Year-end multiples (2026-11, valuation history) ──────────────────

PRICED = {
    # NVDA's fiscal years end in late January of the next calendar year.
    "period_ends": {2018: "2019-01-27", 2019: "2020-01-26", 2025: "2026-01-25"},
    "closes": [("2019-01-25", 4.0), ("2020-01-24", 6.25), ("2026-01-23", 176.2)],
}


def test_year_end_multiples_divide_the_close_by_the_split_adjusted_figures() -> None:
    series = ah.all_series(raw(**PRICED))

    # 2018: revenue 11.7e9 over 625M x 40 shares = $0.468; close $4.00.
    assert by_year(series["ps_annual"]) == {
        "2018": round(4.0 / (11.7e9 / 25e9), 4),
        "2019": round(6.25 / (10.9e9 / 24.72e9), 4),
        "2025": round(176.2 / (216e9 / 24.514e9), 4),
    }
    # EPS filed before both splits: 6.63 / 40.
    assert by_year(series["pe_annual"]) == {
        "2018": round(4.0 / (6.63 / 40), 4),
        "2025": round(176.2 / 4.90, 4),
    }
    assert by_year(series["pfcf_annual"]) == {
        "2019": round(6.25 / ((4.8e9 - 0.5e9) / 24.72e9), 4),
        "2025": round(176.2 / ((100e9 - 3.4e9) / 24.514e9), 4),
    }
    # The per-share series are untouched.
    assert by_year(series["revenue_per_share_annual"])["2025"] == round(216e9 / 24.514e9, 4)


def test_without_prices_the_multiples_are_empty_and_the_rest_stands() -> None:
    series = ah.all_series(raw())
    assert series["pe_annual"] == [] and series["ps_annual"] == [] and series["pfcf_annual"] == []
    assert series["revenue_per_share_annual"]


async def test_fetch_returns_the_multiples_as_ratio_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ah.PROVIDERS, "fake", lambda _symbol: raw(**PRICED))

    claims = await ah.fetch_annual_history("NVDA", provider="fake")

    ps = claims["ps_annual"]
    assert ps.description == "Price-to-sales at fiscal year-end (SEC filings)"
    assert ps.unit == "ratio"
    assert ps.source.tool == "sec.xbrl"
    assert [p.period for p in ps.history] == ["2018", "2019", "2025"]
    assert ps.value == ps.history[-1].value
