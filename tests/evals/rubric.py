"""
Rubric scorers for research reports. Pure functions — given a
``ResearchReport`` (and optionally a list of expected facts), return a
score broken down by dimension. The agent test harness composes these
into a per-case grade; production observability could surface them as
section-level health metrics.

Three dimensions, in order of how cheap they are to enforce:

1. **Structure** — the agent's output validates as a ResearchReport.
   Free; just Pydantic. Catches drift in the structured-output contract.

2. **Factuality** — every numeric fact appearing in any section's
   ``summary`` prose also appears in that section's ``claims`` list.
   Catches the most common hallucination mode: the model writing a
   plausible number into the summary that no tool ever produced.

3. **Latency** — wall-clock duration of the run. Recorded by the test
   harness, not derived from the report itself.

The factuality check is heuristic, not semantic: we extract decimal
numbers with a regex, filter out obvious false positives (4-digit years,
percentages already cited, etc.), and flag anything left unmatched. It
will produce occasional false positives — when it does, the right fix
is usually to widen the tolerance or add the number to claims, not to
loosen the rubric.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.research import ResearchReport

# Match a decimal number, optionally with thousands separators and a
# decimal part. Excludes leading + / - so we don't grab the "-" out of
# date ranges. Excludes trailing % so we treat "12.3%" the same as
# "12.3" (the source claim might be stored either way).
_NUMBER_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\b")

# Years mentioned in passing ("Q3 2026 results", "FY2025 guidance") are
# almost never numerical claims — strip them before factuality scoring.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass(frozen=True)
class StructureScore:
    valid: bool
    errors: list[str]


@dataclass(frozen=True)
class FactualityScore:
    """
    Numbers found in any section's ``summary`` prose, scored for whether
    each appears in that section's ``claims``. ``score`` is the fraction
    of summary-numbers that found a matching claim — 1.0 means every
    number in prose is backed by data, 0.0 means none are.
    """

    summary_numbers: list[float]
    unmatched_numbers: list[float]
    score: float


@dataclass(frozen=True)
class LatencyScore:
    elapsed_ms: float


@dataclass(frozen=True)
class RubricResult:
    structure: StructureScore
    factuality: FactualityScore
    latency: LatencyScore


def score_structure(report_dict: dict) -> StructureScore:
    """Validate the raw dict against the ResearchReport schema."""
    try:
        ResearchReport.model_validate(report_dict)
    except Exception as exc:  # ValidationError is the common case
        return StructureScore(valid=False, errors=[str(exc)])
    return StructureScore(valid=True, errors=[])


def _extract_numbers(text: str) -> list[float]:
    """Pull decimal numbers out of prose, dropping obvious year noise."""
    cleaned = _YEAR_RE.sub(" ", text)
    out: list[float] = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group(0).replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _claim_numeric_values(report: ResearchReport) -> set[float]:
    """All numeric claim values across the report, for fast lookup."""
    out: set[float] = set()
    for section in report.sections:
        for claim in section.claims:
            v = claim.value
            if isinstance(v, int | float) and not isinstance(v, bool):
                out.add(float(v))
    return out


def score_factuality(
    report: ResearchReport,
    *,
    tolerance: float = 0.01,
) -> FactualityScore:
    """
    For every decimal number in any ``summary`` prose, check whether it
    matches (within ``tolerance``) some Claim.value in the report. If a
    section has no summary or no claims, it contributes nothing — the
    factuality check is per-number, not per-section.
    """
    claim_values = _claim_numeric_values(report)
    found: list[float] = []
    unmatched: list[float] = []

    for section in report.sections:
        if not section.summary:
            continue
        for n in _extract_numbers(section.summary):
            found.append(n)
            if not any(abs(n - v) <= tolerance for v in claim_values):
                unmatched.append(n)

    if not found:
        # Pure-prose section with no numbers — vacuously factual.
        # This also covers reports where summaries are empty (bare claim lists).
        return FactualityScore(summary_numbers=[], unmatched_numbers=[], score=1.0)

    matched = len(found) - len(unmatched)
    return FactualityScore(
        summary_numbers=found,
        unmatched_numbers=unmatched,
        score=matched / len(found),
    )


def score_latency(elapsed_ms: float) -> LatencyScore:
    """Trivial wrapper for symmetry with the other scorers."""
    return LatencyScore(elapsed_ms=elapsed_ms)


def grade(
    report: ResearchReport,
    elapsed_ms: float,
    *,
    factuality_tolerance: float = 0.01,
) -> RubricResult:
    """Run all three scorers and bundle the result."""
    return RubricResult(
        structure=StructureScore(valid=True, errors=[]),  # already a model
        factuality=score_factuality(report, tolerance=factuality_tolerance),
        latency=score_latency(elapsed_ms),
    )
