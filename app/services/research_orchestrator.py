"""
Research-report orchestrator.

Top-level coordinator for ``POST /v1/research/{symbol}``. Given a
symbol and a focus mode, it:

1. Resolves the focus to a tool set via ``research_tool_registry``.
2. Fans the tools out in parallel with ``asyncio.gather`` and isolates
   any per-tool exception (one tool failing must never kill the report).
3. For each section in the focus's catalog, runs the section's
   ``builder`` against the tool outputs to assemble its Claims.
4. Calls ``llm.synth_call`` once with a prompt listing every section's
   claims, asking Sonnet to write 2–4 sentences of summary prose per
   section. The forced-tool schema (``SectionSummaries``) constrains
   the model's output structurally.
5. Matches summaries to sections by title — unknown titles are
   dropped, missing titles fall back to a neutral default sentence.
6. Stamps confidence per section programmatically via
   ``research_confidence.score_section`` (LLM never sees confidence).
7. Returns a ``ResearchReport`` with a tool-call audit trail.

## Design choices vs the original "LLM picks claims + writes prose"

This module enforces "code picks claims, LLM only writes prose". The
agent literally cannot misplace a metric — section composition is a
static map in ``research_tool_registry``. The LLM's only output is
prose, and the prompt instructs it to cite only values present in the
claim list. The eval harness checks the latter; the former is
guaranteed structurally.

LLM-driven section composition is the natural escalation point if the
eval harness shows the static catalog is too rigid. That's a Phase
2.2d follow-up, not v1.

## Error handling and observability

- Per-tool exceptions are swallowed and recorded in
  ``tool_calls_audit`` as ``"<name>: error/<ExceptionType>"``. The
  underlying tool already wrote a structured ``log_external_call``
  record for whatever went wrong; we don't want to double-report.
- A synth-call failure propagates — there's no useful report to
  return. The router converts to a 503 problem+json.
- ``log_external_call`` is NOT used here. The orchestrator's job is
  composition, not external I/O. The tools and the LLM each log their
  own external calls; layering another log here would just add noise.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.schemas.research import (
    Confidence,
    ResearchReport,
    Section,
    SectionSummaries,
)
from app.services import llm
from app.services.business_info import fetch_business_info
from app.services.earnings import fetch_earnings
from app.services.fundamentals import fetch_fundamentals
from app.services.macro import fetch_macro
from app.services.news import fetch_news
from app.services.peers import fetch_peers
from app.services.research_confidence import score_section
from app.services.research_tool_registry import (
    SECTIONS_BY_FOCUS,
    Focus,
    SectionSpec,
    tools_for,
)
from app.services.ten_k import extract_10k_business, extract_10k_risks_diff

# Tool name → async callable taking (symbol). Tests substitute via
# ``monkeypatch.setattr(research_orchestrator, "TOOL_DISPATCH", ...)``;
# production code never reassigns.
TOOL_DISPATCH: dict[str, Callable[[str], Awaitable[Any]]] = {
    "fetch_fundamentals": fetch_fundamentals,
    "fetch_earnings": fetch_earnings,
    "fetch_peers": fetch_peers,
    "fetch_macro": fetch_macro,
    "extract_10k_business": extract_10k_business,
    "extract_10k_risks_diff": extract_10k_risks_diff,
    # Phase 4.4.A — Business + News tools wired in so the
    # ContextBand has data to render.
    "fetch_business_info": fetch_business_info,
    "fetch_news": fetch_news,
}


# ── Prompt construction ───────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a financial analyst writing the prose summaries of a structured \
equity research report. The report is composed of sections (Valuation, \
Quality, Earnings, etc.). For each section the user gives you a list of \
factual Claims — each Claim has a description, a numeric or text value, \
and a source identifier. Your only job is to write a 2–4 sentence \
summary per section.

Hard rules — these are non-negotiable:

1. **Cite only values present in the claim list.** Every number, \
percentage, dollar amount, ratio, ticker symbol, or named entity that \
appears in your summary MUST appear in that section's claim list. Do \
not introduce values you weren't given. This is the project's \
anti-hallucination contract.

2. **Round responsibly.** Numbers may be rounded to 1–2 decimal places \
or to natural units ($24.6M instead of $24,594,922.77) but the rounded \
form must clearly correspond to a value in the claim list.

3. **Acknowledge missing data.** If a section's claim list is empty or \
every value is None, write a single sentence explaining that data was \
unavailable. Do not invent context to fill the gap.

4. **Plain prose only.** No bullet lists, no headers, no markdown \
inside summaries. The orchestrator wraps your prose in section \
structure.

5. **Stay 2–4 sentences.** Concise, factual, declarative. No \
editorializing, no speculation, no investment advice.

6. **Match the section title exactly.** The user gives you a list of \
section titles to populate; emit one summary per title using that \
title verbatim. Do not invent additional sections.
"""

_FALLBACK_SUMMARY_TEMPLATE = (
    "Summary unavailable: the model did not return prose for the {title} "
    "section. The section's claims are still attached to this report."
)


def _format_claim_line(c: Any) -> str:
    """One line per claim for the prompt: ``- description = value (tool)``."""
    value_repr = "None" if c.value is None else repr(c.value)
    return f"- {c.description} = {value_repr} ({c.source.tool})"


def _build_user_prompt(
    symbol: str,
    focus: Focus,
    section_claims: dict[str, list[Any]],
) -> str:
    lines: list[str] = [
        f"Symbol: {symbol}",
        f"Focus: {focus.value}",
        "",
        "Write a SectionSummaries response with one entry per section "
        "below. Each summary must be 2–4 sentences and reference only "
        "values from that section's claim list.",
        "",
    ]
    for title, claims in section_claims.items():
        lines.append(f"## {title}")
        if not claims:
            lines.append(
                "(no data available — write a single sentence acknowledging "
                "the data was unavailable)"
            )
        else:
            for c in claims:
                lines.append(_format_claim_line(c))
        lines.append("")
    return "\n".join(lines)


# ── Tool fan-out ──────────────────────────────────────────────────────


async def _run_tools_parallel(
    symbol: str, tool_names: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """Invoke every required tool concurrently; isolate failures.

    Returns ``(outputs, audit_entries)`` where ``outputs`` maps a tool
    name to its result (only successful tools appear) and
    ``audit_entries`` is a parallel list of audit strings —
    ``"<name>: ok"`` for successes, ``"<name>: error/<ExceptionType>"``
    for failures.
    """
    coros = [TOOL_DISPATCH[name](symbol) for name in tool_names]
    results = await asyncio.gather(*coros, return_exceptions=True)

    outputs: dict[str, Any] = {}
    audit: list[str] = []
    for name, result in zip(tool_names, results, strict=True):
        if isinstance(result, BaseException):
            audit.append(f"{name}: error/{type(result).__name__}")
        else:
            outputs[name] = result
            audit.append(f"{name}: ok")
    return outputs, audit


# ── Section assembly ──────────────────────────────────────────────────


def _build_section_claims(
    specs: list[SectionSpec], outputs: dict[str, Any]
) -> dict[str, list[Any]]:
    """Run each section's builder; preserve catalog order."""
    return {spec.title: spec.builder(outputs) for spec in specs}


def _resolve_summary(
    title: str, summaries: SectionSummaries
) -> str:
    """Match the synth-call output to a requested section title.

    Last-wins on duplicates (the model shouldn't emit them, but if it
    does, take the latest). Falls back to a neutral default sentence
    when the synth output omitted this title — the section's claims
    are still attached, just the prose is missing.
    """
    matched = [s.summary for s in summaries.sections if s.title == title]
    if matched:
        return matched[-1]
    return _FALLBACK_SUMMARY_TEMPLATE.format(title=title)


def _overall_confidence(sections: list[Section]) -> Confidence:
    """Lowest section confidence wins. Conservative on purpose: a
    report with one LOW section should not present as MEDIUM overall."""
    if not sections:
        return Confidence.LOW
    levels = {s.confidence for s in sections}
    if Confidence.LOW in levels:
        return Confidence.LOW
    if Confidence.MEDIUM in levels:
        return Confidence.MEDIUM
    return Confidence.HIGH


# ── Public entry point ────────────────────────────────────────────────


async def compose_research_report(
    symbol: str, focus: Focus
) -> ResearchReport:
    """Build a ``ResearchReport`` for ``(symbol, focus)``.

    See module docstring for the orchestration contract. Errors from
    individual tools are isolated. Errors from the synth call (LLM
    unavailable, schema validation failure, etc.) propagate.
    """
    target = symbol.upper()
    specs = SECTIONS_BY_FOCUS[focus]

    # 1. Tool fan-out. ``sorted`` makes the audit deterministic.
    tool_names = sorted(tools_for(focus))
    outputs, audit = await _run_tools_parallel(target, tool_names)

    # 2. Per-section claim assembly.
    section_claims = _build_section_claims(specs, outputs)

    # 3. One synth call covering every section.
    prompt = _build_user_prompt(target, focus, section_claims)
    summaries = await llm.synth_call(
        prompt=prompt,
        schema=SectionSummaries,
        system=_SYSTEM_PROMPT,
    )

    # 4. Stitch together Sections with claims + summary + confidence.
    sections: list[Section] = []
    for spec in specs:
        claims = section_claims[spec.title]
        sections.append(
            Section(
                title=spec.title,
                claims=claims,
                summary=_resolve_summary(spec.title, summaries),
                confidence=score_section(claims),
            )
        )

    # Phase 4.1 — lift name + sector from fetch_fundamentals' metadata
    # claims to top-level ResearchReport fields so the dashboard hero
    # card can read them without traversing claims. Underlying claims
    # stay in place (citation discipline). Both default to None when
    # fetch_fundamentals failed or omitted them.
    fundamentals_out = outputs.get("fetch_fundamentals")
    name_value: str | None = None
    sector_value: str | None = None
    if isinstance(fundamentals_out, dict):
        name_claim = fundamentals_out.get("name")
        sector_claim = fundamentals_out.get("sector_tag")
        if name_claim is not None and isinstance(name_claim.value, str):
            name_value = name_claim.value
        if sector_claim is not None and isinstance(sector_claim.value, str):
            sector_value = sector_claim.value

    return ResearchReport(
        symbol=target,
        generated_at=datetime.now(UTC),
        sections=sections,
        overall_confidence=_overall_confidence(sections),
        tool_calls_audit=audit,
        name=name_value,
        sector=sector_value,
    )


# Phase 4.3.X — descriptions used to identify the metadata claims the
# orchestrator lifts up at fresh-gen time. Held here as constants so the
# backfill helper stays in step if ``fundamentals._DESCRIPTIONS`` ever
# renames them (the test suite exercises both paths so drift fails loudly).
_FUNDAMENTALS_NAME_DESCRIPTION = "Company name"
_FUNDAMENTALS_SECTOR_DESCRIPTION = "Resolved sector tag"


def backfill_top_level_metadata(report: ResearchReport) -> ResearchReport:
    """Lift name + sector from fundamentals claims when the top-level
    fields are absent.

    Pre-Phase-4.1 cached reports were generated before ``ResearchReport``
    grew top-level ``name`` / ``sector`` fields, so the JSONB rows still
    on disk have those as ``None`` even though the underlying claims
    are present. The dashboard hero card reads top-level only — without
    this backfill, AAPL renders as "—" until the cache row ages out.

    The helper is a no-op when:
    - both top-level fields are already set (never overwrite a fresh
      value with a stale claim);
    - the underlying claims aren't in any section (e.g. the
      orchestrator failed to fan out to fetch_fundamentals).

    Returns a possibly-replaced ``ResearchReport``; never mutates input.
    """
    if report.name is not None and report.sector is not None:
        return report

    backfilled_name = report.name
    backfilled_sector = report.sector

    if backfilled_name is None or backfilled_sector is None:
        for section in report.sections:
            for claim in section.claims:
                if (
                    backfilled_name is None
                    and claim.description == _FUNDAMENTALS_NAME_DESCRIPTION
                    and isinstance(claim.value, str)
                ):
                    backfilled_name = claim.value
                if (
                    backfilled_sector is None
                    and claim.description == _FUNDAMENTALS_SECTOR_DESCRIPTION
                    and isinstance(claim.value, str)
                ):
                    backfilled_sector = claim.value
                if (
                    backfilled_name is not None
                    and backfilled_sector is not None
                ):
                    break
            if (
                backfilled_name is not None
                and backfilled_sector is not None
            ):
                break

    if (
        backfilled_name == report.name
        and backfilled_sector == report.sector
    ):
        return report

    return report.model_copy(
        update={"name": backfilled_name, "sector": backfilled_sector}
    )
