"""
Annual financial series from SEC XBRL company facts.

The yfinance statements behind the dashboard stop at about five quarters.
The SEC's XBRL "company concept" API has every value a company has filed
for a us-gaap element, ten years and more. Phase 6 / ADR 0007 layer 3
uses it for cross-company lenses ("how is megacap capex distributed?").

Two things make raw XBRL awkward, and this module absorbs both:

1. **Tags change.** Amazon tagged capex ``PaymentsToAcquirePropertyPlant
   AndEquipment`` until 2016 and ``PaymentsToAcquireProductiveAssets``
   after; Nvidia's revenue moved from ``RevenueFromContractWith...`` to
   ``Revenues``. ``annual_series`` takes an ordered list of tags and
   merges them year by year, preferring the earlier tag.
2. **Fiscal years differ.** Facts carry the SEC's calendar ``frame``
   ("CY2025") — the calendar year a ~365-day fiscal year best matches
   (Apple's Oct–Sep year ending 2025 is CY2025). Only annual frames are
   used; ``CY2025Q3`` and year-to-date values are ignored.

Responses are cached on disk for a day (``{EDGAR_CACHE_DIR}/xbrl``): the
data only changes when a company files, and SEC's fair-access policy
asks clients not to refetch. Requests go through ``edgar._sec_get``
(required User-Agent, polite pacing).
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path

import httpx

from app.core.settings import settings
from app.services import edgar

CACHE_TTL_SECONDS = 24 * 3600
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"


def _cache_path(cik: str, tag: str) -> Path:
    return Path(settings.EDGAR_CACHE_DIR) / "xbrl" / cik / f"{tag}.json"


def fetch_concept(cik: str, tag: str) -> dict:
    """The company-concept payload for one us-gaap tag ({} if never filed).

    Sync (httpx + SEC pacing); callers run it in a thread.
    """
    path = _cache_path(cik, tag)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # unreadable cache entry: refetch
    try:
        payload = edgar._sec_get(_CONCEPT_URL.format(cik=cik, tag=tag)).json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        payload = {}  # the company never used this tag — cache the miss too
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def annual_values(payload: dict) -> dict[int, float]:
    """Calendar year → USD value, from the facts' annual ``CY####`` frames."""
    out: dict[int, float] = {}
    for fact in payload.get("units", {}).get("USD", []):
        frame = fact.get("frame", "")
        if len(frame) == 6 and frame.startswith("CY") and frame[2:].isdigit():
            out[int(frame[2:])] = float(fact["val"])
    return out


def annual_series(cik: str, tags: Sequence[str]) -> dict[int, float]:
    """One metric across tag changes: per year, the first tag that has it."""
    merged: dict[int, float] = {}
    for tag in tags:
        for year, value in annual_values(fetch_concept(cik, tag)).items():
            merged.setdefault(year, value)
    return dict(sorted(merged.items()))
