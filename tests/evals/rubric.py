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
   ``summary`` prose also appears in some claim's ``value`` or
   ``history``. Catches the most common hallucination mode: the
   model writing a plausible number into the summary that no tool
   ever produced. After Phase 3.4 the value pool widened to include
   each ``Claim.history[*].value`` so trend prose like "EPS rose
   from 1.40 to 2.18" matches even when neither endpoint is the
   point-in-time snapshot. Since 2026-11 a number quoted literally in
   the same section's claim text (a description like "last 20
   quarters", or a string value like the business summary) also
   counts as backed.

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

from app.schemas.research import ResearchReport, Section

# Match a decimal number, optionally with thousands separators and a
# decimal part. Excludes leading + / - so we don't grab the "-" out of
# date ranges. Excludes trailing % so we treat "12.3%" the same as
# "12.3" (the source claim might be stored either way).
#
# A finance unit suffix may follow directly — multiples ("14.03x") and
# scaled amounts ("$888.27B", "164.1M", "$4.51T", "3.2bn"). Without it
# the closing ``\b`` can't sit between "3" and "x", so "14.03x" was read
# as 14. Any other trailing letter ("Item 1A", "20Q", "5Y") still means
# a label, not a number, and is skipped.
_NUMBER_RE = re.compile(
    r"\b(?P<num>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:x|bn|[BTMK])?\b"
)

# ISO dates ("2026-01-29") are stripped whole. Without this, the year
# regex below would only catch "2026" and leave "01" / "29" to be
# extracted as 1.0 / 29.0 — false positives that aren't financial
# claims at all. Order matters: strip dates BEFORE bare years.
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")

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
    """Pull decimal numbers out of prose, dropping obvious date / year noise."""
    cleaned = _ISO_DATE_RE.sub(" ", text)
    cleaned = _YEAR_RE.sub(" ", cleaned)
    out: list[float] = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group("num").replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _claim_numeric_values(report: ResearchReport) -> list[float]:
    """All numeric claim values across the report — snapshots **and**
    history points.

    List, not set: order is irrelevant for matching but duplicates
    are allowed (a claim value of 0 repeated across sections is still
    one matchable value).

    ## Phase 3.4 — history points count as factual support

    After 3.2.A–F shipped 19+ history-bearing claims, the LLM
    naturally weaves trend prose like "EPS rose from 1.40 in Q1 to
    2.18 in Q4" — both numbers come from ``Claim.history``, not the
    point-in-time snapshot. Yielding history values into the same
    flat list means the existing ``_matches_claim`` rules
    (tolerance, sign-flip, fraction-percent, scaled units) apply
    uniformly to historical values too, with no special-casing in
    the matcher.

    Pre-3.2 claims with ``history=[]`` are unchanged: only the
    snapshot value is yielded.
    """
    out: list[float] = []
    for section in report.sections:
        for claim in section.claims:
            v = claim.value
            if isinstance(v, int | float) and not isinstance(v, bool):
                out.append(float(v))
            # History points are validated as floats by
            # ClaimHistoryPoint's field_validator, so no isinstance
            # guard is needed — the schema already rejects str/bool.
            for point in claim.history:
                out.append(float(point.value))
    return out


def _claim_text_numbers(section: Section) -> list[float]:
    """Numbers quoted in a section's claim *text* — every description,
    plus string values such as the business summary or a news headline.

    These ground prose that repeats them ("15 of the last 20 quarters",
    "the 10-K", "founded in 1799"): the number is in the tool output,
    just not as a value. Same extraction as prose, so years and ISO
    dates drop out on both sides.
    """
    out: list[float] = []
    for claim in section.claims:
        out.extend(_extract_numbers(claim.description))
        if isinstance(claim.value, str):
            out.extend(_extract_numbers(claim.value))
    return out


def _matches_claim(prose_n: float, claim_v: float, tolerance: float) -> bool:
    """Check ``prose_n`` against ``claim_v`` under finance display rules.

    Beyond direct numeric match (within ``tolerance``), also accept:

    1. **Sign-flip.** Prose like "a reduction of 714 chars" implicitly
       carries the sign that's stored in the claim (-714). Accept
       absolute-value matches.
    2. **Fraction → percentage.** A gross margin claim of 0.47325 will
       be written as "47.33%" — the LLM is doing standard finance
       display, not hallucinating. Accept 100×fraction matches with a
       proportionally scaled tolerance.
    3. **Scaled units.** A market cap of 3,972,863,098,880 will be
       written as "$3.97 trillion"; shares short of 134,422,787 as
       "134.4 million". Accept matches when ``claim_v`` divided by
       1e6, 1e9, or 1e12 lands inside ``tolerance`` of ``prose_n``.

    Each rule covers a real pattern observed in Sonnet's research-
    report prose. Skipping any of them produces false positives that
    swamp genuine hallucinations.
    """
    # Direct match.
    if abs(prose_n - claim_v) <= tolerance:
        return True

    # Sign-flip ("reduction of 714" cites a -714 char delta).
    if abs(abs(prose_n) - abs(claim_v)) <= tolerance:
        return True

    # Fraction <-> percentage. 0.47325 → "47.33%" with tolerance scaled
    # to 100× since the comparison is in the percentage-magnitude space.
    pct_tolerance = tolerance * 100
    if abs(prose_n - claim_v * 100) <= pct_tolerance:
        return True
    if abs(prose_n - abs(claim_v) * 100) <= pct_tolerance:
        return True

    # Scaled units: trillions, billions, millions. Only meaningful for
    # values large enough that the scaling makes sense (≥ 1e6). LLMs
    # typically round to 1 decimal place when displaying scaled units
    # ("$3.97 trillion", "134.4 million"), so use a wider tolerance for
    # these matches than for raw / fraction matches. 0.1 covers
    # one-decimal-place rounding without admitting fabricated values:
    # at scaled-unit magnitudes, "3.5 billion" vs "3.6 billion" still
    # fails (diff = 0.1 = tolerance, edge case) — anything sloppier
    # than that is a real miscount worth flagging.
    if abs(claim_v) >= 1e6:
        scaled_tolerance = 0.1
        for scale in (1e12, 1e9, 1e6):
            if abs(prose_n - claim_v / scale) <= scaled_tolerance:
                return True
            if abs(prose_n - abs(claim_v) / scale) <= scaled_tolerance:
                return True

    return False


def score_factuality(
    report: ResearchReport,
    *,
    tolerance: float = 0.01,
) -> FactualityScore:
    """
    For every decimal number in any ``summary`` or ``card_narrative``
    prose, check whether it matches some Claim.value in the report —
    under direct, sign-flip, fraction-percentage, or scaled-unit
    equivalence (see ``_matches_claim``). If a section has no prose
    or no claims, it contributes nothing; the check is per-number,
    not per-section.

    Phase 4.4.B: ``card_narrative`` joined ``summary`` as a policed
    surface so the LLM can't dodge the rubric by writing the
    hallucination into the card-strip instead of the section narrative.

    2026-11 (ADR 0006 eval): a number also counts as backed when it is
    quoted in the text of one of the *same section's* claims (see
    ``_claim_text_numbers``). That match is literal only — the percent,
    sign-flip and scaled-unit rules are for numeric values, and applying
    them to the "20" in "last 20 quarters" would excuse a fabricated
    "2,000". Section scoping keeps an Earnings description from
    excusing a stray number in the Valuation prose.
    """
    claim_values = _claim_numeric_values(report)
    found: list[float] = []
    unmatched: list[float] = []

    for section in report.sections:
        text_numbers = _claim_text_numbers(section)
        prose_fields: list[str] = []
        if section.summary:
            prose_fields.append(section.summary)
        if section.card_narrative:
            prose_fields.append(section.card_narrative)
        for prose in prose_fields:
            for n in _extract_numbers(prose):
                found.append(n)
                if any(_matches_claim(n, v, tolerance) for v in claim_values):
                    continue
                if any(abs(n - t) <= tolerance for t in text_numbers):
                    continue
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
