"""
Derived comparison claims (app/services/research_derived.py, ADR 0007).

Fixtures use round numbers so every expected value can be checked by
hand: five quarters 2025-Q3 … 2026-Q3, so "a year apart" is Q3 → Q3 and
TTM sums the last four.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.research import Claim, ClaimHistoryPoint, Source
from app.services import research_derived as rd

PERIODS = ["2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]
FETCHED = datetime(2026, 11, 8, 14, 0, tzinfo=UTC)


def c(value: object, history: list[float] | None = None, tool: str = "yfinance.fundamentals") -> Claim:
    return Claim(
        description="x",
        value=value,
        source=Source(tool=tool, fetched_at=FETCHED),
        history=[ClaimHistoryPoint(period=p, value=v) for p, v in zip(PERIODS[-len(history):], history, strict=True)]
        if history
        else [],
    )


def by_description(claims: list[Claim]) -> dict[str, Claim]:
    return {cl.description: cl for cl in claims}


# A KO-like company: revenue $3/quarter, FCF $1/quarter, net margin 25%.
FUND = {
    "trailing_pe": c(28.0),
    "forward_pe": c(26.0),
    "p_s": c(8.0),
    "ev_ebitda": c(25.0),
    "gross_margin": c(0.62),
    "profit_margin": c(0.25),
    "dividend_yield": c(2.9),  # percent-form, as yfinance returns it
    "buyback_yield": c(0.01),
    "operating_margin": c(0.34, [0.30, 0.25, 0.31, 0.33, 0.34]),
    "fcf_margin": c(0.33, [0.36, 0.30, 0.15, 0.37, 0.33]),
    "revenue_per_share": c(3.1, [2.8, 2.9, 2.7, 3.0, 3.1]),
    "operating_income_per_share": c(1.05, [0.84, 0.73, 0.84, 0.99, 1.05]),
    "fcf_per_share": c(1.0, [1.0, 0.9, 0.4, 1.1, 1.0]),
    "ocf_per_share": c(1.2, [1.2, 1.0, 0.5, 1.3, 1.2]),
    "capex_per_share": c(0.1, [0.08, 0.1, 0.1, 0.12, 0.1]),
    "sbc_per_share": c(0.02, [0.02, 0.02, 0.02, 0.02, 0.02]),
    "total_debt_per_share": c(9.6),
    "cash_and_st_investments_per_share": c(3.8),
}
REV_TTM = 2.9 + 2.7 + 3.0 + 3.1  # 11.7
FCF_TTM = 0.9 + 0.4 + 1.1 + 1.0  # 3.4
OCF_TTM = 1.0 + 0.5 + 1.3 + 1.2  # 4.0
CAPEX_TTM = 0.1 + 0.1 + 0.12 + 0.1  # 0.42


class TestQuality:
    def test_margin_change_against_the_same_quarter_last_year(self) -> None:
        d = by_description(rd.quality_claims(FUND))
        op = d["Operating margin change, 2025-Q3 → 2026-Q3"]
        assert op.value == pytest.approx(0.04)
        assert op.unit == "percentage_points"
        assert d["Free cash flow margin change, 2025-Q3 → 2026-Q3"].value == pytest.approx(-0.03)

    def test_per_share_growth_year_over_year(self) -> None:
        d = by_description(rd.quality_claims(FUND))
        assert d["Revenue per share growth, 2025-Q3 → 2026-Q3"].value == pytest.approx(3.1 / 2.8 - 1)
        assert d["Operating income per share growth, 2025-Q3 → 2026-Q3"].value == pytest.approx(1.05 / 0.84 - 1)

    def test_ttm_fcf_margin_and_conversion(self) -> None:
        d = by_description(rd.quality_claims(FUND))
        ttm = d["Free cash flow margin (trailing 4 quarters)"].value
        assert ttm == pytest.approx(FCF_TTM / REV_TTM)
        assert d["Free cash flow ÷ net income (trailing 12 months)"].value == pytest.approx(ttm / 0.25)

    def test_net_debt_and_years_to_repay(self) -> None:
        d = by_description(rd.quality_claims(FUND))
        assert d["Net debt per share (debt minus cash; negative = net cash)"].value == pytest.approx(5.8)
        assert d["Net debt ÷ trailing-12-month operating cash flow (years to repay)"].value == pytest.approx(
            5.8 / OCF_TTM
        )

    def test_net_cash_company_gets_no_years_to_repay(self) -> None:
        cash_rich = {**FUND, "total_debt_per_share": c(1.0), "cash_and_st_investments_per_share": c(4.0)}
        d = by_description(rd.quality_claims(cash_rich))
        assert d["Net debt per share (debt minus cash; negative = net cash)"].value == pytest.approx(-3.0)
        assert not any("years to repay" in k for k in d)

    def test_short_history_skips_year_over_year(self) -> None:
        short = {**FUND, "operating_margin": c(0.34, [0.31, 0.33, 0.34])}
        d = by_description(rd.quality_claims(short))
        assert not any(k.startswith("Operating margin change") for k in d)

    def test_loss_making_base_skips_growth_and_conversion(self) -> None:
        losses = {
            **FUND,
            "operating_income_per_share": c(-0.2, [-0.9, -0.7, -0.6, -0.4, -0.2]),
            "profit_margin": c(-0.3),
        }
        d = by_description(rd.quality_claims(losses))
        assert not any(k.startswith("Operating income per share growth") for k in d)
        assert not any(k.startswith("Free cash flow ÷ net income") for k in d)

    def test_every_claim_is_sourced_as_computed_with_its_formula(self) -> None:
        for claim in rd.quality_claims(FUND):
            assert claim.source.tool == rd.DERIVED_TOOL
            assert claim.source.detail
            assert claim.source.fetched_at == FETCHED
            assert claim.unit is not None


class TestCapitalAllocation:
    def test_payout_ratio_from_yield_and_pe(self) -> None:
        d = by_description(rd.capital_allocation_claims(FUND))
        assert d["Dividend payout ratio (forward dividend ÷ trailing earnings)"].value == pytest.approx(0.029 * 28)

    def test_fcf_yield_and_dividend_coverage(self) -> None:
        d = by_description(rd.capital_allocation_claims(FUND))
        fcf_yield = (FCF_TTM / REV_TTM) / 8.0
        assert d["Free cash flow yield (trailing 12 months)"].value == pytest.approx(fcf_yield)
        assert d["Free cash flow ÷ dividends paid (coverage)"].value == pytest.approx(fcf_yield / 0.029)

    def test_shareholder_yield_adds_dividend_and_buybacks_in_one_unit(self) -> None:
        d = by_description(rd.capital_allocation_claims(FUND))
        assert d["Shareholder yield (forward dividend + latest-year buybacks)"].value == pytest.approx(0.039)

    def test_capex_intensity_share_of_ocf_and_growth(self) -> None:
        d = by_description(rd.capital_allocation_claims(FUND))
        assert d["Capex as % of revenue (trailing 12 months)"].value == pytest.approx(CAPEX_TTM / REV_TTM)
        assert d["Capex as % of operating cash flow (trailing 12 months)"].value == pytest.approx(CAPEX_TTM / OCF_TTM)
        assert d["Capex per share growth, 2025-Q3 → 2026-Q3"].value == pytest.approx(0.1 / 0.08 - 1)

    def test_sbc_share_of_fcf(self) -> None:
        d = by_description(rd.capital_allocation_claims(FUND))
        assert d["Stock-based compensation as % of free cash flow (trailing 12 months)"].value == pytest.approx(
            0.08 / FCF_TTM
        )

    def test_no_dividend_means_no_payout_or_coverage(self) -> None:
        d = by_description(rd.capital_allocation_claims({**FUND, "dividend_yield": c(None)}))
        assert not any("payout" in k or "coverage" in k for k in d)
        assert not any(k.startswith("Shareholder yield") for k in d)

    def test_cash_burner_gets_a_negative_fcf_yield_but_no_coverage(self) -> None:
        burner = {**FUND, "fcf_per_share": c(-0.5, [-0.5, -0.6, -0.5, -0.4, -0.5])}
        d = by_description(rd.capital_allocation_claims(burner))
        assert d["Free cash flow yield (trailing 12 months)"].value < 0
        assert not any("coverage" in k for k in d)
        assert not any(k.startswith("Stock-based compensation as % of free cash flow") for k in d)


PEERS = {
    "median.trailing_pe": c(35.24, tool="yfinance.peers"),
    "median.p_s": c(1.75, tool="yfinance.peers"),
    "median.ev_ebitda": c(20.0, tool="yfinance.peers"),
    "median.gross_margin": c(0.40, tool="yfinance.peers"),
}


class TestValuation:
    def test_premium_or_discount_to_the_peer_median(self) -> None:
        d = by_description(rd.valuation_claims(FUND, PEERS))
        assert d["Trailing P/E vs peer median of 35.24: premium (+) or discount (−)"].value == pytest.approx(
            28 / 35.24 - 1
        )
        assert d["EV/EBITDA vs peer median of 20.00: premium (+) or discount (−)"].value == pytest.approx(0.25)

    def test_gross_margin_gap_to_peers_in_points(self) -> None:
        d = by_description(rd.valuation_claims(FUND, PEERS))
        gap = d["Gross margin vs peer median of 40.00%"]
        assert gap.value == pytest.approx(0.22)
        assert gap.unit == "percentage_points"

    def test_implied_growth_from_forward_pe(self) -> None:
        d = by_description(rd.valuation_claims(FUND, PEERS))
        assert d["Earnings growth implied by forward vs trailing P/E"].value == pytest.approx(28 / 26 - 1)

    def test_without_peers_only_the_own_comparison_remains(self) -> None:
        d = by_description(rd.valuation_claims(FUND, None))
        assert list(d) == ["Earnings growth implied by forward vs trailing P/E"]

    def test_negative_earnings_skip_pe_comparisons(self) -> None:
        d = by_description(rd.valuation_claims({**FUND, "trailing_pe": c(None), "forward_pe": c(-12.0)}, PEERS))
        assert not any(k.startswith("Trailing P/E") for k in d)
        assert not any(k.startswith("Earnings growth implied") for k in d)


def eps_history(values: list[float]) -> list[ClaimHistoryPoint]:
    return [ClaimHistoryPoint(period=f"Q{i}", value=v) for i, v in enumerate(values)]


class TestEarnings:
    def _earnings(self, eps: list[float], surprises: list[float]) -> dict[str, Claim]:
        src = Source(tool="yfinance.earnings", fetched_at=FETCHED)
        return {
            "eps_actual": Claim(description="EPS", value=eps[-1], source=src, history=eps_history(eps)),
            "eps_surprise_pct": Claim(description="S", value=surprises[-1], source=src, history=eps_history(surprises)),
        }

    def test_ttm_eps_growth_and_year_over_year(self) -> None:
        e = self._earnings([0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.6, 0.6], [1.0] * 8)
        d = by_description(rd.earnings_claims(e))
        assert d["EPS growth, last 4 quarters vs the 4 before"].value == pytest.approx(0.2)
        assert d["EPS growth, Q3 → Q7"].value == pytest.approx(0.2)

    def test_beat_streak_counts_back_from_the_latest_quarter(self) -> None:
        e = self._earnings([0.5] * 6, [2.0, -1.0, 3.0, 1.0, 0.5, 4.0])
        d = by_description(rd.earnings_claims(e))
        assert d["Consecutive quarters beating consensus (latest backwards)"].value == 4

    def test_prior_year_loss_skips_growth(self) -> None:
        e = self._earnings([-0.5, -0.4, -0.3, -0.2, 0.1, 0.2, 0.3, 0.4], [1.0] * 8)
        d = by_description(rd.earnings_claims(e))
        assert not any(k.startswith("EPS growth") for k in d)


def test_missing_tool_output_yields_nothing() -> None:
    for fn in (rd.quality_claims, rd.capital_allocation_claims, rd.earnings_claims):
        assert fn(None) == []
        assert fn({}) == []
    assert rd.valuation_claims(None, None) == []


class TestBanks:
    """A bank's FCF, capex, gross margin and net debt describe its loan book
    and deposit funding; the first eval read JPM's "−42% FCF margin" as
    distress."""

    BANK = {**FUND, "sector_tag": c("banks")}

    def test_skips_cash_flow_capex_and_debt_comparisons(self) -> None:
        derived = (
            rd.quality_claims(self.BANK)
            + rd.capital_allocation_claims(self.BANK)
            + rd.valuation_claims(self.BANK, PEERS)
        )
        text = " ".join(cl.description for cl in derived).lower()
        for word in ("free cash flow", "capex", "net debt", "gross margin"):
            assert word not in text, word

    def test_keeps_the_comparisons_that_still_apply(self) -> None:
        d = by_description(
            rd.quality_claims(self.BANK)
            + rd.capital_allocation_claims(self.BANK)
            + rd.valuation_claims(self.BANK, PEERS)
        )
        assert "Operating margin change, 2025-Q3 → 2026-Q3" in d
        assert "Dividend payout ratio (forward dividend ÷ trailing earnings)" in d
        assert "Shareholder yield (forward dividend + latest-year buybacks)" in d
        assert "Trailing P/E vs peer median of 35.24: premium (+) or discount (−)" in d


def test_latest_surprise_against_the_long_run_average() -> None:
    src = Source(tool="yfinance.earnings", fetched_at=FETCHED)
    e = {
        "eps_surprise_pct": Claim(description="S", value=5.78, source=src),
        "last_20q.avg_surprise_pct": Claim(description="A", value=4.41, source=src),
    }
    d = by_description(rd.earnings_claims(e))
    gap = d["Latest EPS surprise minus the 20-quarter average surprise"]
    assert gap.value == pytest.approx(0.0137)
    assert gap.unit == "percentage_points"  # prints "+1.37 pts": above, not below
