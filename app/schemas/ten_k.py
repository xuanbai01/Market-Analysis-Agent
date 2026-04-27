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

from pydantic import BaseModel, ConfigDict, Field


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
