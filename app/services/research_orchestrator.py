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
    LayoutSignals,
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
from app.services.research_layout_signals import derive_layout_signals
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
You are a financial analyst writing the prose for a structured equity \
research report. The report is composed of sections (Valuation, \
Quality, Earnings, etc.). For each section the user gives you a list \
of factual Claims — each Claim has a description, a numeric or text \
value, and a source identifier. Your job is to write TWO prose fields \
per section:

- ``summary``: a broad 2–4 sentence narrative covering the section.
- ``card_narrative``: a SHORTER 1–2 sentence punchy headline tagline \
distinct from the summary. Lead with the takeaway, follow with the \
supporting delta. Style examples (do NOT copy verbatim — match the \
shape, not the words):
  • "Loss is narrowing. EPS −3.82 → −0.78 over 20Q with no positive print."
  • "Trajectory positive, level negative. Gross margin up 226 pts in 5Y \
but still below break-even."
  • "Disinflation continues. 10Y has compressed 43 bps from peak."
  • "Disclosure expanded. Net +9 ¶ across categories — concentrated in \
AI / regulatory and export controls."
The card_narrative is what users see first on each dashboard card; it \
should be the single most informative one-liner the data supports.

Hard rules — these are non-negotiable, and they apply to BOTH ``summary`` \
and ``card_narrative``:

1. **Cite only values present in the claim list.** Every number, \
percentage, dollar amount, ratio, ticker symbol, or named entity that \
appears in your prose MUST appear in that section's claim list (either \
as a snapshot ``value`` or a ``history[*].value``). Do not introduce \
values you weren't given. This is the project's anti-hallucination \
contract.

2. **Round responsibly.** Numbers may be rounded to 1–2 decimal places \
or to natural units ($24.6M instead of $24,594,922.77) but the rounded \
form must clearly correspond to a value in the claim list.

3. **Acknowledge missing data.** If a section's claim list is empty or \
every value is None, ``summary`` is one sentence explaining that data \
was unavailable, and ``card_narrative`` is the empty string (omit the \
field). Do not invent context to fill the gap.

4. **Plain prose only.** No bullet lists, no headers, no markdown \
inside either field.

5. **Length discipline.** ``summary`` stays 2–4 sentences. \
``card_narrative`` stays 1–2 sentences and reads punchier — the \
takeaway, then the delta. No editorializing, no speculation, no \
investment advice in either.

6. **Match the section title exactly.** The user gives you a list of \
section titles to populate; emit one entry per title using that title \
verbatim. Do not invent additional sections.

7. **Don't duplicate.** ``summary`` and ``card_narrative`` are different \
surfaces — write distinct prose for each. The card_narrative is not \
the summary's first sentence shortened.
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


def _resolve_card_narrative(
    title: str, summaries: SectionSummaries
) -> str | None:
    """Match the synth-call output's card_narrative for ``title``.

    Phase 4.4.B. Distinct from ``_resolve_summary`` in two ways:

    1. **No fallback string.** A missing card_narrative renders as a
       hidden strip on the frontend — there's no neutral default that
       would be more informative than the absence.
    2. **Empty / whitespace normalized to None.** The model may
       legitimately decline to emit a narrative for a section with
       no data ("Risk Factors" when nothing changed); collapsing
       empty strings to None means every renderer can do a uniform
       truthy check (``narrative ? <strip /> : null``).
    """
    matched = [s.card_narrative for s in summaries.sections if s.title == title]
    if not matched:
        return None
    last = matched[-1]
    if last is None or not last.strip():
        return None
    return last


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

    # 4. Stitch together Sections with claims + summary +
    #    card_narrative + confidence.
    sections: list[Section] = []
    for spec in specs:
        claims = section_claims[spec.title]
        sections.append(
            Section(
                title=spec.title,
                claims=claims,
                summary=_resolve_summary(spec.title, summaries),
                card_narrative=_resolve_card_narrative(spec.title, summaries),
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

    report = ResearchReport(
        symbol=target,
        generated_at=datetime.now(UTC),
        sections=sections,
        overall_confidence=_overall_confidence(sections),
        tool_calls_audit=audit,
        name=name_value,
        sector=sector_value,
    )
    # Phase 4.5.A — derive adaptive-layout signals from the assembled
    # report. Pure transform — runs after section assembly so it can
    # read the same claim values the dashboard will read.
    return report.model_copy(update={"layout_signals": derive_layout_signals(report)})


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


def backfill_layout_signals(report: ResearchReport) -> ResearchReport:
    """Recompute ``layout_signals`` from claim values for cached
    pre-4.5 reports.

    Phase 4.5.A. Pre-4.5 cached JSONB rows have ``layout_signals=
    LayoutSignals()`` (the healthy default), which silently broke
    adaptive layouts on cache hits — a Rivian report from before the
    derivation existed would render as healthy.

    Trust-the-cache rule: if the report's ``layout_signals`` is
    *anything other than* the healthy default, leave it alone. The
    only case worth backfilling is "field is at the healthy default,
    which might mean genuinely healthy or might mean pre-4.5 cache row
    that never had a derivation". When current == default, re-derive;
    if the derivation still returns default, fast-path identity so
    callers can ``backfilled is report``.
    """
    if report.layout_signals != LayoutSignals():
        # Trust the cache — never overwrite a populated value.
        return report
    fresh_signals = derive_layout_signals(report)
    if fresh_signals == report.layout_signals:
        return report
    return report.model_copy(update={"layout_signals": fresh_signals})


# Re-export ``LayoutSignals`` so the test module can import the type
# from the orchestrator alongside ``backfill_layout_signals`` without
# threading two import lines.
__all__ = [
    "LayoutSignals",
    "backfill_layout_signals",
    "backfill_top_level_metadata",
    "compose_research_report",
]
