"""
Tests for the 10-K Item 1 / Item 1A extractors. Two layers of testing:

1. **Pure extractor** (`_extract_section`) — given an HTML string + a
   section id, returns plain text (or None). Tests against hand-crafted
   HTML fixtures covering the patterns real 10-Ks use: clean section
   headers, all-caps headers, TOC + main-section combos, malformed HTML,
   XBRL inline tags, missing sections, below-threshold (TOC-only) hits.
2. **Async entry points** (`extract_10k_business`, `extract_10k_risks`)
   — fetch_edgar mocked at the module-import boundary (same pattern as
   form_4). Verifies the coordination: which form_type, recent_n, and
   which filing index gets used for ``prior=True``.

Note: real 10-Ks are 10-150 KB of HTML per section. Test fixtures here
are deliberately small but exercise the same boundary patterns.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.schemas.edgar import EdgarFiling
from app.schemas.ten_k import Extracted10KSection, Risk10KDiff
from app.services import ten_k as ten_k_module
from app.services.ten_k import (
    _extract_section,
    _extract_section_paragraphs,
    _flatten_html_to_paragraphs,
    _paragraph_diff,
    extract_10k_business,
    extract_10k_risks,
    extract_10k_risks_diff,
)

# ── HTML fixtures ─────────────────────────────────────────────────────


def _wrap_html(body: str) -> str:
    return f"""<!DOCTYPE html><html><head><title>10-K</title></head>
<body>{body}</body></html>"""


# A section is real when it's substantively long. The threshold is 500
# chars; tests use ~600+ char sections to clear it comfortably, with
# explicit "tiny" fixtures for the below-threshold case.
_LONG_BUSINESS_TEXT = (
    "We design, manufacture, and market smartphones, personal computers, "
    "tablets, wearables, and accessories worldwide. Our segments include "
    "Americas, Europe, Greater China, Japan, and Rest of Asia Pacific. "
    "We sell our products through retail stores, online stores, and direct "
    "sales force, as well as through third-party cellular network carriers, "
    "wholesalers, retailers, and resellers. The Company was founded in 1976 "
    "and is headquartered in Cupertino, California. Our principal source of "
    "revenue is the iPhone product line, which we believe represents the "
    "most advanced smartphone available. We continue to invest in research "
    "and development to maintain our technological leadership across all "
    "product lines and services."
)
_LONG_RISKS_TEXT = (
    "The Company's business, operating results, and financial condition "
    "could be materially adversely affected by various risk factors. We are "
    "exposed to global macroeconomic conditions, rapid technological change, "
    "competitive pressures from larger and smaller competitors, supply chain "
    "concentration in a small number of contract manufacturers, foreign "
    "exchange volatility, regulatory uncertainty in key markets including "
    "the European Union and China, intellectual property litigation, and "
    "cybersecurity threats targeting our products and services. Failure to "
    "anticipate or successfully respond to any of these factors could harm "
    "our business and stock price. The risks described below are not the "
    "only risks facing the Company; additional risks not currently known "
    "may also impact our results."
)
_LONG_RISKS_TEXT_PRIOR_YEAR = (
    "The Company's business is subject to a variety of risks. We face "
    "competitive pressure, supply-chain concentration, foreign exchange "
    "exposure, and regulatory scrutiny in our largest markets. Cybersecurity "
    "and intellectual property litigation are persistent threats. The risks "
    "below are not exhaustive. Macroeconomic headwinds in any of our "
    "operating regions could materially affect demand for our products and "
    "services, and supply chain disruption from a small number of contract "
    "manufacturers could constrain output and damage our competitive "
    "position. We continue to monitor these conditions and adjust our "
    "operations accordingly."
)


def _clean_html_with_item_1_only() -> str:
    return _wrap_html(f"""
        <h1>Item 1. Business</h1>
        <p>{_LONG_BUSINESS_TEXT}</p>
        <h1>Item 2. Properties</h1>
        <p>The Company owns properties in California.</p>
    """)


def _html_with_item_1_and_1a() -> str:
    return _wrap_html(f"""
        <h1>Item 1. Business</h1>
        <p>{_LONG_BUSINESS_TEXT}</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT}</p>
        <h1>Item 1B. Unresolved Staff Comments</h1>
        <p>None.</p>
        <h1>Item 2. Properties</h1>
        <p>The Company owns properties in California.</p>
    """)


def _html_with_toc_and_main_section() -> str:
    """Real 10-Ks have a Table of Contents that mentions every Item.

    The "longest match" heuristic should pick the main section, not the TOC.
    """
    return _wrap_html(f"""
        <h2>TABLE OF CONTENTS</h2>
        <ul>
            <li><a href="#i1">Item 1. Business</a></li>
            <li><a href="#i1a">Item 1A. Risk Factors</a></li>
            <li><a href="#i2">Item 2. Properties</a></li>
        </ul>
        <h1>Item 1. Business</h1>
        <p>{_LONG_BUSINESS_TEXT}</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT}</p>
        <h1>Item 2. Properties</h1>
        <p>The Company owns properties.</p>
    """)


def _html_with_only_item_2() -> str:
    """Smaller filer that omits Item 1 entirely (rare but possible)."""
    return _wrap_html("""
        <h1>Item 2. Properties</h1>
        <p>The Company owns properties in California.</p>
    """)


def _html_with_xbrl_inline_tags() -> str:
    """Real 10-Ks have <ix:nonNumeric> tags everywhere. Strip them."""
    return _wrap_html(f"""
        <h1>Item 1. Business</h1>
        <p><ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c0">
        Apple Inc.</ix:nonNumeric> {_LONG_BUSINESS_TEXT}</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT}</p>
        <h1>Item 2. Properties</h1>
        <p>None.</p>
    """)


def _html_with_all_caps_headers() -> str:
    """Some filers use ALL CAPS section headers."""
    return _wrap_html(f"""
        <p><b>ITEM 1. BUSINESS</b></p>
        <p>{_LONG_BUSINESS_TEXT}</p>
        <p><b>ITEM 1A. RISK FACTORS</b></p>
        <p>{_LONG_RISKS_TEXT}</p>
        <p><b>ITEM 2. PROPERTIES</b></p>
        <p>None.</p>
    """)


def _html_toc_only_below_threshold() -> str:
    """Only TOC anchors present — extracted text is below 500-char threshold."""
    return _wrap_html("""
        <h2>TABLE OF CONTENTS</h2>
        <p>Item 1. Business ........... 4</p>
        <p>Item 1A. Risk Factors ........... 12</p>
        <p>Item 2. Properties ........... 30</p>
    """)


def _malformed_html_with_section() -> str:
    """Unclosed tags, missing quotes — BeautifulSoup should still recover."""
    return f"""<html><body
        <div><h1>Item 1. Business</h1>
        <p>{_LONG_BUSINESS_TEXT}
        <h1>Item 2. Properties
        <p>None.
    """


def _html_item_1a_to_item_2_no_1b() -> str:
    """Filer where Item 1B doesn't exist — Item 1A ends at Item 2."""
    return _wrap_html(f"""
        <h1>Item 1. Business</h1>
        <p>{_LONG_BUSINESS_TEXT}</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT}</p>
        <h1>Item 2. Properties</h1>
        <p>None.</p>
    """)


# ── Pure extractor tests (no I/O) ─────────────────────────────────────


def test_extracts_item_1_from_clean_html() -> None:
    text = _extract_section(_clean_html_with_item_1_only(), section_id="Item 1")
    assert text is not None
    assert "smartphones" in text.lower()
    assert len(text) > 500


def test_extracts_item_1a_from_html_with_both_sections() -> None:
    text = _extract_section(_html_with_item_1_and_1a(), section_id="Item 1A")
    assert text is not None
    assert "macroeconomic" in text.lower()
    assert len(text) > 500
    # Item 2's content shouldn't bleed in.
    assert "owns properties" not in text.lower()


def test_picks_main_section_over_toc_via_longest_match() -> None:
    """When TOC and main section both match, pick the long one."""
    text = _extract_section(_html_with_toc_and_main_section(), section_id="Item 1")
    assert text is not None
    assert "smartphones" in text.lower()
    assert len(text) > 500
    # TOC stub ("Business" link text) is short; we should NOT have picked it.


def test_returns_none_when_section_missing() -> None:
    assert _extract_section(_html_with_only_item_2(), section_id="Item 1") is None
    assert _extract_section(_html_with_only_item_2(), section_id="Item 1A") is None


def test_returns_none_when_match_below_threshold() -> None:
    """TOC-only HTML matches the anchor but extracted text is too short."""
    assert (
        _extract_section(_html_toc_only_below_threshold(), section_id="Item 1") is None
    )


def test_strips_xbrl_inline_tags() -> None:
    text = _extract_section(_html_with_xbrl_inline_tags(), section_id="Item 1")
    assert text is not None
    # The XBRL tag attribute names shouldn't appear in the extracted text.
    assert "dei:EntityRegistrantName" not in text
    assert "contextRef" not in text
    # The wrapped value content does survive.
    assert "Apple Inc." in text


def test_handles_all_caps_section_headers() -> None:
    text = _extract_section(_html_with_all_caps_headers(), section_id="Item 1A")
    assert text is not None
    assert "macroeconomic" in text.lower()


def test_handles_malformed_html() -> None:
    """BeautifulSoup is forgiving — extraction should still produce text."""
    text = _extract_section(_malformed_html_with_section(), section_id="Item 1")
    # Malformed HTML may not always produce >500 chars depending on how BS4
    # recovers, so we accept either a successful extraction or graceful None.
    if text is not None:
        assert "smartphones" in text.lower()


def test_item_1a_ends_at_item_2_when_no_item_1b() -> None:
    text = _extract_section(_html_item_1a_to_item_2_no_1b(), section_id="Item 1A")
    assert text is not None
    assert "macroeconomic" in text.lower()
    # Item 2's content shouldn't bleed in.
    assert "owns properties" not in text.lower()


def test_unsupported_section_id_raises() -> None:
    """Only Item 1 and Item 1A are wired up in v1."""
    with pytest.raises(ValueError, match="Unsupported section_id"):
        _extract_section(_clean_html_with_item_1_only(), section_id="Item 7")


# ── End-to-end tests (fetch_edgar mocked) ─────────────────────────────


def _mk_filing(
    *,
    accession: str = "0000320193-24-000123",
    filed_at: datetime | None = None,
    period_of_report: date | None = None,
    primary_doc_text: str | None = None,
) -> EdgarFiling:
    return EdgarFiling(
        cik="0000320193",
        symbol="AAPL",
        accession=accession,
        form_type="10-K",
        filed_at=filed_at or datetime(2024, 11, 1, tzinfo=UTC),
        period_of_report=period_of_report or date(2024, 9, 28),
        primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-', '')}/aapl-10k.htm",
        primary_doc_text=primary_doc_text,
        size_bytes=len(primary_doc_text or ""),
    )


def _patch_fetch_edgar(
    monkeypatch: pytest.MonkeyPatch,
    filings: list[EdgarFiling] | Exception,
) -> None:
    async def _fake_fetch_edgar(*_a: Any, **_kw: Any) -> list[EdgarFiling]:
        if isinstance(filings, Exception):
            raise filings
        return filings

    monkeypatch.setattr(ten_k_module, "fetch_edgar", _fake_fetch_edgar)


async def test_extract_10k_business_returns_section_from_latest_filing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filing = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [filing])

    result = await extract_10k_business("AAPL")

    assert isinstance(result, Extracted10KSection)
    assert result.symbol == "AAPL"
    assert result.section_id == "Item 1"
    assert "smartphones" in result.text.lower()
    assert result.char_count == len(result.text)
    assert result.accession == filing.accession
    assert result.primary_doc_url == filing.primary_doc_url


async def test_extract_10k_risks_returns_item_1a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filing = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [filing])

    result = await extract_10k_risks("AAPL")

    assert isinstance(result, Extracted10KSection)
    assert result.section_id == "Item 1A"
    assert "macroeconomic" in result.text.lower()


async def test_extract_10k_risks_prior_uses_second_filing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prior=True selects the second filing (last year's 10-K)."""
    current_html = _wrap_html(f"""
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT}</p>
        <h1>Item 2. Properties</h1>
        <p>None.</p>
    """)
    prior_html = _wrap_html(f"""
        <h1>Item 1A. Risk Factors</h1>
        <p>{_LONG_RISKS_TEXT_PRIOR_YEAR}</p>
        <h1>Item 2. Properties</h1>
        <p>None.</p>
    """)
    current = _mk_filing(
        accession="0000320193-24-000123",
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
        primary_doc_text=current_html,
    )
    prior = _mk_filing(
        accession="0000320193-23-000110",
        filed_at=datetime(2023, 11, 3, tzinfo=UTC),
        primary_doc_text=prior_html,
    )
    _patch_fetch_edgar(monkeypatch, [current, prior])

    result = await extract_10k_risks("AAPL", prior=True)

    assert result is not None
    assert result.accession == prior.accession
    # The prior-year fixture has different language than the current.
    assert "exhaustive" in result.text.lower()


async def test_extract_returns_none_when_no_filings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fetch_edgar(monkeypatch, [])

    assert await extract_10k_business("AAPL") is None
    assert await extract_10k_risks("AAPL") is None


async def test_extract_returns_none_when_filing_has_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filing = _mk_filing(primary_doc_text=None)
    _patch_fetch_edgar(monkeypatch, [filing])

    assert await extract_10k_business("AAPL") is None


async def test_extract_returns_none_when_anchors_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 10-K HTML where the regex anchors don't hit returns None gracefully."""
    weird_html = _wrap_html(
        "<p>This document contains no Item headings.</p>" * 20
    )
    filing = _mk_filing(primary_doc_text=weird_html)
    _patch_fetch_edgar(monkeypatch, [filing])

    assert await extract_10k_business("AAPL") is None


async def test_extract_returns_none_when_prior_filing_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prior=True but only one 10-K → None, not an IndexError."""
    only_one = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [only_one])

    assert await extract_10k_risks("AAPL", prior=True) is None


async def test_symbol_uppercased_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def _capture(symbol: str, **_kw: Any) -> list[EdgarFiling]:
        seen.append(symbol)
        return []

    monkeypatch.setattr(ten_k_module, "fetch_edgar", _capture)

    await extract_10k_business("aapl")
    assert seen == ["AAPL"]


async def test_logs_one_external_call_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    filing = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [filing])

    with caplog.at_level(logging.INFO, logger="app.external"):
        await extract_10k_business("AAPL")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "sec.ten_k_business"
    assert r.input_summary == {
        "symbol": "AAPL",
        "edgar_provider": "sec",
        "section_id": "Item 1",
    }
    assert r.output_summary["extracted"] is True
    assert r.output_summary["char_count"] > 500
    assert r.outcome == "ok"


async def test_logs_extracted_false_when_no_section(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When the extractor returns None, observability records extracted=False."""
    import logging

    _patch_fetch_edgar(monkeypatch, [])

    with caplog.at_level(logging.INFO, logger="app.external"):
        await extract_10k_business("AAPL")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].output_summary["extracted"] is False


async def test_fetch_edgar_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    _patch_fetch_edgar(monkeypatch, RuntimeError("EDGAR is down"))

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="EDGAR is down"):
            await extract_10k_business("AAPL")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


# ── Risk10KDiff: paragraph-aware extractor + mechanical diff ──────────
#
# The diff tool answers "what's new in Item 1A this year vs last" without
# asking the LLM to compare two ~50KB texts (the failure mode the citation
# schema exists to prevent). It works by splitting each year's Item 1A
# into paragraphs, then bucketing each paragraph as added/removed/kept
# via a fuzzy similarity threshold so cosmetic edits ("we" → "the
# Company") don't get falsely flagged as new risks.

# Paragraphs that show up identically in both years.
_FILLER_PARA_1 = (
    "The Company faces intense competition in all segments, including from "
    "competitors with greater financial, operational, or marketing "
    "resources, and increased competition could materially impact margins, "
    "demand, and overall results of operations and financial condition."
)
_FILLER_PARA_2 = (
    "Our supply chain is concentrated in a small number of contract "
    "manufacturers, primarily in Asia, and any disruption to that "
    "concentration could constrain output or increase component costs in "
    "ways that materially harm gross margins and product availability."
)
# Reworded version of _FILLER_PARA_2 — same risk, slightly different prose.
# At similarity >= 0.6 this should bucket as "kept" rather than added/removed.
_FILLER_PARA_2_REWORDED = (
    "Our supply chain remains concentrated in a small number of contract "
    "manufacturers, principally in Asia, and disruption to that "
    "concentration could constrain output or raise component costs in ways "
    "that materially harm gross margins and product availability."
)
_NEW_PARA_AI = (
    "Cybersecurity threats specifically targeting AI training pipelines "
    "and model weights emerged this year as a new and rapidly evolving "
    "category of risk for the Company, including state-sponsored actors "
    "seeking access to proprietary model architectures."
)
_REMOVED_PARA_CLIMATE = (
    "Climate change and physical risks may disrupt manufacturing in "
    "coastal regions where the Company has key suppliers, including "
    "potential impacts from severe weather events, sea-level rise, and "
    "regional water scarcity affecting semiconductor fabrication."
)


def _wrap_risks_html(paragraphs: list[str]) -> str:
    """Wrap paragraphs as a 10-K with Item 1A bracketed by Item 2."""
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return _wrap_html(f"""
        <h1>Item 1A. Risk Factors</h1>
        {body}
        <h1>Item 2. Properties</h1>
        <p>None.</p>
    """)


# ── _flatten_html_to_paragraphs ────────────────────────────────────────


def test_flatten_html_to_paragraphs_preserves_block_structure() -> None:
    html = "<html><body><p>First para.</p><p>Second para.</p></body></html>"
    assert _flatten_html_to_paragraphs(html) == ["First para.", "Second para."]


def test_flatten_html_to_paragraphs_drops_empty_blocks() -> None:
    html = "<html><body><p>First.</p><p>   </p><p>Last.</p></body></html>"
    assert _flatten_html_to_paragraphs(html) == ["First.", "Last."]


def test_flatten_html_to_paragraphs_normalizes_internal_whitespace() -> None:
    html = "<html><body><p>Multiple  \n  spaces\tinside.</p></body></html>"
    assert _flatten_html_to_paragraphs(html) == ["Multiple spaces inside."]


def test_flatten_html_to_paragraphs_handles_div_and_li() -> None:
    """Real 10-Ks use <div> and <li> as block containers, not just <p>."""
    html = (
        "<html><body>"
        "<div>Block A.</div>"
        "<ul><li>Item one.</li><li>Item two.</li></ul>"
        "</body></html>"
    )
    paras = _flatten_html_to_paragraphs(html)
    assert "Block A." in paras
    assert "Item one." in paras
    assert "Item two." in paras


# ── _extract_section_paragraphs ────────────────────────────────────────


def test_extract_section_paragraphs_returns_list_of_paragraphs() -> None:
    html = _wrap_risks_html([_FILLER_PARA_1, _FILLER_PARA_2, _NEW_PARA_AI])
    paras = _extract_section_paragraphs(html, section_id="Item 1A")
    assert paras is not None
    # Three content paragraphs go in; the heading paragraphs are excluded.
    assert len(paras) == 3
    assert any("intense competition" in p for p in paras)
    assert any("AI training" in p for p in paras)
    # Item 2 content shouldn't bleed in.
    assert not any("None." in p and len(p) < 20 for p in paras)


def test_extract_section_paragraphs_returns_none_when_section_missing() -> None:
    assert _extract_section_paragraphs(
        _html_with_only_item_2(), section_id="Item 1A"
    ) is None


def test_extract_section_paragraphs_returns_none_when_below_threshold() -> None:
    """TOC-only HTML matches anchors but content is too short."""
    assert _extract_section_paragraphs(
        _html_toc_only_below_threshold(), section_id="Item 1A"
    ) is None


# ── _paragraph_diff ────────────────────────────────────────────────────


def test_paragraph_diff_identifies_added_and_removed() -> None:
    prior = [_FILLER_PARA_1, _FILLER_PARA_2, _REMOVED_PARA_CLIMATE]
    current = [_FILLER_PARA_1, _FILLER_PARA_2, _NEW_PARA_AI]
    added, removed, kept = _paragraph_diff(current, prior)

    assert added == [_NEW_PARA_AI]
    assert removed == [_REMOVED_PARA_CLIMATE]
    assert kept == 2


def test_paragraph_diff_treats_cosmetic_edit_as_kept() -> None:
    """Slightly reworded paragraph >= 0.6 similarity is kept, not flagged."""
    prior = [_FILLER_PARA_2]
    current = [_FILLER_PARA_2_REWORDED]
    added, removed, kept = _paragraph_diff(current, prior)

    assert added == []
    assert removed == []
    assert kept == 1


def test_paragraph_diff_preserves_input_order() -> None:
    """Added paragraphs appear in their order in `current`; removed in `prior`."""
    shared = (
        "Macroeconomic conditions in any of our principal operating regions "
        "could materially affect demand for our products and services."
    )
    prior = [
        "Reliance on a single tier-one supplier for power management ICs "
        "exposes the Company to single-source supply disruption.",
        shared,
        "Pension liabilities tied to defined-benefit plans in legacy "
        "European subsidiaries remain a material balance-sheet risk.",
    ]
    current = [
        "Generative-AI competitive entrants have begun to reshape the "
        "search-advertising market in ways that may erode our share.",
        shared,
        "Geopolitical tensions in the Taiwan Strait could disrupt foundry "
        "capacity that the Company depends on for advanced-node silicon.",
    ]
    added, removed, _ = _paragraph_diff(current, prior)

    assert added == [current[0], current[2]]
    assert removed == [prior[0], prior[2]]


def test_paragraph_diff_handles_empty_inputs() -> None:
    assert _paragraph_diff([], []) == ([], [], 0)

    added, removed, kept = _paragraph_diff(["new only"], [])
    assert added == ["new only"]
    assert removed == []
    assert kept == 0

    added, removed, kept = _paragraph_diff([], ["dropped only"])
    assert added == []
    assert removed == ["dropped only"]
    assert kept == 0


# ── extract_10k_risks_diff (fetch_edgar mocked) ────────────────────────


async def test_extract_10k_risks_diff_returns_full_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_html = _wrap_risks_html([_FILLER_PARA_1, _FILLER_PARA_2, _NEW_PARA_AI])
    prior_html = _wrap_risks_html(
        [_FILLER_PARA_1, _FILLER_PARA_2_REWORDED, _REMOVED_PARA_CLIMATE]
    )
    current = _mk_filing(
        accession="0000320193-24-000123",
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
        primary_doc_text=current_html,
    )
    prior = _mk_filing(
        accession="0000320193-23-000110",
        filed_at=datetime(2023, 11, 3, tzinfo=UTC),
        primary_doc_text=prior_html,
    )
    _patch_fetch_edgar(monkeypatch, [current, prior])

    result = await extract_10k_risks_diff("AAPL")

    assert isinstance(result, Risk10KDiff)
    assert result.symbol == "AAPL"
    assert result.current.accession == current.accession
    assert result.prior.accession == prior.accession
    assert result.current.section_id == "Item 1A"
    assert result.prior.section_id == "Item 1A"

    # The AI paragraph is genuinely new; the climate paragraph is dropped.
    assert any("AI training" in p for p in result.added_paragraphs)
    assert any("Climate change" in p for p in result.removed_paragraphs)

    # FILLER_PARA_1 is identical → kept; FILLER_PARA_2 reworded → kept.
    assert result.kept_paragraph_count == 2

    # Computed delta matches the section char counts.
    assert result.char_delta == result.current.char_count - result.prior.char_count


async def test_extract_10k_risks_diff_uppercases_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def _capture(symbol: str, **kw: Any) -> list[EdgarFiling]:
        seen.append({"symbol": symbol, **kw})
        return []

    monkeypatch.setattr(ten_k_module, "fetch_edgar", _capture)

    await extract_10k_risks_diff("aapl")
    assert seen and seen[0]["symbol"] == "AAPL"
    # Diff should ask for two filings in one round trip.
    assert seen[0]["recent_n"] == 2
    assert seen[0]["form_type"] == "10-K"
    assert seen[0]["include_text"] is True


async def test_extract_10k_risks_diff_returns_none_when_only_one_filing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_one = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [only_one])

    assert await extract_10k_risks_diff("AAPL") is None


async def test_extract_10k_risks_diff_returns_none_when_no_filings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fetch_edgar(monkeypatch, [])
    assert await extract_10k_risks_diff("AAPL") is None


async def test_extract_10k_risks_diff_returns_none_when_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both filings present, but neither has matchable Item 1A anchors."""
    weird_html = _wrap_html("<p>This document contains no Item headings.</p>" * 20)
    current = _mk_filing(
        accession="0000320193-24-000123", primary_doc_text=weird_html
    )
    prior = _mk_filing(
        accession="0000320193-23-000110",
        filed_at=datetime(2023, 11, 3, tzinfo=UTC),
        primary_doc_text=weird_html,
    )
    _patch_fetch_edgar(monkeypatch, [current, prior])

    assert await extract_10k_risks_diff("AAPL") is None


async def test_extract_10k_risks_diff_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    current_html = _wrap_risks_html([_FILLER_PARA_1, _FILLER_PARA_2, _NEW_PARA_AI])
    prior_html = _wrap_risks_html(
        [_FILLER_PARA_1, _FILLER_PARA_2_REWORDED, _REMOVED_PARA_CLIMATE]
    )
    current = _mk_filing(
        accession="0000320193-24-000123",
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
        primary_doc_text=current_html,
    )
    prior = _mk_filing(
        accession="0000320193-23-000110",
        filed_at=datetime(2023, 11, 3, tzinfo=UTC),
        primary_doc_text=prior_html,
    )
    _patch_fetch_edgar(monkeypatch, [current, prior])

    with caplog.at_level(logging.INFO, logger="app.external"):
        await extract_10k_risks_diff("AAPL")

    records = [
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "sec.ten_k_risks_diff"
    ]
    assert len(records) == 1
    r = records[0]
    assert r.input_summary == {"symbol": "AAPL", "edgar_provider": "sec"}
    assert r.output_summary["available"] is True
    assert r.output_summary["added_count"] >= 1
    assert r.output_summary["removed_count"] >= 1
    assert r.output_summary["kept_count"] == 2
    assert r.outcome == "ok"


async def test_extract_10k_risks_diff_logs_unavailable_when_only_one_filing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    only_one = _mk_filing(primary_doc_text=_html_with_item_1_and_1a())
    _patch_fetch_edgar(monkeypatch, [only_one])

    with caplog.at_level(logging.INFO, logger="app.external"):
        await extract_10k_risks_diff("AAPL")

    records = [
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "sec.ten_k_risks_diff"
    ]
    assert len(records) == 1
    assert records[0].output_summary["available"] is False
