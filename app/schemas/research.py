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

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Phase 4.3.X — display-unit hint for Claim.value. The frontend formatter
# (frontend/src/lib/format.ts::formatClaimValue) dispatches on this so a
# fraction-form ROE > 1 doesn't silently drop the % suffix, a per-share
# dollar < $1 isn't rendered as a percent, and yfinance's percent-form
# dividendYield isn't ×100'd a second time. Kept as an optional Literal
# so pre-4.3.X cached rows (where the field is absent) round-trip
# unchanged and fall through to the heuristic on the frontend.
ClaimUnit = Literal[
    "fraction",        # 0.74 → "74.00%"  — margins, ROE, ROIC, growth fractions
    "percent",         # 0.39 → "0.39%"   — yfinance-shaped dividendYield, FRED rates
    "usd",             # 4.11e12 → "$4.11T", 921.04 → "$921.04" — market cap, 52W
    "usd_per_share",   # 0.16 → "$0.16"   — capex/sbc/per-share dollars
    "ratio",           # 33.92 → "33.92"  — P/E, EV/EBITDA, days-to-cover
    "count",           # 12,345 → "12,345" with locale grouping
    "shares",          # 134.42M → "134.42M" abbreviated, no $
    "basis_points",    # rare, reserved for explicit bp-shaped deltas
    "date",            # ISO string passthrough
    "string",          # name, sector tag
]


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


class ClaimHistoryPoint(BaseModel):
    """
    One point in a Claim's time series — a period label and a numeric
    value. Used by Phase 3 to render sparklines and section charts
    next to point-in-time claim values (per ADR 0004).

    ``period`` is an opaque string emitted by the tool that produced
    the history (``"2024-Q4"``, ``"2024-12"``, ``"2024"``, …).
    Different tools emit different granularities; the rendering layer
    treats it as a label, never parses it.

    ``value`` is intentionally a plain ``float`` (not the broader
    ``ClaimValue`` union). Strings, booleans, and nulls aren't
    chartable — when a tool can't produce a numeric history point, it
    omits the point rather than emitting None. This keeps the
    rendering layer's contract narrow.

    Frozen because history points are value objects — once a point
    has been recorded, mutating it mid-flight would silently corrupt
    a chart.
    """

    model_config = ConfigDict(frozen=True)

    period: str = Field(min_length=1, max_length=32)
    value: float

    @field_validator("value", mode="before")
    @classmethod
    def _value_must_be_numeric(cls, v: Any) -> Any:
        # Pydantic 2 by default coerces ``"2.18"`` -> ``2.18`` for a
        # ``float`` field; we reject strings explicitly so a bug in a
        # tool doesn't smuggle text into a chart series. Booleans also
        # rejected — ``bool`` is an ``int`` subtype in Python and would
        # otherwise pass numeric validation as 0.0 / 1.0, which is
        # never meaningful as a history point.
        if isinstance(v, bool):
            raise ValueError("value must be numeric, not a boolean")
        if isinstance(v, str):
            raise ValueError("value must be numeric, not a string")
        return v


class Claim(BaseModel):
    """
    One factual statement in a report. ``description`` is the
    human-readable label ("P/E ratio (trailing 12 months)"), ``value`` is
    the data point, ``source`` is where it came from. The structured
    output schema is the only way the agent can include a number — there
    is no free-form prose path that bypasses this.

    ``history`` (Phase 3.1) is an optional time series of
    ``ClaimHistoryPoint``s for the same metric over prior periods.
    Defaults to ``[]`` so existing claims and existing cache rows
    round-trip unchanged. Tools that can produce a series (e.g.
    ``fetch_fundamentals`` reading yfinance's quarterly tables)
    populate it; tools that can't (e.g. peer-comparison snapshots)
    leave it empty. The frontend renders a sparkline when
    ``history`` has ≥ 2 points and skips it otherwise.
    """

    description: str = Field(min_length=1, max_length=200)
    value: ClaimValue
    source: Source
    history: list[ClaimHistoryPoint] = Field(default_factory=list)
    # Phase 4.3.X — optional display-unit hint. ``None`` (the default)
    # leaves the frontend on its legacy heuristic, which is correct for
    # any value already covered by the rules in formatClaimValue. Tools
    # that ship values where the heuristic gets it wrong (per-share
    # dollars < $1, percent-form yields, fraction-form ROE > 1) set
    # this to an explicit category so the formatter dispatches
    # deterministically.
    unit: ClaimUnit | None = None


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
    # Phase 4.1 — top-level metadata for the dashboard hero card.
    # Both default to None so pre-4.1 cached JSONB rows round-trip
    # unchanged. Values are lifted from fetch_fundamentals' name +
    # sector_tag claims by ``research_orchestrator.compose_research_report``.
    name: str | None = None
    sector: str | None = None

    @property
    def all_claims(self) -> list[Claim]:
        return [c for s in self.sections for c in s.claims]


# ── Synth-call output schema (internal, not user-facing) ──────────────
#
# The agent's only job in 2.2a is to write summary prose. Section
# composition (which claims go in which section) is determined by code
# in ``app.services.research_tool_registry`` so the LLM cannot
# misplace a metric. The synth call's forced-tool schema is therefore
# bounded to ``{title, summary}`` pairs — one per section the
# orchestrator requested.
#
# The orchestrator passes the agent the full claim list per section in
# the user prompt, and instructs the model to write a 2–4 sentence
# summary that ONLY references values present in those claims. After
# the call returns, the orchestrator matches summaries to sections by
# title; unknown titles are dropped, missing titles get a fallback
# summary.


# ── List-endpoint summary shape (Phase 3.0 A3) ───────────────────────
#
# ``GET /v1/research`` returns a paginated list of past reports for the
# dashboard sidebar. The full ``ResearchReport`` blob would be wasteful
# (every page render would ship dozens of cached reports' full
# sections + claims trees over the wire). This summary carries only
# the 5 fields the sidebar actually renders — clicks fetch the full
# report via ``POST /v1/research/{symbol}`` which hits the same-day
# cache and returns instantly.


class ResearchReportSummary(BaseModel):
    """Lightweight cache-row metadata for the dashboard list view."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=16)
    focus: str = Field(min_length=1, max_length=16)
    report_date: date
    generated_at: datetime
    overall_confidence: Confidence


class SectionSummary(BaseModel):
    """One ``{title, summary}`` pair emitted by the synth call.

    ``title`` MUST match a section title the orchestrator requested
    (case-sensitive). Lookups that miss are dropped silently rather
    than raised — the orchestrator already has the canonical title
    list, the model is allowed to be sloppy, and a missing summary
    falls back to a neutral default.
    """

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=4000)


class SectionSummaries(BaseModel):
    """Synth-call output: the prose for every requested section."""

    model_config = ConfigDict(frozen=True)

    sections: list[SectionSummary] = Field(default_factory=list)
