"""
Cross-company lenses — how a metric is distributed across a group of
companies, and what that distribution says (ADR 0007 layer 3).

The first lens: **megacap tech capex**. For the seven largest US tech
companies over ten years (SEC XBRL annual filings): capital spending,
capex intensity (capex ÷ revenue) and capex ÷ operating cash flow; per
year, the distribution of intensity across the group (median, quartiles,
the companies at each end, total spend); and an AI narrative that cites
computed facts under the same rules as the dashboard prose.

The window is the ten years ending at the latest year *every* company
has filed — a partly-filed year would change who is in the median.
Companies missing a year (NVDA before 2021) drop out of that year's
statistics, and each year records how many companies it covers.

Results are cached in memory for a day; XBRL responses are also cached
on disk (``xbrl``). A failed rebuild serves the previous result.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from app.core.observability import log_external_call
from app.schemas.lens import (
    LensCompany,
    LensDraft,
    LensNarrative,
    LensPoint,
    LensReport,
    LensSummary,
    LensYearStats,
)
from app.schemas.research import Claim, ClaimRef, ClaimUnit, Source
from app.services import llm, research_thesis, xbrl
from app.services.claim_display import format_claim_line

logger = logging.getLogger(__name__)

WINDOW_YEARS = 10
CACHE_TTL_SECONDS = 24 * 3600
MAX_NARRATIVE_POINTS = 5
LENS_SECTION = "Lens"

# Ordered tag preferences per metric (shared with the per-share history
# tool); ``xbrl.annual_series`` merges them year by year.
CAPEX_TAGS = xbrl.CAPEX_TAGS
REVENUE_TAGS = xbrl.REVENUE_TAGS
OCF_TAGS = xbrl.OCF_TAGS

METHOD = (
    "SEC XBRL annual filings. Capex is purchases of property and equipment; "
    "fiscal years are mapped to the calendar year they best match (SEC frames), "
    "so a CY2025 value can end anywhere from mid-2025 to early 2026."
)


@dataclass(frozen=True)
class LensCompanySpec:
    ticker: str
    name: str
    cik: str


@dataclass(frozen=True)
class LensSpec:
    id: str
    title: str
    description: str
    companies: tuple[LensCompanySpec, ...]

    def summary(self) -> LensSummary:
        return LensSummary(
            id=self.id,
            title=self.title,
            description=self.description,
            tickers=[c.ticker for c in self.companies],
        )


LENSES: dict[str, LensSpec] = {
    "megacap-capex": LensSpec(
        id="megacap-capex",
        title="Megacap tech capex",
        description=(
            "How much of their revenue the seven largest US tech companies "
            "put into capital spending, and how that spending is spread "
            "across the group."
        ),
        companies=(
            LensCompanySpec("AAPL", "Apple", "0000320193"),
            LensCompanySpec("MSFT", "Microsoft", "0000789019"),
            LensCompanySpec("GOOGL", "Alphabet", "0001652044"),
            LensCompanySpec("AMZN", "Amazon", "0001018724"),
            LensCompanySpec("META", "Meta Platforms", "0001326801"),
            LensCompanySpec("NVDA", "Nvidia", "0001045810"),
            LensCompanySpec("TSLA", "Tesla", "0001318605"),
        ),
    ),
}

RawSeries = dict[str, dict[int, float]]  # metric → year → value


def list_lenses() -> list[LensSummary]:
    return [spec.summary() for spec in LENSES.values()]


# ── Fetch ────────────────────────────────────────────────────────────


def _fetch_company(company: LensCompanySpec) -> RawSeries:
    return {
        "capex": xbrl.annual_series(company.cik, CAPEX_TAGS),
        "revenue": xbrl.annual_series(company.cik, REVENUE_TAGS),
        "ocf": xbrl.annual_series(company.cik, OCF_TAGS),
    }


def fetch_raw(spec: LensSpec) -> dict[str, RawSeries]:
    """Sync (SEC pacing); swapped out in tests."""
    return {c.ticker: _fetch_company(c) for c in spec.companies}


# ── Compute ──────────────────────────────────────────────────────────


def window(raw: dict[str, RawSeries], size: int = WINDOW_YEARS) -> list[int]:
    """The ``size`` years ending at the latest year every company has
    reported both capex and revenue; [] if there is no such year."""
    common: set[int] | None = None
    for series in raw.values():
        years = set(series["capex"]) & set(series["revenue"])
        common = years if common is None else common & years
    if not common:
        return []
    latest = max(common)
    return list(range(latest - size + 1, latest + 1))


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def company_points(series: RawSeries, years: Sequence[int]) -> list[LensPoint]:
    out = []
    for year in years:
        capex = series["capex"].get(year)
        revenue = series["revenue"].get(year)
        ocf = series["ocf"].get(year)
        out.append(
            LensPoint(
                year=year,
                capex=capex,
                revenue=revenue,
                ocf=ocf,
                capex_intensity=_ratio(capex, revenue),
                capex_to_ocf=_ratio(capex, ocf),
            )
        )
    return out


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (numpy's default), q in [0, 1]."""
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def year_stats(companies: Sequence[LensCompany], years: Sequence[int]) -> list[LensYearStats]:
    out = []
    for i, year in enumerate(years):
        rows = [
            (c.ticker, c.points[i].capex_intensity, c.points[i].capex or 0.0)
            for c in companies
            if c.points[i].capex_intensity is not None
        ]
        if not rows:
            continue
        intensities = [r[1] for r in rows]
        low = min(rows, key=lambda r: r[1])
        high = max(rows, key=lambda r: r[1])
        out.append(
            LensYearStats(
                year=year,
                companies=len(rows),
                median=percentile(intensities, 0.5),
                p25=percentile(intensities, 0.25),
                p75=percentile(intensities, 0.75),
                low=low[1],
                low_ticker=low[0],
                high=high[1],
                high_ticker=high[0],
                total_capex=sum(r[2] for r in rows),
            )
        )
    return out


def _fact(description: str, value: float, unit: ClaimUnit, detail: str) -> Claim:
    tool = "sec.xbrl" if detail.startswith("XBRL") else "computed.analytics"
    return Claim(
        description=description,
        value=value,
        unit=unit,
        source=Source(tool=tool, fetched_at=datetime.now(UTC), detail=detail),
    )


def lens_facts(companies: Sequence[LensCompany], stats: Sequence[LensYearStats]) -> list[Claim]:
    """The numbers the narrative may cite: the group's distribution then and
    now, growth of spend vs revenue, concentration, and each company's
    position. All computed here so the model never does arithmetic."""
    if not stats:
        return []
    first, last = stats[0], stats[-1]
    y0, y1 = first.year, last.year
    facts = [
        _fact(f"Median capex intensity (capex ÷ revenue), CY{y1}, {last.companies} companies",
              last.median, "fraction", "median of capex/revenue across companies"),
        _fact(f"Median capex intensity, CY{y0}, {first.companies} companies",
              first.median, "fraction", "median of capex/revenue across companies"),
        _fact(f"Change in median capex intensity, CY{y0} → CY{y1}",
              last.median - first.median, "percentage_points", "median[last] − median[first]"),
        _fact(f"25th percentile capex intensity, CY{y1}", last.p25, "fraction", "linear-interpolated percentile"),
        _fact(f"75th percentile capex intensity, CY{y1}", last.p75, "fraction", "linear-interpolated percentile"),
        _fact(f"Highest capex intensity, CY{y1}: {last.high_ticker}", last.high, "fraction", "max of capex/revenue"),
        _fact(f"Lowest capex intensity, CY{y1}: {last.low_ticker}", last.low, "fraction", "min of capex/revenue"),
        _fact(f"Total capex, {last.companies} companies, CY{y1}", last.total_capex, "usd", "sum of capex"),
    ]

    # Growth of spend vs revenue, over the companies reporting both years
    # (a company joining mid-window would inflate the total).
    both = [c for c in companies if c.points[0].capex_intensity is not None and c.points[-1].capex_intensity is not None]
    if both:
        capex0 = sum(c.points[0].capex or 0.0 for c in both)
        capex1 = sum(c.points[-1].capex or 0.0 for c in both)
        rev0 = sum(c.points[0].revenue or 0.0 for c in both)
        rev1 = sum(c.points[-1].revenue or 0.0 for c in both)
        tickers = ", ".join(c.ticker for c in both)
        if capex0 > 0 and rev0 > 0:
            facts += [
                _fact(f"Total capex growth, CY{y0} → CY{y1} (multiple; {tickers})",
                      capex1 / capex0, "ratio", "Σ capex[last] / Σ capex[first]"),
                _fact(f"Total revenue growth, CY{y0} → CY{y1} (multiple; {tickers})",
                      rev1 / rev0, "ratio", "Σ revenue[last] / Σ revenue[first]"),
            ]

    # Concentration: share of the year's spend from the four largest spenders.
    latest = sorted(
        ((c.ticker, c.points[-1].capex or 0.0) for c in companies if c.points[-1].capex),
        key=lambda r: r[1],
        reverse=True,
    )
    if len(latest) > 4 and last.total_capex > 0:
        top = latest[:4]
        facts.append(_fact(
            f"Share of CY{y1} capex from the four largest spenders ({', '.join(t for t, _ in top)})",
            sum(v for _, v in top) / last.total_capex, "fraction", "Σ top-4 capex / total capex",
        ))

    # Each company's position, highest intensity first.
    ranked = sorted(
        (c for c in companies if c.points[-1].capex_intensity is not None),
        key=lambda c: c.points[-1].capex_intensity or 0.0,
        reverse=True,
    )
    for c in ranked:
        now = c.points[-1]
        facts.append(_fact(f"{c.ticker} capex intensity, CY{y1}", now.capex_intensity or 0.0, "fraction",
                           "XBRL capex / revenue"))
        facts.append(_fact(f"{c.ticker} capex, CY{y1}", now.capex or 0.0, "usd", "XBRL capex"))
        if now.capex_to_ocf is not None:
            facts.append(_fact(f"{c.ticker} capex ÷ operating cash flow, CY{y1}", now.capex_to_ocf, "fraction",
                               "XBRL capex / operating cash flow"))
        start = next((p for p in c.points if p.capex_intensity is not None), None)
        if start is not None and start.year != now.year:
            facts.append(_fact(
                f"{c.ticker} capex intensity change, CY{start.year} → CY{y1}",
                (now.capex_intensity or 0.0) - (start.capex_intensity or 0.0),
                "percentage_points",
                "intensity[last] − intensity[first reported]",
            ))
    return facts


# ── Narrative ────────────────────────────────────────────────────────

LENS_SYSTEM_PROMPT = """\
You are an equity analyst explaining what a cross-company distribution \
shows. The user gives computed facts about one metric across a group of \
companies over ten years; each line starts with an id in brackets ("[L3]"). \
Write:

- ``headline``: one sentence — the main pattern: the level, how spread out \
the group is, the trend, or how concentrated the spending is.
- ``points``: 3–5 points, each one or two sentences and at most 40 words. \
Cover how the typical company moved, who sits at each end and how far \
apart they are, whether spending is concentrated, how spend grew against \
revenue, and what the numbers imply for cash flow (capex against \
operating cash flow). Each point lists in ``claim_ids`` the 1–3 ids of \
the facts it quotes, exactly as written in the brackets.

Rules (non-negotiable):
1. Every number in your text must be a value shown in the fact lines, in \
the display units shown. Never compute a number yourself.
2. For a signed change, say the direction in words and drop the sign.
3. No outside facts: explain what the numbers imply, not why they \
happened — no products, technologies, events, management actions or \
macro causes. Whatever you know about these companies from elsewhere \
stays out.
4. No forecasts, price targets or advice. Plain prose, no markdown.
"""


async def write_narrative(spec: LensSpec, facts: Sequence[Claim]) -> LensNarrative | None:
    """The AI read of the distribution; None on any failure."""
    if not facts:
        return None
    ids = {f"L{i + 1}": ClaimRef(section=LENS_SECTION, index=i) for i in range(len(facts))}
    lines = [f"Lens: {spec.title}", f"Companies: {', '.join(c.ticker for c in spec.companies)}", ""]
    lines += [format_claim_line(fact, claim_id=f"L{i + 1}") for i, fact in enumerate(facts)]
    try:
        draft: Any = await llm.synth_call(prompt="\n".join(lines), schema=LensDraft, system=LENS_SYSTEM_PROMPT)
    except Exception:
        logger.exception("lens narrative failed for %s", spec.id)
        return None
    if not isinstance(draft, LensDraft) or not draft.headline.strip():
        return None
    points = research_thesis.resolve_points(draft.points, ids, MAX_NARRATIVE_POINTS, {LENS_SECTION: list(facts)})
    if not points:
        return None
    return LensNarrative(headline=draft.headline.strip(), points=points)


# ── Build + cache ────────────────────────────────────────────────────


async def build_lens(spec: LensSpec) -> LensReport:
    with log_external_call("sec.xbrl.companyconcept", {"lens": spec.id, "companies": len(spec.companies)}) as call:
        raw = await asyncio.to_thread(fetch_raw, spec)
        call.record_output({"companies_returned": len(raw)})
    years = window(raw)
    companies = [
        LensCompany(ticker=c.ticker, name=c.name, points=company_points(raw[c.ticker], years))
        for c in spec.companies
        if c.ticker in raw
    ]
    stats = year_stats(companies, years)
    facts = lens_facts(companies, stats)
    narrative = await write_narrative(spec, facts)
    summary = spec.summary()
    return LensReport(
        **summary.model_dump(),
        method=METHOD,
        years=years,
        companies=companies,
        stats=stats,
        facts=facts,
        narrative=narrative,
        generated_at=datetime.now(UTC),
    )


@dataclass
class _Entry:
    report: LensReport
    expires_at: float


_cache: dict[str, _Entry] = {}


def clear_cache() -> None:
    _cache.clear()


async def get_lens(lens_id: str) -> LensReport | None:
    """The lens, from cache when fresh; None for an unknown id. A failed
    rebuild serves the stale copy when there is one, else raises."""
    spec = LENSES.get(lens_id)
    if spec is None:
        return None
    now = monotonic()
    entry = _cache.get(lens_id)
    if entry and entry.expires_at > now:
        return entry.report
    try:
        report = await build_lens(spec)
    except Exception:
        if entry:
            logger.exception("lens %s rebuild failed; serving the cached copy", lens_id)
            return entry.report
        raise
    _cache[lens_id] = _Entry(report, now + CACHE_TTL_SECONDS)
    return report
