"""
Tests for ``app.services.research_tool_registry``.

The registry is a pure-data declaration of:
  1. Which sections appear in each focus mode.
  2. Which tools each section needs.
  3. How to extract that section's Claims from a tool-output dict.

No I/O, no LLM, no async — every test is a fast unit check.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.research import Claim, Source
from app.schemas.ten_k import Extracted10KSection, Risk10KDiff
from app.services.research_tool_registry import (
    SECTIONS_BY_FOCUS,
    Focus,
    tools_for,
)


# ── Claim-builder helpers ─────────────────────────────────────────────


def _claim(description: str, value: object) -> Claim:
    return Claim(
        description=description,
        value=value,  # type: ignore[arg-type]
        source=Source(tool="test.tool", fetched_at=datetime.now(UTC)),
    )


def _make_fundamentals_output() -> dict[str, Claim]:
    """All 15 fundamentals keys, every value populated."""
    return {
        # Valuation
        "trailing_pe": _claim("Trailing P/E", 28.5),
        "forward_pe": _claim("Forward P/E", 25.0),
        "p_s": _claim("P/S", 7.2),
        "ev_ebitda": _claim("EV/EBITDA", 21.0),
        "peg": _claim("PEG", 2.1),
        # Quality
        "roe": _claim("ROE", 0.45),
        "gross_margin": _claim("Gross margin", 0.46),
        "profit_margin": _claim("Profit margin", 0.25),
        "gross_margin_trend_1y": _claim("Gross-margin YoY trend", 0.005),
        # Capital allocation
        "dividend_yield": _claim("Dividend yield", 0.005),
        "short_ratio": _claim("Short ratio", 1.2),
        "shares_short": _claim("Shares short", 100_000_000),
        "market_cap": _claim("Market cap", 3_500_000_000_000),
        "buyback_yield": _claim("Buyback yield", 0.04),
        "sbc_pct_revenue": _claim("SBC % revenue", 0.07),
    }


# ── Focus enum + section catalog ──────────────────────────────────────


def test_focus_full_has_seven_sections() -> None:
    """Catalog: Valuation, Quality, Capital Allocation, Earnings, Peers,
    Risk Factors, Macro."""
    titles = [s.title for s in SECTIONS_BY_FOCUS[Focus.FULL]]
    assert titles == [
        "Valuation",
        "Quality",
        "Capital Allocation",
        "Earnings",
        "Peers",
        "Risk Factors",
        "Macro",
    ]


def test_focus_earnings_has_three_sections() -> None:
    """Catalog: Earnings, Valuation, Risk Factors — earnings-event lens."""
    titles = [s.title for s in SECTIONS_BY_FOCUS[Focus.EARNINGS]]
    assert titles == ["Earnings", "Valuation", "Risk Factors"]


def test_every_focus_section_declares_at_least_one_tool() -> None:
    """A section without an upstream tool is dead code; guard against."""
    for focus, sections in SECTIONS_BY_FOCUS.items():
        for spec in sections:
            assert spec.tools_required, (
                f"{focus.value}/{spec.title} declares no required tools"
            )


# ── tools_for: which tools to invoke per focus ────────────────────────


def test_tools_for_full_lists_every_required_tool() -> None:
    """Full mode invokes the union of tools across all 7 sections."""
    assert tools_for(Focus.FULL) == {
        "fetch_fundamentals",
        "fetch_earnings",
        "fetch_peers",
        "fetch_macro",
        "extract_10k_risks_diff",
        "extract_10k_business",
    }


def test_tools_for_earnings_drops_peers_macro_and_quality_only_tools() -> None:
    """Earnings focus is narrower; peers + macro are not invoked."""
    tools = tools_for(Focus.EARNINGS)
    assert "fetch_peers" not in tools
    assert "fetch_macro" not in tools
    # Still needs fundamentals (Valuation) + earnings + 10-K
    assert tools >= {
        "fetch_fundamentals",
        "fetch_earnings",
        "extract_10k_risks_diff",
        "extract_10k_business",
    }


def test_tools_for_returns_a_set_not_a_list() -> None:
    """Deduplication matters: fundamentals feeds 3 sections in full mode
    but the orchestrator should only invoke it once."""
    tools = tools_for(Focus.FULL)
    assert isinstance(tools, set)
    # Spot-check: fundamentals appears once in the output even though
    # Valuation, Quality, and Capital Allocation each require it.
    assert sum(1 for t in tools if t == "fetch_fundamentals") == 1


# ── Section builders: tool outputs → Claims ───────────────────────────


def _spec(focus: Focus, title: str):
    return next(s for s in SECTIONS_BY_FOCUS[focus] if s.title == title)


def test_valuation_builder_takes_only_valuation_keys() -> None:
    fundamentals = _make_fundamentals_output()
    outputs = {"fetch_fundamentals": fundamentals}

    claims = _spec(Focus.FULL, "Valuation").builder(outputs)
    descriptions = {c.description for c in claims}

    # 5 valuation metrics
    assert len(claims) == 5
    assert {"Trailing P/E", "Forward P/E", "P/S", "EV/EBITDA", "PEG"} <= descriptions
    # Quality / capital-alloc keys are NOT in the Valuation section.
    assert "ROE" not in descriptions
    assert "Dividend yield" not in descriptions


def test_quality_builder_takes_only_quality_keys() -> None:
    fundamentals = _make_fundamentals_output()
    outputs = {"fetch_fundamentals": fundamentals}

    claims = _spec(Focus.FULL, "Quality").builder(outputs)
    descriptions = {c.description for c in claims}

    assert {"ROE", "Gross margin", "Profit margin", "Gross-margin YoY trend"} <= descriptions
    assert "Trailing P/E" not in descriptions
    assert "Market cap" not in descriptions


def test_capital_allocation_builder_takes_only_cap_alloc_keys() -> None:
    fundamentals = _make_fundamentals_output()
    outputs = {"fetch_fundamentals": fundamentals}

    claims = _spec(Focus.FULL, "Capital Allocation").builder(outputs)
    descriptions = {c.description for c in claims}

    expected = {
        "Dividend yield",
        "Buyback yield",
        "SBC % revenue",
        "Short ratio",
        "Shares short",
        "Market cap",
    }
    assert expected <= descriptions
    assert "Trailing P/E" not in descriptions


def test_section_builders_return_empty_when_tool_output_missing() -> None:
    """A section must not raise when its required tool failed upstream.

    The orchestrator passes ``{}`` for a tool that errored out; the
    builder returns ``[]`` and confidence-stamping renders the section
    as LOW with an empty claims list.
    """
    for spec in SECTIONS_BY_FOCUS[Focus.FULL]:
        assert spec.builder({}) == []


def test_earnings_builder_returns_all_earnings_claims() -> None:
    """Earnings section takes every claim the tool emitted, not a subset."""
    earnings = {
        f"q{i}.eps_actual": _claim(f"Q{i} EPS actual", 1.0 + i * 0.1) for i in range(1, 5)
    }
    outputs = {"fetch_earnings": earnings}

    claims = _spec(Focus.FULL, "Earnings").builder(outputs)
    assert len(claims) == 4


def test_peers_builder_returns_all_peer_claims() -> None:
    peers = {
        "sector": _claim("Sector", "megacap_tech"),
        "peers_list": _claim("Peers", "MSFT, GOOGL"),
        "MSFT.trailing_pe": _claim("MSFT P/E", 26.6),
    }
    outputs = {"fetch_peers": peers}

    claims = _spec(Focus.FULL, "Peers").builder(outputs)
    assert len(claims) == 3


def test_macro_builder_returns_all_macro_claims() -> None:
    macro = {
        "sector": _claim("Sector", "megacap_tech"),
        "DGS10.value": _claim("10Y Treasury yield", 4.32),
    }
    outputs = {"fetch_macro": macro}

    claims = _spec(Focus.FULL, "Macro").builder(outputs)
    assert len(claims) == 2


# ── Risk Factors: special non-dict[str, Claim] adapter ────────────────


def _mk_extracted_section(*, accession: str, char_count: int) -> Extracted10KSection:
    return Extracted10KSection(
        symbol="AAPL",
        accession=accession,
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
        section_id="Item 1A",
        section_title="Risk Factors",
        text="x" * char_count,
        char_count=char_count,
        primary_doc_url="https://www.sec.gov/foo.htm",
    )


def _mk_risks_diff() -> Risk10KDiff:
    return Risk10KDiff(
        symbol="AAPL",
        current=_mk_extracted_section(
            accession="0000320193-25-000079", char_count=68_000
        ),
        prior=_mk_extracted_section(
            accession="0000320193-24-000123", char_count=68_700
        ),
        added_paragraphs=["new risk 1", "new risk 2"],
        removed_paragraphs=["old risk"],
        kept_paragraph_count=83,
        char_delta=-700,
    )


def test_risk_factors_builder_converts_diff_to_claims() -> None:
    """Risk10KDiff → list[Claim] with counts + char delta."""
    diff = _mk_risks_diff()
    outputs = {"extract_10k_risks_diff": diff, "extract_10k_business": None}

    claims = _spec(Focus.FULL, "Risk Factors").builder(outputs)
    descriptions = {c.description: c.value for c in claims}

    assert descriptions.get("Newly added risk paragraphs vs prior 10-K") == 2
    assert descriptions.get("Risk paragraphs dropped vs prior 10-K") == 1
    assert descriptions.get("Risk paragraphs kept (carryover)") == 83
    assert descriptions.get("Item 1A char delta vs prior 10-K") == -700


def test_risk_factors_builder_includes_business_section_when_present() -> None:
    """Business section adds its own claim (length, accession)."""
    diff = _mk_risks_diff()
    business = _mk_extracted_section(
        accession="0000320193-25-000079", char_count=16_000
    )
    outputs = {
        "extract_10k_risks_diff": diff,
        "extract_10k_business": business,
    }

    claims = _spec(Focus.FULL, "Risk Factors").builder(outputs)
    descriptions = {c.description: c.value for c in claims}

    assert descriptions.get("Business section length (chars)") == 16_000


def test_risk_factors_builder_handles_none_diff() -> None:
    """When the diff tool failed (None), section degrades gracefully."""
    outputs = {"extract_10k_risks_diff": None, "extract_10k_business": None}
    claims = _spec(Focus.FULL, "Risk Factors").builder(outputs)
    assert claims == []


def test_risk_factors_builder_returns_business_only_when_diff_unavailable() -> None:
    """Diff is None but business section was extracted: still emit business claim."""
    business = _mk_extracted_section(
        accession="0000320193-25-000079", char_count=16_000
    )
    outputs = {
        "extract_10k_risks_diff": None,
        "extract_10k_business": business,
    }

    claims = _spec(Focus.FULL, "Risk Factors").builder(outputs)
    descriptions = {c.description for c in claims}
    assert "Business section length (chars)" in descriptions
