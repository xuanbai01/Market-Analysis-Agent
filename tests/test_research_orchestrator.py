"""
Tests for ``app.services.research_orchestrator.compose_research_report``.

Strategy: mock both layers the orchestrator depends on:

1. ``TOOL_DISPATCH`` — patched per-test to substitute a fake async
   callable for any of the six real tools. Lets us exercise the
   fan-out, error isolation, and per-section claim assembly without
   any network or DB.
2. ``llm.synth_call`` — patched to return a hand-crafted
   ``SectionSummaries`` so we never hit Anthropic in unit tests.
   Real-LLM exercise lives in ``tests/evals/test_golden.py``.

Both mocks are scoped per test via ``monkeypatch``; nothing leaks.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.research import (
    Claim,
    ClaimHistoryPoint,
    ClaimRef,
    Confidence,
    ResearchReport,
    Section,
    SectionSummaries,
    SectionSummary,
    Source,
    Thesis,
    ThesisPoint,
)
from app.schemas.ten_k import Extracted10KSection, Risk10KDiff
from app.services import research_orchestrator as orch_module
from app.services.research_orchestrator import (
    backfill_top_level_metadata,
    compose_research_report,
)
from app.services.research_tool_registry import Focus

# ── Tool output factories ─────────────────────────────────────────────


def _claim(description: str, value: object, *, age_days: int = 1) -> Claim:
    return Claim(
        description=description,
        value=value,  # type: ignore[arg-type]
        source=Source(
            tool="test.tool",
            fetched_at=datetime.now(UTC) - timedelta(days=age_days),
        ),
    )


def _fundamentals_output() -> dict[str, Claim]:
    """All 15 fundamentals claims, fully populated."""
    keys = [
        "trailing_pe", "forward_pe", "p_s", "ev_ebitda", "peg",
        "roe", "gross_margin", "profit_margin", "gross_margin_trend_1y",
        "dividend_yield", "buyback_yield", "sbc_pct_revenue",
        "short_ratio", "shares_short", "market_cap",
    ]
    return {k: _claim(k.replace("_", " ").title(), 1.5) for k in keys}


def _earnings_output() -> dict[str, Claim]:
    return {f"q{i}.eps_actual": _claim(f"Q{i} EPS", 1.0 + i * 0.1) for i in range(1, 5)}


def _peers_output() -> dict[str, Claim]:
    return {
        "sector": _claim("Sector", "megacap_tech"),
        "peers_list": _claim("Peers", "MSFT, GOOGL"),
        "MSFT.trailing_pe": _claim("MSFT P/E", 26.6),
    }


def _macro_output() -> dict[str, Claim]:
    return {
        "sector": _claim("Sector", "megacap_tech"),
        "DGS10.value": _claim("10Y yield", 4.32),
    }


def _risks_diff_output() -> Risk10KDiff:
    """Recent fixture so the freshness rule doesn't cap confidence at MEDIUM.

    Real 10-Ks are filed annually so Risk Factors *will* be MEDIUM in
    production — that's correct behavior. These tests are about
    orchestration mechanics; freshness rules are tested separately in
    test_research_confidence.py.
    """
    fresh = datetime.now(UTC) - timedelta(days=2)
    section = Extracted10KSection(
        symbol="AAPL",
        accession="0000320193-25-000079",
        filed_at=fresh,
        section_id="Item 1A",
        section_title="Risk Factors",
        text="x" * 68_000,
        char_count=68_000,
        primary_doc_url="https://www.sec.gov/foo",
    )
    prior = Extracted10KSection(
        symbol="AAPL",
        accession="0000320193-24-000123",
        filed_at=fresh - timedelta(days=365),
        section_id="Item 1A",
        section_title="Risk Factors",
        text="x" * 68_700,
        char_count=68_700,
        primary_doc_url="https://www.sec.gov/foo-prior",
    )
    return Risk10KDiff(
        symbol="AAPL",
        current=section,
        prior=prior,
        added_paragraphs=["new"],
        removed_paragraphs=[],
        kept_paragraph_count=80,
        char_delta=-700,
    )


def _business_output() -> Extracted10KSection:
    """Recent fixture; see _risks_diff_output rationale."""
    return Extracted10KSection(
        symbol="AAPL",
        accession="0000320193-25-000079",
        filed_at=datetime.now(UTC) - timedelta(days=2),
        section_id="Item 1",
        section_title="Business",
        text="b" * 16_000,
        char_count=16_000,
        primary_doc_url="https://www.sec.gov/foo",
    )


# ── Mock plumbing ─────────────────────────────────────────────────────


def _patch_tools(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
) -> None:
    """Replace tool callables in the dispatch dict.

    Each override value can be either an async callable (signature
    ``async def f(symbol) -> Any``) or a plain object that's wrapped
    so the dispatch invocation returns it. ``Exception`` instances are
    raised when the (mock) tool is called.

    Phase 4.4.A — ``fetch_business_info`` + ``fetch_news`` default to
    empty-dict stubs so existing tests that don't override them still
    work after the catalog grew. Tests asserting on the new tools'
    call sites supply explicit overrides.
    """
    new_dispatch: dict[str, Any] = {
        "fetch_business_info": _wrap_const({}),
        "fetch_news": _wrap_const({}),
        "fetch_annual_history": _wrap_const({}),
    }
    for name, override in overrides.items():
        if callable(override) and hasattr(override, "__await__"):
            new_dispatch[name] = override
        elif callable(override):
            new_dispatch[name] = override
        else:
            new_dispatch[name] = _wrap_const(override)
    monkeypatch.setattr(orch_module, "TOOL_DISPATCH", new_dispatch)


def _wrap_const(value: Any):
    """Build an async callable that returns ``value``, or raises if it's an exception."""
    async def _fn(_symbol: str) -> Any:
        if isinstance(value, Exception):
            raise value
        return value
    return _fn


def _patch_synth(
    monkeypatch: pytest.MonkeyPatch,
    summaries: SectionSummaries | Exception,
) -> list[dict[str, Any]]:
    """Replace ``llm.synth_call`` with a stub that returns ``summaries``.

    Returns a list that captures every call's kwargs so tests can
    assert what the orchestrator actually asked for.
    """
    captured: list[dict[str, Any]] = []

    async def _fake_synth(prompt: str, schema: type, **kwargs: Any) -> Any:
        captured.append({"prompt": prompt, "schema": schema, **kwargs})
        if isinstance(summaries, Exception):
            raise summaries
        return summaries

    monkeypatch.setattr(orch_module.llm, "synth_call", _fake_synth)
    return captured


def _summaries_for(*titles: str, prose: str = "Summary text.") -> SectionSummaries:
    return SectionSummaries(
        sections=[SectionSummary(title=t, summary=prose) for t in titles]
    )


# ── Happy paths ───────────────────────────────────────────────────────


async def test_full_focus_assembles_seven_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    summaries = _summaries_for(
        "Valuation", "Quality", "Capital Allocation",
        "Earnings", "Peers", "Risk Factors", "Macro",
    )
    _patch_synth(monkeypatch, summaries)

    report = await compose_research_report("aapl", Focus.FULL)

    assert isinstance(report, ResearchReport)
    assert report.symbol == "AAPL"  # uppercased
    # Phase 4.4.A — Business + News land at the front of the catalog;
    # this test still asserts on the seven numeric sections, so allow
    # them through but pin the numeric sequence.
    titles = [s.title for s in report.sections]
    assert titles[:2] == ["Business", "News"]
    assert titles[2:] == [
        "Valuation", "Quality", "Capital Allocation",
        "Earnings", "Peers", "Risk Factors", "Macro",
    ]
    # All numeric sections populated → HIGH per section. Business +
    # News default-stubbed to empty in this test, so they land LOW;
    # overall confidence is the min so it lands LOW too.
    assert all(
        s.confidence == Confidence.HIGH
        for s in report.sections
        if s.title not in {"Business", "News"}
    )


async def test_earnings_focus_assembles_three_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for("News", "Earnings", "Valuation", "Risk Factors"),
    )

    report = await compose_research_report("AAPL", Focus.EARNINGS)

    assert [s.title for s in report.sections] == [
        "News", "Earnings", "Valuation", "Risk Factors",
    ]


async def test_summary_text_threaded_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    summaries = SectionSummaries(
        sections=[
            SectionSummary(title="Valuation", summary="Apple trades at 33x earnings."),
            SectionSummary(title="Quality", summary="ROE is exceptional."),
            SectionSummary(title="Capital Allocation", summary="Mostly buybacks."),
            SectionSummary(title="Earnings", summary="Q1 beat consensus."),
            SectionSummary(title="Peers", summary="Trades premium to peers."),
            SectionSummary(title="Risk Factors", summary="One new risk added."),
            SectionSummary(title="Macro", summary="Rate-sensitive."),
        ]
    )
    _patch_synth(monkeypatch, summaries)

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s.summary for s in report.sections}
    assert by_title["Valuation"] == "Apple trades at 33x earnings."
    assert by_title["Risk Factors"] == "One new risk added."


# ── Failure isolation ────────────────────────────────────────────────


async def test_one_tool_failure_isolated_to_its_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_peers raising must not break Valuation / Quality / etc.

    fetch_peers feeds only the Peers section in full mode; that
    section ends up with [] claims and LOW confidence; the other
    sections are unaffected.
    """
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": RuntimeError("yfinance is down"),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s for s in report.sections}
    # Peers tanked
    assert by_title["Peers"].claims == []
    assert by_title["Peers"].confidence == Confidence.LOW
    # The other 6 are HIGH (fully populated, fresh)
    for title in [
        "Valuation", "Quality", "Capital Allocation",
        "Earnings", "Risk Factors", "Macro",
    ]:
        assert by_title[title].confidence == Confidence.HIGH
    # Overall is the floor
    assert report.overall_confidence == Confidence.LOW


async def test_fundamentals_failure_drops_three_sections_to_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_fundamentals feeds 3 sections — its failure cascades to all 3."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": ConnectionError("yfinance unreachable"),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s for s in report.sections}
    assert by_title["Valuation"].confidence == Confidence.LOW
    assert by_title["Quality"].confidence == Confidence.LOW
    assert by_title["Capital Allocation"].confidence == Confidence.LOW
    assert by_title["Earnings"].confidence == Confidence.HIGH
    assert by_title["Peers"].confidence == Confidence.HIGH


async def test_all_tools_fail_returns_all_low_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every tool errors → every section LOW, overall LOW, but synth still runs."""
    err = RuntimeError("upstream down")
    _patch_tools(
        monkeypatch,
        {n: err for n in [
            "fetch_fundamentals", "fetch_earnings", "fetch_peers",
            "fetch_macro", "extract_10k_risks_diff", "extract_10k_business",
        ]},
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    assert all(s.confidence == Confidence.LOW for s in report.sections)
    assert all(s.claims == [] for s in report.sections)
    assert report.overall_confidence == Confidence.LOW


# ── Synth-output handling ────────────────────────────────────────────


async def test_synth_missing_section_falls_back_to_default_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    # Synth omits "Macro"
    summaries = SectionSummaries(
        sections=[
            SectionSummary(title=t, summary=f"text for {t}")
            for t in [
                "Valuation", "Quality", "Capital Allocation",
                "Earnings", "Peers", "Risk Factors",
            ]
        ]
    )
    _patch_synth(monkeypatch, summaries)

    report = await compose_research_report("AAPL", Focus.FULL)

    macro = next(s for s in report.sections if s.title == "Macro")
    # Fallback summary is non-empty and clearly indicates absence.
    assert macro.summary
    assert "macro" in macro.summary.lower() or "summary unavailable" in macro.summary.lower()


async def test_synth_unknown_title_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synth hallucinates a section title we didn't ask for → ignore it."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    summaries = SectionSummaries(
        sections=[
            SectionSummary(title="Valuation", summary="ok"),
            SectionSummary(title="Quality", summary="ok"),
            SectionSummary(title="Capital Allocation", summary="ok"),
            SectionSummary(title="Earnings", summary="ok"),
            SectionSummary(title="Peers", summary="ok"),
            SectionSummary(title="Risk Factors", summary="ok"),
            SectionSummary(title="Macro", summary="ok"),
            SectionSummary(title="ESG Analysis", summary="hallucinated"),
        ]
    )
    _patch_synth(monkeypatch, summaries)

    report = await compose_research_report("AAPL", Focus.FULL)

    titles = [s.title for s in report.sections]
    assert "ESG Analysis" not in titles
    # Phase 4.4.A — Business + News added to FULL catalog → 9 sections.
    assert len(report.sections) == 9


# ── Audit trail + observability ──────────────────────────────────────


async def test_tool_calls_audit_records_every_invoked_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    # Phase 4.4.A — eight tool names (added fetch_business_info +
    # fetch_news). Order doesn't matter, presence does.
    audit_names = {entry.split(":")[0].strip() for entry in report.tool_calls_audit}
    assert audit_names == {
        "fetch_fundamentals", "fetch_earnings", "fetch_peers",
        "fetch_macro", "extract_10k_risks_diff", "extract_10k_business",
        "fetch_business_info", "fetch_news", "fetch_annual_history",
    }


async def test_tool_calls_audit_marks_failed_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": RuntimeError("boom"),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    # The failed tool's audit entry mentions its outcome.
    peers_entry = next(
        e for e in report.tool_calls_audit if e.startswith("fetch_peers")
    )
    assert "error" in peers_entry.lower() or "fail" in peers_entry.lower()
    assert "RuntimeError" in peers_entry


# ── Symbol normalization ─────────────────────────────────────────────


async def test_symbol_uppercased_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def _capture(symbol: str) -> dict[str, Claim]:
        seen.append(symbol)
        return _fundamentals_output()

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _capture,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    await compose_research_report("aapl", Focus.FULL)

    assert "AAPL" in seen


# ── Phase 4.1 — top-level name + sector ─────────────────────────────


async def test_orchestrator_lifts_name_and_sector_to_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.1 — fetch_fundamentals exposes ``name`` and
    ``sector_tag`` claims; the orchestrator copies their values to
    top-level ``ResearchReport.name`` / ``.sector`` so the dashboard
    hero card can read them without traversing claims."""
    fundamentals = _fundamentals_output()
    fundamentals["name"] = _claim("Company name", "Apple Inc.")
    fundamentals["sector_tag"] = _claim("Sector", "megacap_tech")

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": fundamentals,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("aapl", Focus.FULL)

    assert report.name == "Apple Inc."
    assert report.sector == "megacap_tech"


async def test_orchestrator_top_level_metadata_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When fetch_fundamentals fails or omits the metadata claims,
    top-level name/sector are None — backwards compatible with pre-4.1
    cached reports."""
    fundamentals = _fundamentals_output()
    # No name / sector_tag claims at all.
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": fundamentals,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("aapl", Focus.FULL)

    assert report.name is None
    assert report.sector is None


# ── backfill_top_level_metadata (Phase 4.3.X) ─────────────────────────


def _make_report_with_fundamentals(
    *,
    top_name: str | None = None,
    top_sector: str | None = None,
    fundamentals_name: str | None = None,
    fundamentals_sector: str | None = None,
) -> ResearchReport:
    """Build a minimal ResearchReport whose Valuation section optionally
    carries fundamentals-style ``Company name`` / ``Resolved sector tag``
    claims, plus optional top-level ``name``/``sector`` fields."""
    from app.schemas.research import Section

    claims: list[Claim] = []
    if fundamentals_name is not None:
        claims.append(
            Claim(
                description="Company name",
                value=fundamentals_name,
                source=Source(tool="test.fundamentals", fetched_at=datetime.now(UTC)),
            )
        )
    if fundamentals_sector is not None:
        claims.append(
            Claim(
                description="Resolved sector tag",
                value=fundamentals_sector,
                source=Source(tool="test.fundamentals", fetched_at=datetime.now(UTC)),
            )
        )
    return ResearchReport(
        symbol="AAPL",
        generated_at=datetime.now(UTC),
        sections=[Section(title="Valuation", claims=claims)],
        overall_confidence=Confidence.HIGH,
        name=top_name,
        sector=top_sector,
    )


def test_backfill_top_level_metadata_lifts_from_fundamentals_claims() -> None:
    """Phase 4.3.X / Bug 6 — pre-Phase-4.1 cached rows lack top-level
    name + sector but still carry the underlying fundamentals claims.
    The helper lifts the values up so the dashboard hero card renders
    correctly without forcing a fresh-gen.
    """
    report = _make_report_with_fundamentals(
        fundamentals_name="Apple Inc.",
        fundamentals_sector="megacap_consumer_tech",
    )
    assert report.name is None
    assert report.sector is None

    out = backfill_top_level_metadata(report)
    assert out.name == "Apple Inc."
    assert out.sector == "megacap_consumer_tech"


def test_backfill_top_level_metadata_preserves_existing_values() -> None:
    """When the report already has top-level name/sector set, the
    helper is a no-op — never overwrites a non-None top-level value
    even if a stale claim disagrees."""
    report = _make_report_with_fundamentals(
        top_name="From Top Level",
        top_sector="from_top_level",
        fundamentals_name="From Claim",
        fundamentals_sector="from_claim",
    )
    out = backfill_top_level_metadata(report)
    assert out.name == "From Top Level"
    assert out.sector == "from_top_level"


def test_backfill_top_level_metadata_no_fundamentals_claim_leaves_none() -> None:
    """No claim, no top level → still None after backfill (not an error).
    Renders as em-dash on the frontend."""
    report = _make_report_with_fundamentals()
    out = backfill_top_level_metadata(report)
    assert out.name is None
    assert out.sector is None


# ── Phase 4.4.A: Business + News tools wired into TOOL_DISPATCH ──────


async def test_full_focus_invokes_business_info_and_news_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.4.A — the orchestrator's tool fan-out for FULL focus
    must include ``fetch_business_info`` + ``fetch_news`` so the
    ContextBand has data to render. We patch both and assert each is
    invoked once for the target symbol."""
    business_calls: list[str] = []
    news_calls: list[str] = []

    async def _fake_business(symbol: str) -> dict[str, Claim]:
        business_calls.append(symbol)
        return {
            "summary": _claim("Business description (from 10-K filing)", "x"),
            "hq": _claim("Headquarters location", "Cupertino, CA, United States"),
            "employee_count": _claim("Full-time employee count", 164_000),
        }

    async def _fake_news(symbol: str) -> dict[str, Claim]:
        news_calls.append(symbol)
        return {
            "news_0": _claim("Apple beats Q1", "positive"),
            "news_1": _claim("iPhone 17 launches", "neutral"),
        }

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
            "fetch_business_info": _fake_business,
            "fetch_news": _fake_news,
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Business", "News",
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("aapl", Focus.FULL)

    assert business_calls == ["AAPL"]
    assert news_calls == ["AAPL"]
    titles = [s.title for s in report.sections]
    assert "Business" in titles
    assert "News" in titles


# ── Phase 4.4.B — per-card section narratives ────────────────────────


async def test_card_narrative_threaded_through_when_synth_returns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SectionSummary.card_narrative`` from the synth call lands on
    ``Section.card_narrative`` in the assembled report — distinct from
    ``Section.summary`` which holds the longer narrative."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    summaries = SectionSummaries(
        sections=[
            SectionSummary(
                title="Quality",
                summary="Apple's margin profile is exceptional across the board.",
                card_narrative=(
                    "Trajectory positive, level positive. Gross margin "
                    "stable in mid-40s; ROE elite."
                ),
            ),
            SectionSummary(
                title="Earnings",
                summary="Beat consensus 17 of 20.",
                card_narrative="Loss is narrowing. EPS climbed steadily.",
            ),
            SectionSummary(title="Valuation", summary="Trades premium."),
            SectionSummary(title="Capital Allocation", summary="Buybacks dominant."),
            SectionSummary(title="Peers", summary="Premium to peers."),
            SectionSummary(title="Risk Factors", summary="Stable."),
            SectionSummary(title="Macro", summary="Rate-sensitive."),
        ]
    )
    _patch_synth(monkeypatch, summaries)

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s for s in report.sections}
    assert by_title["Quality"].card_narrative == (
        "Trajectory positive, level positive. Gross margin "
        "stable in mid-40s; ROE elite."
    )
    assert by_title["Earnings"].card_narrative == (
        "Loss is narrowing. EPS climbed steadily."
    )
    # Sections whose synth output lacked card_narrative land as None,
    # not empty string — the rendering layer treats them differently
    # (None hides the strip; "" would render an empty card-within-card).
    assert by_title["Valuation"].card_narrative is None
    # ``summary`` and ``card_narrative`` are independent surfaces.
    assert by_title["Quality"].summary == (
        "Apple's margin profile is exceptional across the board."
    )


async def test_card_narrative_falls_back_to_none_when_synth_omits_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the synth call omits a section title entirely, that section's
    ``card_narrative`` is None (the orchestrator already supplies a
    fallback ``summary`` — there's no equivalent fallback prose for the
    card narrative since blank > a generic placeholder)."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    # Synth omits Macro entirely.
    _patch_synth(
        monkeypatch,
        SectionSummaries(
            sections=[
                SectionSummary(title=t, summary=f"text for {t}", card_narrative=f"narrative for {t}")
                for t in [
                    "Valuation", "Quality", "Capital Allocation",
                    "Earnings", "Peers", "Risk Factors",
                ]
            ]
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s for s in report.sections}
    macro = by_title["Macro"]
    # Fallback summary still fires (existing 4.0 behavior).
    assert macro.summary
    # Card narrative has no fallback — None when missing.
    assert macro.card_narrative is None
    # The sections that were present still get their card narrative.
    assert by_title["Valuation"].card_narrative == "narrative for Valuation"


async def test_card_narrative_empty_string_normalized_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If synth emits ``card_narrative=""`` (model declined to write
    one), the orchestrator stores None so the rendering layer's
    ``narrative ? <strip/> : null`` check uniformly hides the strip."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        SectionSummaries(
            sections=[
                SectionSummary(title="Valuation", summary="ok", card_narrative=""),
                SectionSummary(title="Quality", summary="ok", card_narrative="   "),
                SectionSummary(title="Capital Allocation", summary="ok"),
                SectionSummary(title="Earnings", summary="ok", card_narrative="real prose."),
                SectionSummary(title="Peers", summary="ok"),
                SectionSummary(title="Risk Factors", summary="ok"),
                SectionSummary(title="Macro", summary="ok"),
            ]
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    by_title = {s.title: s for s in report.sections}
    assert by_title["Valuation"].card_narrative is None
    assert by_title["Quality"].card_narrative is None
    assert by_title["Earnings"].card_narrative == "real prose."


async def test_layout_signals_attached_to_fresh_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.5.A — orchestrator computes ``layout_signals`` and
    attaches them to the ``ResearchReport`` it returns. Healthy
    fixture data → all flags False/None."""
    from app.schemas.research import LayoutSignals

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("AAPL", Focus.FULL)

    assert isinstance(report.layout_signals, LayoutSignals)
    # Default fixture descriptions don't match the real Operating
    # margin / Net profit margin / etc. strings — derive returns the
    # healthy default.
    assert report.layout_signals.is_unprofitable_ttm is False
    assert report.layout_signals.cash_runway_quarters is None


async def test_layout_signals_distressed_fixture_lights_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the fundamentals tool ships claims with the real
    ``_DESCRIPTIONS`` strings AND distressed values, the orchestrator's
    derived signals reflect the distress."""
    distressed_fundamentals = {
        "operating_margin": _claim("Operating margin", -0.41),
        "profit_margin": _claim("Net profit margin", -0.55),
        "gross_margin": _claim("Gross margin", -0.18),
    }

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": distressed_fundamentals,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    report = await compose_research_report("RIVN", Focus.FULL)

    assert report.layout_signals.is_unprofitable_ttm is True
    assert report.layout_signals.gross_margin_negative is True


def test_backfill_layout_signals_for_pre_4_5_cached_report() -> None:
    """Pre-4.5 cached reports lack the derived signals. The backfill
    helper recomputes them from the section claims so the dashboard's
    adaptive UI works on cache hits without re-running the LLM."""
    from app.schemas.research import LayoutSignals
    from app.services.research_orchestrator import backfill_layout_signals

    distressed_claim = Claim(
        description="Operating margin",
        value=-0.41,
        source=Source(tool="yfinance.fundamentals", fetched_at=datetime.now(UTC)),
    )
    report = ResearchReport(
        symbol="RIVN",
        generated_at=datetime.now(UTC),
        sections=[Section(title="Quality", claims=[distressed_claim], confidence=Confidence.HIGH)],
        overall_confidence=Confidence.HIGH,
        # Default healthy LayoutSignals — simulating a pre-4.5 cache row.
        layout_signals=LayoutSignals(),
    )

    backfilled = backfill_layout_signals(report)

    assert backfilled.layout_signals.is_unprofitable_ttm is True
    # Original input not mutated.
    assert report.layout_signals.is_unprofitable_ttm is False


def test_backfill_layout_signals_no_op_when_already_distressed() -> None:
    """If the cached report already has distressed signals (post-4.5
    cache row), the backfill is a no-op — never overwrite a fresh
    derivation with another from the same data."""
    from app.schemas.research import LayoutSignals
    from app.services.research_orchestrator import backfill_layout_signals

    report = ResearchReport(
        symbol="RIVN",
        generated_at=datetime.now(UTC),
        sections=[],
        overall_confidence=Confidence.LOW,
        layout_signals=LayoutSignals(is_unprofitable_ttm=True, cash_runway_quarters=4.5),
    )

    backfilled = backfill_layout_signals(report)
    # Same instance — no mutation, no copy.
    assert backfilled is report


async def test_user_prompt_includes_layout_signals_when_distressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.5.B — Sonnet's user prompt receives the derived layout
    signals as context so the model's narratives can adapt for
    distressed names ("Loss is narrowing" vs "Margins exceptional").

    The prompt must surface the signals when at least one is non-default
    so the model has the framing context — and skip the block entirely
    on healthy reports so we don't burn input tokens on a static
    'all-healthy' boilerplate."""
    distressed_fundamentals = {
        "operating_margin": _claim("Operating margin", -0.41),
        "profit_margin": _claim("Net profit margin", -0.55),
        "gross_margin": _claim("Gross margin", -0.18),
    }

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": distressed_fundamentals,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    captured = _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    await compose_research_report("RIVN", Focus.FULL)

    # One section-prose call (the analyst view is a second, separate call).
    section_calls = [c for c in captured if c["schema"] is SectionSummaries]
    assert len(section_calls) == 1
    prompt = section_calls[0]["prompt"]
    # The prompt mentions the distressed framing explicitly so Sonnet
    # can adapt its tone. We don't pin the exact wording — assert the
    # signals' names land in the prompt + a framing word.
    assert "is_unprofitable_ttm" in prompt
    lower = prompt.lower()
    assert "distressed" in lower or "unprofitable" in lower or "negative" in lower


async def test_user_prompt_omits_layout_signals_block_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy reports skip the layout-signals context block entirely
    — no point burning input tokens on a 'no distressed signals' line
    when every flag is at its healthy default."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    captured = _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    await compose_research_report("AAPL", Focus.FULL)

    prompt = captured[0]["prompt"]
    # No distressed framing should be in the prompt for a healthy
    # report. The signal names won't appear when the block is omitted.
    assert "is_unprofitable_ttm" not in prompt


def test_system_prompt_documents_card_narrative_as_distinct_field() -> None:
    """The synth-call system prompt must instruct the model that
    ``card_narrative`` is a 1-2 sentence headline distinct from the
    longer ``summary`` — otherwise the model writes the same prose
    into both slots."""
    prompt = orch_module._SYSTEM_PROMPT
    lower = prompt.lower()
    # Both surfaces are referenced by name.
    assert "card_narrative" in prompt
    assert "summary" in lower
    # The prompt must distinguish their roles — at least one of these
    # framings is present (we don't pin the exact wording, just that
    # the distinction is articulated).
    distinguishes = (
        "1-2 sentence" in lower
        or "1–2 sentence" in lower
        or "shorter" in lower
        or "punchy" in lower
        or "headline" in lower
    )
    assert distinguishes, (
        "system prompt should distinguish card_narrative (1-2 sentence "
        "headline) from summary (2-4 sentence narrative)"
    )


# ── Claim units reach the prompt (2026-11 dogfood #1) ────────────────
#
# The prompt used to carry ``repr(value)``, so DeepSeek wrote "return on
# equity of 1.42" and compared a fraction-form buyback yield (0.017)
# with a percent-form dividend yield (0.32) as if they were the same
# unit. Unit-annotated claims now reach the model as display values.


def _unit_claim(description: str, value: float, unit: str) -> Claim:
    return Claim(
        description=description,
        value=value,
        unit=unit,  # type: ignore[arg-type]
        source=Source(tool="yfinance.fundamentals", fetched_at=datetime.now(UTC)),
    )


async def test_user_prompt_shows_unit_annotated_values_in_display_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fundamentals = _fundamentals_output()
    fundamentals["roe"] = _unit_claim("Return on equity", 1.4226, "fraction")
    fundamentals["dividend_yield"] = _unit_claim("Forward dividend yield", 0.32, "percent")
    fundamentals["buyback_yield"] = _unit_claim(
        "Buyback yield (latest fiscal year)", 0.0174, "fraction"
    )
    fundamentals["market_cap"] = _unit_claim("Market capitalization", 4.98e12, "usd")

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": fundamentals,
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    captured = _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    await compose_research_report("AAPL", Focus.FULL)

    prompt = captured[0]["prompt"]
    assert "Return on equity = 142.26%" in prompt
    assert "Forward dividend yield = 0.32%" in prompt
    assert "Buyback yield (latest fiscal year) = 1.74%" in prompt
    assert "Market capitalization = $4.98T" in prompt
    assert "1.4226" not in prompt
    assert "0.0174" not in prompt


async def test_user_prompt_keeps_raw_values_for_unannotated_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tools without unit annotations (the fixtures' plain claims) keep
    the old ``repr`` form."""
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    captured = _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )

    await compose_research_report("AAPL", Focus.FULL)

    assert "Trailing Pe = 1.5 (test.tool)" in captured[0]["prompt"]


def test_system_prompt_says_values_are_in_display_units() -> None:
    """The model is told to cite values in the units shown, not to
    convert them back to raw decimals."""
    lower = orch_module._SYSTEM_PROMPT.lower()
    assert "display units" in lower


# ── ADR 0007 — history, derived comparisons, interpretation ──────────


def test_claim_line_carries_its_history_in_display_units() -> None:
    claim = Claim(
        description="Operating margin",
        value=0.34,
        unit="fraction",
        source=Source(tool="yfinance.fundamentals", fetched_at=datetime.now(UTC)),
        history=[
            ClaimHistoryPoint(period="2025-Q3", value=0.30),
            ClaimHistoryPoint(period="2025-Q4", value=0.25),
            ClaimHistoryPoint(period="2026-Q1", value=0.31),
            ClaimHistoryPoint(period="2026-Q2", value=0.33),
            ClaimHistoryPoint(period="2026-Q3", value=0.34),
        ],
    )
    line = orch_module._format_claim_line(claim)
    assert line.startswith("- Operating margin = 34.00% (yfinance.fundamentals)")
    assert "5 periods: 2025-Q3 30.00% → 2026-Q3 34.00%" in line
    assert "low 25.00% (2025-Q4)" in line
    assert "high 34.00% (2026-Q3)" in line


def test_claim_line_without_history_is_unchanged() -> None:
    claim = Claim(
        description="Return on equity",
        value=1.4226,
        unit="fraction",
        source=Source(tool="yfinance.fundamentals", fetched_at=datetime.now(UTC)),
    )
    assert orch_module._format_claim_line(claim) == "- Return on equity = 142.26% (yfinance.fundamentals)"


async def test_prompt_includes_derived_comparison_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "fetch_peers": _peers_output(),
            "fetch_macro": _macro_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    captured = _patch_synth(
        monkeypatch,
        _summaries_for(
            "Valuation", "Quality", "Capital Allocation",
            "Earnings", "Peers", "Risk Factors", "Macro",
        ),
    )
    await compose_research_report("AAPL", Focus.FULL)
    assert "(computed.analytics)" in captured[0]["prompt"]


def test_system_prompt_asks_for_interpretation_without_new_numbers() -> None:
    lower = orch_module._SYSTEM_PROMPT.lower()
    assert "so what" in lower
    assert "never compute" in lower
    # Grounding: no causes or events the claims don't contain.
    assert "outside facts" in lower


def test_prompt_names_the_sector_and_adds_the_bank_note() -> None:
    prompt = orch_module._build_user_prompt("JPM", Focus.FULL, {"Quality": []}, None, "banks")
    assert "Sector: banks" in prompt
    assert "Sector note: This is a bank" in prompt
    plain = orch_module._build_user_prompt("KO", Focus.FULL, {"Quality": []}, None, "consumer_staples")
    assert "Sector: consumer_staples" in plain
    assert "Sector note" not in plain
    assert "Sector:" not in orch_module._build_user_prompt("ZZZ", Focus.FULL, {"Quality": []})


def test_system_prompt_keeps_outside_knowledge_out() -> None:
    lower = orch_module._SYSTEM_PROMPT.lower()
    assert "no product, model or brand names" in lower
    assert "never \"down -2.65 pts\"" in lower


# ── Phase 5 — the analyst view ────────────────────────────────────────


def _all_tools() -> dict[str, Any]:
    return {
        "fetch_fundamentals": _fundamentals_output(),
        "fetch_earnings": _earnings_output(),
        "fetch_peers": _peers_output(),
        "fetch_macro": _macro_output(),
        "extract_10k_risks_diff": _risks_diff_output(),
        "extract_10k_business": _business_output(),
    }


_SECTIONS = ("Valuation", "Quality", "Capital Allocation", "Earnings", "Peers", "Risk Factors", "Macro")


async def test_full_report_carries_the_analyst_view(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tools(monkeypatch, _all_tools())
    _patch_synth(monkeypatch, _summaries_for(*_SECTIONS))
    seen: dict[str, Any] = {}

    async def _fake_thesis(symbol: str, section_claims: Any, **kwargs: Any) -> Thesis:
        seen.update(kwargs, symbol=symbol, titles=list(section_claims))
        return Thesis(
            headline="A strong business priced for it.",
            bull=[ThesisPoint(text="Margins expand.", claim_refs=[ClaimRef(section="Quality", index=0)])],
        )

    monkeypatch.setattr(orch_module.research_thesis, "compose_thesis", _fake_thesis)
    report = await compose_research_report("AAPL", Focus.FULL)
    assert report.thesis is not None
    assert report.thesis.headline == "A strong business priced for it."
    assert seen["symbol"] == "AAPL"
    assert "Quality" in seen["titles"]


async def test_report_stands_when_the_analyst_view_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real compose_thesis gets the stub's SectionSummaries back, not a
    ThesisDraft, and must degrade to None instead of failing the report."""
    _patch_tools(monkeypatch, _all_tools())
    _patch_synth(monkeypatch, _summaries_for(*_SECTIONS))
    report = await compose_research_report("AAPL", Focus.FULL)
    assert report.thesis is None
    assert {s.title for s in report.sections} >= set(_SECTIONS)


async def test_earnings_focus_skips_the_analyst_view(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tools(monkeypatch, _all_tools())
    captured = _patch_synth(monkeypatch, _summaries_for("Earnings", "Valuation", "Risk Factors"))
    report = await compose_research_report("AAPL", Focus.EARNINGS)
    assert report.thesis is None
    assert all(c["schema"] is SectionSummaries for c in captured)


# ── Report version (2026-11-10) ──────────────────────────────────────


async def test_fresh_reports_carry_the_current_report_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.report_version import REPORT_VERSION

    _patch_tools(
        monkeypatch,
        {
            "fetch_fundamentals": _fundamentals_output(),
            "fetch_earnings": _earnings_output(),
            "extract_10k_risks_diff": _risks_diff_output(),
            "extract_10k_business": _business_output(),
        },
    )
    _patch_synth(monkeypatch, _summaries_for("News", "Earnings", "Valuation", "Risk Factors"))

    report = await compose_research_report("AAPL", Focus.EARNINGS)

    assert report.report_version == REPORT_VERSION


def test_reports_cached_before_versioning_read_as_version_zero() -> None:
    from app.services.report_version import is_outdated

    cached = {"symbol": "KO", "generated_at": "2026-11-08T14:00:00+00:00", "sections": []}
    report = ResearchReport.model_validate(cached)
    assert report.report_version == 0
    assert is_outdated(report)


# ── Audit: a tool that returned nothing is not "ok" (dogfood #18) ─────


async def test_audit_says_empty_when_a_tool_succeeds_with_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """XOM, 2026-11: the SEC tools found no filings, raised nothing and
    were audited "ok", so nothing said why two cards were missing."""
    _patch_tools(
        monkeypatch,
        {
            # No 10-K found: the extractor returns None.
            "extract_10k_risks_diff": None,
            # Stable shape, every value None.
            "fetch_annual_history": {
                "revenue_per_share_annual": _claim("Revenue per share, annual", None),
                "eps_diluted_annual": _claim("Diluted EPS, annual", None),
            },
            # No headlines in the window.
            "fetch_news": {},
            # Some values missing is normal, not empty.
            "fetch_fundamentals": {
                "trailing_pe": _claim("P/E ratio (trailing 12 months)", 28.5),
                "peg": _claim("PEG ratio", None),
            },
            "fetch_peers": RuntimeError("boom"),
        },
    )
    names = [
        "extract_10k_risks_diff",
        "fetch_annual_history",
        "fetch_fundamentals",
        "fetch_news",
        "fetch_peers",
    ]
    outputs, audit = await orch_module._run_tools_parallel("XOM", names)

    assert audit == [
        "extract_10k_risks_diff: empty",
        "fetch_annual_history: empty",
        "fetch_fundamentals: ok",
        "fetch_news: empty",
        "fetch_peers: error/RuntimeError",
    ]
    # An empty result still reaches the section builders, which handle
    # it; only a tool that raised is left out.
    assert set(outputs) == {
        "extract_10k_risks_diff",
        "fetch_annual_history",
        "fetch_fundamentals",
        "fetch_news",
    }


async def test_audit_says_empty_for_macro_labels_without_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``FRED_API_KEY`` fetch_macro still returns its sector and
    series labels, so "any value at all" would call it ok. It has data
    only when a series carries observations."""
    labels_only = {
        "sector": _claim("Resolved sector tag", "integrated_oil"),
        "DCOILWTICO.label": _claim("Human-readable label for FRED series DCOILWTICO", "WTI crude oil price"),
        "DCOILWTICO.value": _claim("WTI crude oil price (latest observation)", None),
    }
    observed = _claim("WTI crude oil price (latest observation)", 88.28)
    observed = observed.model_copy(
        update={"history": [ClaimHistoryPoint(period="2026-09", value=85.1), ClaimHistoryPoint(period="2026-10", value=88.28)]}
    )

    _patch_tools(monkeypatch, {"fetch_macro": labels_only})
    _outputs, audit = await orch_module._run_tools_parallel("XOM", ["fetch_macro"])
    assert audit == ["fetch_macro: empty"]

    _patch_tools(monkeypatch, {"fetch_macro": {**labels_only, "DCOILWTICO.value": observed}})
    _outputs, audit = await orch_module._run_tools_parallel("XOM", ["fetch_macro"])
    assert audit == ["fetch_macro: ok"]


def test_both_prompts_say_a_year_end_figure_is_not_todays() -> None:
    """First real report with year-end multiples (KO, 2026-11-13): the
    prose called the fiscal-2025 price-to-free-cash-flow "today"."""
    from app.services import research_thesis

    for prompt in (orch_module._SYSTEM_PROMPT, research_thesis.THESIS_SYSTEM_PROMPT):
        assert "A value is as of when its description says" in prompt
        assert "at fiscal year-end" in prompt
