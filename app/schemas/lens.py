"""Response shapes for ``/v1/lens`` — cross-company lenses (ADR 0007 layer 3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.research import Claim, ThesisDraftPoint, ThesisPoint


class LensMetricInfo(BaseModel):
    """What a lens measures: ``label`` starts a heading ("R&D"), ``short``
    sits inside a sentence ("capex")."""

    key: str
    label: str
    short: str
    definition: str


class LensPoint(BaseModel):
    """One company-year of the lens's metric. Ratios are None when an
    input is missing (or the operating cash flow is not positive)."""

    year: int
    value: float | None = Field(default=None, description="the metric, USD")
    revenue: float | None = None
    ocf: float | None = None
    intensity: float | None = Field(default=None, description="metric / revenue")
    to_ocf: float | None = Field(default=None, description="metric / operating cash flow")


class LensCompany(BaseModel):
    ticker: str
    name: str
    points: list[LensPoint]


class LensYearStats(BaseModel):
    """The distribution of the metric's intensity across the companies
    reporting that year; ``total`` is the metric summed over them."""

    year: int
    companies: int
    median: float
    p25: float
    p75: float
    low: float
    low_ticker: str
    high: float
    high_ticker: str
    total: float


class LensNarrative(BaseModel):
    """What the distribution shows. Each point's ``claim_refs`` index into
    ``LensReport.facts`` (section ``"Lens"``)."""

    headline: str
    points: list[ThesisPoint]


class LensSummary(BaseModel):
    id: str
    title: str
    description: str
    tickers: list[str]
    metric: LensMetricInfo


class LensReport(LensSummary):
    method: str
    years: list[int]
    companies: list[LensCompany]
    stats: list[LensYearStats]
    facts: list[Claim]
    narrative: LensNarrative | None
    generated_at: datetime
    excluded: list[str] = Field(
        default_factory=list, description="tickers with no figure for the metric in their filings"
    )


class LensDraft(BaseModel):
    """LLM output for the narrative; loose on purpose, trimmed in code."""

    headline: str = Field(description="One sentence: the main pattern.")
    points: list[ThesisDraftPoint] = Field(default_factory=list)
