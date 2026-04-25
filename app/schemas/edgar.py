"""
Schemas for SEC EDGAR filings.

``EdgarFiling`` is a structured filing record returned by ``fetch_edgar``.
Filings are *inputs* to other tools (``parse_filing`` produces the
``Claim`` records that land in the report) — so this schema is plain
data, not citation-shaped. The agent's flow is fetch_edgar → parse_filing
→ Claim, with each layer narrower than the last.

Why a schema rather than a dataclass: Pydantic validation catches
upstream changes in EDGAR's submissions JSON shape before they
poison downstream parsers. The cache layer also serializes through
``model_dump_json`` / ``model_validate_json`` so a stable Pydantic
contract is the cache invariant.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EdgarFiling(BaseModel):
    """
    One SEC filing's metadata + (optionally) raw primary-document text.

    ``cik`` is the 10-digit zero-padded CIK as SEC URLs require it.
    ``accession`` is the dash-form id ("0000320193-24-000123") that
    appears in submissions metadata; the URL form swaps dashes for
    nothing ("000032019324000123") in the path. ``primary_doc_text`` is
    populated only when ``include_text=True`` is passed to fetch_edgar
    — the primary doc on a 10-K can be 10+ MB and we don't want to
    move that around when only the metadata is wanted.
    """

    model_config = ConfigDict(frozen=True)

    cik: str = Field(min_length=10, max_length=10, pattern=r"^\d{10}$")
    symbol: str = Field(min_length=1, max_length=16)
    accession: str = Field(min_length=20, max_length=20, pattern=r"^\d{10}-\d{2}-\d{6}$")
    form_type: str = Field(min_length=1, max_length=16)
    filed_at: datetime
    period_of_report: date | None = None
    primary_doc_url: str = Field(min_length=1, max_length=512)
    primary_doc_text: str | None = None
    size_bytes: int = Field(ge=0)
