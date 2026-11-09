"""Response shapes for ``/v1/lens`` — cross-company lenses (ADR 0007 layer 3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.research import Claim, ThesisDraftPoint, ThesisPoint


class LensPoint(BaseModel):
    """One company-year. Ratios are None when an input is missing (or the
    operating cash flow is not positive)."""

    year: int
    capex: float | None = None
    revenue: float | None = None
    ocf: float | None = None
    capex_intensity: float | None = Field(default=None, description="capex / revenue")
    capex_to_ocf: float | None = Field(default=None, description="capex / operating cash flow")


class LensCompany(BaseModel):
    ticker: str
    name: str
    points: list[LensPoint]


class LensYearStats(BaseModel):
    """The distribution of capex intensity across the companies reporting
    that year."""

    year: int
    companies: int
    median: float
    p25: float
    p75: float
    low: float
    low_ticker: str
    high: float
    high_ticker: str
    total_capex: float


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


class LensReport(LensSummary):
    method: str
    years: list[int]
    companies: list[LensCompany]
    stats: list[LensYearStats]
    facts: list[Claim]
    narrative: LensNarrative | None
    generated_at: datetime


class LensDraft(BaseModel):
    """LLM output for the narrative; loose on purpose, trimmed in code."""

    headline: str = Field(description="One sentence: the main pattern.")
    points: list[ThesisDraftPoint] = Field(default_factory=list)
