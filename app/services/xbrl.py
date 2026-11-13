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
from app.services import edgar, sec_registrants

CACHE_TTL_SECONDS = 24 * 3600

# Ordered us-gaap tag preferences per metric; ``annual_series`` merges
# them year by year (companies switch tags over time).
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
OCF_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
# A company with nothing dilutive may tag one combined count, or only the
# basic one: Exxon stopped tagging a diluted count after 2013. Those fill
# the years that have no diluted count.
DILUTED_SHARES_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic",
)
DILUTED_EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
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


def annual_facts(payload: dict, unit: str = "USD") -> dict[int, tuple[float, str]]:
    """Calendar year → (value, filing date), from the facts' annual
    ``CY####`` frames in ``unit`` ("USD", "shares", "USD/shares").

    The filing date matters for share counts and per-share values: a
    framed fact is the latest one filed for that period, so it reflects
    the stock splits before that date and none after (NVDA's CY2018
    diluted shares, filed in Feb 2021, predate its 4:1 and 10:1 splits).
    """
    out: dict[int, tuple[float, str]] = {}
    for fact in payload.get("units", {}).get(unit, []):
        frame = fact.get("frame", "")
        if len(frame) == 6 and frame.startswith("CY") and frame[2:].isdigit():
            out[int(frame[2:])] = (float(fact["val"]), str(fact.get("filed", "")))
    return out


def annual_values(payload: dict) -> dict[int, float]:
    """Calendar year → USD value, from the facts' annual ``CY####`` frames."""
    return {year: value for year, (value, _filed) in annual_facts(payload, "USD").items()}


def annual_series(cik: str, tags: Sequence[str]) -> dict[int, float]:
    """One metric across tag changes: per year, the first tag that has it."""
    return {year: value for year, (value, _filed) in annual_series_with_filed(cik, tags).items()}


def annual_series_with_filed(
    cik: str, tags: Sequence[str], unit: str = "USD"
) -> dict[int, tuple[float, str]]:
    """``annual_series`` in any unit, keeping each value's filing date.

    Reads ``cik`` and then the registrants it replaced
    (``sec_registrants``): a company that reorganized under a new holding
    company keeps its earlier years under the old registrant. A year the
    current registrant has filed wins over the same year from an earlier
    one.
    """
    merged: dict[int, tuple[float, str]] = {}
    for registrant in sec_registrants.registrant_chain(cik):
        for tag in tags:
            for year, fact in annual_facts(fetch_concept(registrant, tag), unit).items():
                merged.setdefault(year, fact)
    return dict(sorted(merged.items()))


def annual_period_ends(cik: str, tags: Sequence[str], unit: str = "USD") -> dict[int, str]:
    """Calendar year → the ISO date that fiscal year ended, from the same
    annual frames ``annual_series_with_filed`` reads (and the same
    registrant chain). A year-end price needs the date: Apple's CY2025
    ended on 27 September 2025, Nvidia's on 25 January 2026."""
    ends: dict[int, str] = {}
    for registrant in sec_registrants.registrant_chain(cik):
        for tag in tags:
            for fact in fetch_concept(registrant, tag).get("units", {}).get(unit, []):
                frame = fact.get("frame", "")
                end = str(fact.get("end", ""))
                if len(frame) == 6 and frame.startswith("CY") and frame[2:].isdigit() and end:
                    ends.setdefault(int(frame[2:]), end)
    return dict(sorted(ends.items()))
