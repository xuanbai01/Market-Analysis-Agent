"""
Schema for extracted 10-K sections.

Different shape from the data tools' ``dict[str, Claim]`` because the
output here is multi-page prose, not a list of factual data points.
The agent treats an ``Extracted10KSection`` as input *to* the synth
call (which composes the report's "Business Overview" or "Risks vs
Prior Year" section). Citation fields (accession, filed_at,
primary_doc_url) feed the Source attached to whatever Claims the
agent ends up emitting in those sections.

Why a Pydantic model rather than a dataclass: the cache layer (when
it lands) will serialize through ``model_dump_json`` /
``model_validate_json``; a stable Pydantic contract is the
serialization invariant.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiskCategory(str, Enum):
    """
    Buckets that ``risk_categorizer`` sorts each added/removed Item 1A
    paragraph into. Phase 4.3.B.

    String-valued so ``model_dump(mode="json")`` serializes them as
    plain strings — the cache layer's JSONB round-trip + the frontend's
    Zod schema both expect strings, not ints.

    Adding a new bucket requires a paired update to:
      - the categorizer's system prompt (definition + 1-line example)
      - the frontend ``RiskCategory`` union in ``schemas.ts``
      - the description label in ``research_tool_registry`` so the
        new bucket renders as a Claim

    The catalog is intentionally narrow (9 buckets) so Haiku can
    classify confidently and the bar chart stays readable. ``OTHER``
    is the fallback for paragraphs that don't fit; if ``OTHER``
    dominates an issuer's diff, that's a signal to widen the catalog.
    """

    AI_REGULATORY = "ai_regulatory"
    EXPORT_CONTROLS = "export_controls"
    SUPPLY_CONCENTRATION = "supply_concentration"
    CUSTOMER_CONCENTRATION = "customer_concentration"
    COMPETITION = "competition"
    CYBERSECURITY = "cybersecurity"
    IP = "ip"
    MACRO = "macro"
    OTHER = "other"


class Extracted10KSection(BaseModel):
    """
    One Item N section pulled from a 10-K, plus citation metadata.

    ``text`` is plain text (HTML stripped, XBRL tags removed). For a
    typical Item 1 or Item 1A on a large filer this is 10-150 KB; the
    schema enforces no cap because callers pipe it straight to an LLM
    that handles 200K-token windows.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=16)
    accession: str = Field(min_length=20, max_length=20, pattern=r"^\d{10}-\d{2}-\d{6}$")
    filed_at: datetime
    period_of_report: date | None = None
    section_id: str = Field(min_length=1, max_length=16)  # "Item 1", "Item 1A"
    section_title: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    char_count: int = Field(ge=0)
    primary_doc_url: str = Field(min_length=1, max_length=512)


class Risk10KDiff(BaseModel):
    """
    Year-over-year diff of Item 1A (Risk Factors) between the two most
    recent 10-Ks. Mechanical paragraph-level diff with fuzzy matching
    so cosmetic edits ("we" → "the Company") don't get flagged as new
    risks — the agent reads ``added_paragraphs`` to write a
    high-confidence "what's new in risks" section without comparing
    two ~50KB texts itself.

    ``current`` and ``prior`` are the full extracted sections (so the
    agent has each year's prose available if it needs context). The
    diff buckets are over the paragraph splits, not the flattened text.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=16)
    current: Extracted10KSection
    prior: Extracted10KSection
    added_paragraphs: list[str]
    removed_paragraphs: list[str]
    kept_paragraph_count: int = Field(ge=0)
    char_delta: int  # current.char_count − prior.char_count; can be negative
    # Phase 4.3.B — per-bucket net delta from the Haiku categorizer.
    # Empty dict by default so pre-4.3.B JSONB rows round-trip
    # unchanged (and stable disclosures, where the categorizer skips
    # the LLM call entirely, also land here as ``{}``). When populated:
    # value is added-paragraph-count minus removed-paragraph-count for
    # that category, never zero (zero-net buckets are filtered out by
    # the categorizer).
    category_deltas: dict[RiskCategory, int] = Field(default_factory=dict)
