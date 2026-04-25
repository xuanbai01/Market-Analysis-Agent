"""
Citation-enforcing schema for the v2 research report.

Every quantitative or specific claim in a report must be a `Claim` carrying
a `Source` (which tool produced it, when it was fetched, optional URL).
Section.summary is free-form prose — but the eval rubric checks that any
number or named entity appearing in `summary` is also present in `claims`.
The schema constrains data; the rubric polices the prose.

Confidence is set programmatically by the agent based on data freshness +
sparsity, not by the LLM — high/medium/low fields are a contract with the
caller, not a vibe.

See ADR 0003 §"Anti-hallucination disciplines" for the four invariants
this schema is meant to enforce.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(str, Enum):
    """Per-section confidence. Set programmatically — never by the LLM."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Source(BaseModel):
    """
    Provenance for a single claim. ``tool`` is the registered tool id
    (``yfinance.history``, ``edgar.10k``, ``fred.series``); ``detail``
    optionally narrows it (``Ticker.info[trailingPE]``, filing accession
    number, FRED series id). ``url`` is set when the source has a public
    citable URL — EDGAR filings, news articles. ``fetched_at`` is the wall
    time at which the upstream call returned, not when the report was
    generated.
    """

    model_config = ConfigDict(frozen=True)

    tool: str = Field(min_length=1, max_length=64)
    fetched_at: datetime
    url: str | None = None
    detail: str | None = Field(default=None, max_length=256)


# A claim's value can be a number, a string, or null (e.g. "data unavailable
# from source"). Booleans are intentionally allowed — beat/miss flags, etc.
ClaimValue = float | int | str | bool | None


class Claim(BaseModel):
    """
    One factual statement in a report. ``description`` is the
    human-readable label ("P/E ratio (trailing 12 months)"), ``value`` is
    the data point, ``source`` is where it came from. The structured
    output schema is the only way the agent can include a number — there
    is no free-form prose path that bypasses this.
    """

    description: str = Field(min_length=1, max_length=200)
    value: ClaimValue
    source: Source


class Section(BaseModel):
    """
    One section of a research report (Valuation, Quality, Earnings, …).
    ``claims`` is the source-of-truth data; ``summary`` is the LLM's
    synthesis of those claims into prose. The eval rubric checks that
    every number / named entity in ``summary`` appears in ``claims`` —
    summary cannot introduce new facts.
    """

    title: str = Field(min_length=1, max_length=80)
    claims: list[Claim] = Field(default_factory=list)
    summary: str = Field(default="", max_length=4000)
    confidence: Confidence = Confidence.LOW

    @property
    def last_updated(self) -> datetime | None:
        """Most recent ``fetched_at`` across this section's claims."""
        if not self.claims:
            return None
        return max(c.source.fetched_at for c in self.claims)


class ResearchReport(BaseModel):
    """
    Top-level Pydantic model returned by ``POST /v1/research/{symbol}``.
    Composed of N sections, with an overall confidence the agent
    derives from the section-level confidences (lowest wins by default).
    ``tool_calls_audit`` records which tools the agent invoked and in
    what order — kept for debugging and eval traces, not user-facing.
    """

    symbol: str = Field(min_length=1, max_length=16)
    generated_at: datetime
    sections: list[Section] = Field(default_factory=list)
    overall_confidence: Confidence = Confidence.LOW
    tool_calls_audit: list[str] = Field(default_factory=list)

    @property
    def all_claims(self) -> list[Claim]:
        return [c for s in self.sections for c in s.claims]
