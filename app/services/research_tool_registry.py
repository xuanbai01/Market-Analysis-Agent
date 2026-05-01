"""
Static registry mapping research focus modes to sections and tools.

Why a static registry rather than LLM-driven section composition:
anti-hallucination. The agent's job is prose; section composition is
code. ``SECTIONS_BY_FOCUS`` declares — for each focus mode — the exact
list of sections, the tools each section consumes, and how to extract
that section's Claims from those tools' outputs. This is reviewable in
one file and testable without an LLM.

## Two responsibilities

1. **Section catalog** (``SECTIONS_BY_FOCUS``) — for ``Focus.FULL``,
   the seven sections of a long-form research report; for
   ``Focus.EARNINGS``, three sections framed around an upcoming or
   recent earnings event.

2. **Builders** — pure functions that take a ``tool_outputs`` dict
   (``{tool_name: raw_output}``) and return the section's Claims. For
   ``dict[str, Claim]`` tools (fundamentals, peers, earnings, macro)
   the builder is a key-filter. For tools returning Pydantic objects
   (``Extracted10KSection``, ``Risk10KDiff``), a small adapter
   constructs Claims from the object's fields.

## What a section's claims look like

The orchestrator runs the focus-mode's required tools in parallel,
collects their outputs into ``{tool_name: output}``, and calls each
section's builder with that dict. A tool that failed upstream is
absent from the dict; builders MUST return an empty list (not raise)
in that case so one tool failure degrades a section to LOW confidence
rather than killing the whole report.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.schemas.research import Claim, Source
from app.schemas.ten_k import Extracted10KSection, Risk10KDiff


class Focus(str, Enum):
    """Research-report scope. Determines section catalog + tool selection."""

    FULL = "full"
    EARNINGS = "earnings"


# A builder receives the orchestrator's tool-outputs dict and returns
# the section's Claims. ``Any`` is wide on purpose — different tools
# return different shapes (dict[str, Claim], Risk10KDiff,
# Extracted10KSection, None for failures).
SectionBuilder = Callable[[dict[str, Any]], list[Claim]]


@dataclass(frozen=True)
class SectionSpec:
    """One section in a research report.

    ``tools_required`` is the set of tool names whose outputs the
    builder reads. The orchestrator unions these across all sections
    of a focus to determine which tools to invoke.
    """

    title: str
    tools_required: tuple[str, ...]
    builder: SectionBuilder


# ── Per-section claim-key splits for fetch_fundamentals ──────────────
# fetch_fundamentals returns 28 flat keys (Phase 3.2.B+C: 22 from 3.2.A
# + 2 cash-flow-component + 4 balance-sheet trend claims). We split
# them across three sections so each section's prose is bounded and
# themed. Order within each list is the display order in the report.

_VALUATION_KEYS = ("trailing_pe", "forward_pe", "p_s", "ev_ebitda", "peg")
_QUALITY_KEYS = (
    # Legacy point-in-time
    "roe",
    "gross_margin",
    "profit_margin",
    "gross_margin_trend_1y",
    # Phase 3.2.A — per-share growth (history-bearing). Visual layer
    # renders sparklines next to these. Section's prose stays at
    # 2-4 sentences regardless of metric count.
    "revenue_per_share",
    "gross_profit_per_share",
    "operating_income_per_share",
    "fcf_per_share",
    "ocf_per_share",
    # Phase 3.2.A — margin trends (history-bearing).
    "operating_margin",
    "fcf_margin",
    # Phase 3.2.C — balance sheet trend (history-bearing). Financial-
    # strength read; lives in Quality alongside ROE / margins.
    "cash_and_st_investments_per_share",
    "total_debt_per_share",
    "total_assets_per_share",
    "total_liabilities_per_share",
    # Phase 3.2.D — ROIC TTM (history-bearing). Capital-efficiency read.
    # ``roe`` already in this section as a legacy point-in-time claim
    # that gains a history field this PR.
    "roic",
)
_CAPITAL_ALLOCATION_KEYS = (
    "dividend_yield",
    "buyback_yield",
    "sbc_pct_revenue",
    "short_ratio",
    "shares_short",
    "market_cap",
    # Phase 3.2.B — cash flow components (history-bearing). "What does
    # management do with the cash" lives here alongside the existing
    # yield + buyback metrics.
    "capex_per_share",
    "sbc_per_share",
)


def _filter_keys(claims: dict[str, Claim] | None, keys: tuple[str, ...]) -> list[Claim]:
    """Pull a fixed key subset out of a ``dict[str, Claim]``; keep order.

    None / missing-key / non-dict outputs all degrade to ``[]`` rather
    than raising — the builder contract is "graceful when upstream
    tool failed", and the orchestrator may pass anything (a dict, an
    exception, None) depending on what the tool returned.
    """
    if not isinstance(claims, dict):
        return []
    return [claims[k] for k in keys if k in claims]


def _build_valuation(outputs: dict[str, Any]) -> list[Claim]:
    return _filter_keys(outputs.get("fetch_fundamentals"), _VALUATION_KEYS)


def _build_quality(outputs: dict[str, Any]) -> list[Claim]:
    return _filter_keys(outputs.get("fetch_fundamentals"), _QUALITY_KEYS)


def _build_capital_allocation(outputs: dict[str, Any]) -> list[Claim]:
    return _filter_keys(
        outputs.get("fetch_fundamentals"), _CAPITAL_ALLOCATION_KEYS
    )


def _all_claims(claims: dict[str, Claim] | None) -> list[Claim]:
    """Pass-through for tools whose entire claim dict feeds one section."""
    if not isinstance(claims, dict):
        return []
    return list(claims.values())


def _build_earnings(outputs: dict[str, Any]) -> list[Claim]:
    return _all_claims(outputs.get("fetch_earnings"))


def _build_peers(outputs: dict[str, Any]) -> list[Claim]:
    return _all_claims(outputs.get("fetch_peers"))


def _build_macro(outputs: dict[str, Any]) -> list[Claim]:
    return _all_claims(outputs.get("fetch_macro"))


# ── Risk Factors: composed from two non-dict tools ────────────────────
# extract_10k_risks_diff returns Risk10KDiff (or None); we synthesize
# four Claims from its counts and char delta. extract_10k_business
# returns Extracted10KSection (or None); we add one Claim describing
# the business section's length so the agent has a citation hook for
# the company description.


def _build_risk_factors(outputs: dict[str, Any]) -> list[Claim]:
    claims: list[Claim] = []

    diff = outputs.get("extract_10k_risks_diff")
    if isinstance(diff, Risk10KDiff):
        diff_source = Source(
            tool="sec.ten_k_risks_diff",
            fetched_at=diff.current.filed_at,
            url=diff.current.primary_doc_url,
            detail=(
                f"current accession {diff.current.accession} vs prior "
                f"{diff.prior.accession}"
            ),
        )
        claims.append(
            Claim(
                description="Newly added risk paragraphs vs prior 10-K",
                value=len(diff.added_paragraphs),
                source=diff_source,
            )
        )
        claims.append(
            Claim(
                description="Risk paragraphs dropped vs prior 10-K",
                value=len(diff.removed_paragraphs),
                source=diff_source,
            )
        )
        claims.append(
            Claim(
                description="Risk paragraphs kept (carryover)",
                value=diff.kept_paragraph_count,
                source=diff_source,
            )
        )
        claims.append(
            Claim(
                description="Item 1A char delta vs prior 10-K",
                value=diff.char_delta,
                source=diff_source,
            )
        )

    business = outputs.get("extract_10k_business")
    if isinstance(business, Extracted10KSection):
        biz_source = Source(
            tool="sec.ten_k_business",
            fetched_at=business.filed_at,
            url=business.primary_doc_url,
            detail=f"accession {business.accession}",
        )
        claims.append(
            Claim(
                description="Business section length (chars)",
                value=business.char_count,
                source=biz_source,
            )
        )

    return claims


# ── Section catalog ──────────────────────────────────────────────────
# Order in the list is the display order in the rendered report.

SECTIONS_BY_FOCUS: dict[Focus, list[SectionSpec]] = {
    Focus.FULL: [
        SectionSpec("Valuation", ("fetch_fundamentals",), _build_valuation),
        SectionSpec("Quality", ("fetch_fundamentals",), _build_quality),
        SectionSpec(
            "Capital Allocation",
            ("fetch_fundamentals",),
            _build_capital_allocation,
        ),
        SectionSpec("Earnings", ("fetch_earnings",), _build_earnings),
        SectionSpec("Peers", ("fetch_peers",), _build_peers),
        SectionSpec(
            "Risk Factors",
            ("extract_10k_risks_diff", "extract_10k_business"),
            _build_risk_factors,
        ),
        SectionSpec("Macro", ("fetch_macro",), _build_macro),
    ],
    Focus.EARNINGS: [
        SectionSpec("Earnings", ("fetch_earnings",), _build_earnings),
        SectionSpec("Valuation", ("fetch_fundamentals",), _build_valuation),
        SectionSpec(
            "Risk Factors",
            ("extract_10k_risks_diff", "extract_10k_business"),
            _build_risk_factors,
        ),
    ],
}


def tools_for(focus: Focus) -> set[str]:
    """Distinct tool names the orchestrator must invoke for ``focus``.

    Returns a set so a tool that feeds multiple sections (e.g.
    fetch_fundamentals → Valuation + Quality + Capital Allocation in
    full mode) is invoked only once per request.
    """
    return {
        tool
        for spec in SECTIONS_BY_FOCUS[focus]
        for tool in spec.tools_required
    }
