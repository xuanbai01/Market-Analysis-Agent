"""
Cross-company lenses — how a metric is distributed across a group of
companies, and what that distribution says (ADR 0007 layer 3).

A lens (``lens_catalog``) is one metric across one group: megacap capex,
stock-based compensation, R&D. For each company over ten years (SEC XBRL
annual filings): the metric in dollars, its intensity (÷ revenue) and its
share of operating cash flow; per year, the distribution of intensity
across the group (median, quartiles, the companies at each end, the
total); and an AI narrative that cites computed facts under the same
rules as the dashboard prose.

The window is the ten years ending at the latest year *every* company
has filed — a partly-filed year would change who is in the median.
Companies missing a year (NVDA before 2021) drop out of that year's
statistics, and each year records how many companies it covers. A
company that never tagged the metric (Amazon's R&D) is left out of the
lens and named in ``excluded`` and the method note.

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
from app.services.lens_catalog import (  # re-exported: callers and tests use lens.*
    CAPEX,
    LENSES,
    RND,
    SBC,
    LensCompanySpec,
    LensMetric,
    LensSpec,
)

logger = logging.getLogger(__name__)

WINDOW_YEARS = 10
CACHE_TTL_SECONDS = 24 * 3600
MAX_NARRATIVE_POINTS = 5
LENS_SECTION = "Lens"

REVENUE_TAGS = xbrl.REVENUE_TAGS
OCF_TAGS = xbrl.OCF_TAGS

METHOD = (
    "SEC XBRL annual filings. {definition} Fiscal years are mapped to the calendar "
    "year they best match (SEC frames), so a CY2025 value can end anywhere from "
    "mid-2025 to early 2026."
)

__all__ = ["CAPEX", "LENSES", "RND", "SBC", "LensCompanySpec", "LensMetric", "LensSpec"]

RawSeries = dict[str, dict[int, float]]  # "value" | "revenue" | "ocf" → year → USD


def list_lenses() -> list[LensSummary]:
    return [spec.summary() for spec in LENSES.values()]


# ── Fetch ────────────────────────────────────────────────────────────


def _fetch_company(company: LensCompanySpec, metric: LensMetric) -> RawSeries:
    return {
        "value": xbrl.annual_series(company.cik, metric.tags),
        "revenue": xbrl.annual_series(company.cik, REVENUE_TAGS),
        "ocf": xbrl.annual_series(company.cik, OCF_TAGS),
    }


def fetch_raw(spec: LensSpec) -> dict[str, RawSeries]:
    """Sync (SEC pacing); swapped out in tests."""
    return {c.ticker: _fetch_company(c, spec.metric) for c in spec.companies}


# ── Compute ──────────────────────────────────────────────────────────


def without_figures(raw: dict[str, RawSeries]) -> list[str]:
    """Companies that never tagged the lens's metric: left out of the lens."""
    return [ticker for ticker, series in raw.items() if not series["value"]]


def window(raw: dict[str, RawSeries], size: int = WINDOW_YEARS) -> list[int]:
    """The ``size`` years ending at the latest year every company with a
    figure for the metric has reported both it and revenue; [] if there is
    no such year."""
    common: set[int] | None = None
    for series in raw.values():
        if not series["value"]:
            continue
        years = set(series["value"]) & set(series["revenue"])
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
        value = series["value"].get(year)
        revenue = series["revenue"].get(year)
        ocf = series["ocf"].get(year)
        out.append(
            LensPoint(
                year=year,
                value=value,
                revenue=revenue,
                ocf=ocf,
                intensity=_ratio(value, revenue),
                to_ocf=_ratio(value, ocf),
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
            (c.ticker, c.points[i].intensity, c.points[i].value or 0.0)
            for c in companies
            if c.points[i].intensity is not None
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
                total=sum(r[2] for r in rows),
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


def lens_facts(
    metric: LensMetric, companies: Sequence[LensCompany], stats: Sequence[LensYearStats]
) -> list[Claim]:
    """The numbers the narrative may cite: the group's distribution then and
    now, growth of the metric vs revenue, concentration, and each company's
    position. All computed here so the model never does arithmetic."""
    if not stats:
        return []
    m = metric.short
    first, last = stats[0], stats[-1]
    y0, y1 = first.year, last.year
    facts = [
        _fact(f"Median {m} intensity ({m} ÷ revenue), CY{y1}, {last.companies} companies",
              last.median, "fraction", f"median of {m}/revenue across companies"),
        _fact(f"Median {m} intensity, CY{y0}, {first.companies} companies",
              first.median, "fraction", f"median of {m}/revenue across companies"),
        _fact(f"Change in median {m} intensity, CY{y0} → CY{y1}",
              last.median - first.median, "percentage_points", "median[last] − median[first]"),
        _fact(f"25th percentile {m} intensity, CY{y1}", last.p25, "fraction", "linear-interpolated percentile"),
        _fact(f"75th percentile {m} intensity, CY{y1}", last.p75, "fraction", "linear-interpolated percentile"),
        _fact(f"Highest {m} intensity, CY{y1}: {last.high_ticker}", last.high, "fraction", f"max of {m}/revenue"),
        _fact(f"Lowest {m} intensity, CY{y1}: {last.low_ticker}", last.low, "fraction", f"min of {m}/revenue"),
        _fact(f"Total {m}, {last.companies} companies, CY{y1}", last.total, "usd", f"sum of {m}"),
    ]

    # Growth of the metric vs revenue, over the companies reporting both
    # years (a company joining mid-window would inflate the total).
    both = [c for c in companies if c.points[0].intensity is not None and c.points[-1].intensity is not None]
    if both:
        value0 = sum(c.points[0].value or 0.0 for c in both)
        value1 = sum(c.points[-1].value or 0.0 for c in both)
        rev0 = sum(c.points[0].revenue or 0.0 for c in both)
        rev1 = sum(c.points[-1].revenue or 0.0 for c in both)
        tickers = ", ".join(c.ticker for c in both)
        if value0 > 0 and rev0 > 0:
            facts += [
                _fact(f"Total {m} growth, CY{y0} → CY{y1} (multiple; {tickers})",
                      value1 / value0, "ratio", f"Σ {m}[last] / Σ {m}[first]"),
                _fact(f"Total revenue growth, CY{y0} → CY{y1} (multiple; {tickers})",
                      rev1 / rev0, "ratio", "Σ revenue[last] / Σ revenue[first]"),
            ]

    # Concentration: share of the year's total from the four largest.
    latest = sorted(
        ((c.ticker, c.points[-1].value or 0.0) for c in companies if c.points[-1].value),
        key=lambda r: r[1],
        reverse=True,
    )
    if len(latest) > 4 and last.total > 0:
        top = latest[:4]
        facts.append(_fact(
            f"Share of CY{y1} {m} from the four largest ({', '.join(t for t, _ in top)})",
            sum(v for _, v in top) / last.total, "fraction", f"Σ top-4 {m} / total {m}",
        ))

    # Each company's position, highest intensity first.
    ranked = sorted(
        (c for c in companies if c.points[-1].intensity is not None),
        key=lambda c: c.points[-1].intensity or 0.0,
        reverse=True,
    )
    for c in ranked:
        now = c.points[-1]
        facts.append(_fact(f"{c.ticker} {m} intensity, CY{y1}", now.intensity or 0.0, "fraction",
                           f"XBRL {m} / revenue"))
        facts.append(_fact(f"{c.ticker} {m}, CY{y1}", now.value or 0.0, "usd", f"XBRL {m}"))
        if now.to_ocf is not None:
            facts.append(_fact(f"{c.ticker} {m} ÷ operating cash flow, CY{y1}", now.to_ocf, "fraction",
                               f"XBRL {m} / operating cash flow"))
        start = next((p for p in c.points if p.intensity is not None), None)
        if start is not None and start.year != now.year:
            facts.append(_fact(
                f"{c.ticker} {m} intensity change, CY{start.year} → CY{y1}",
                (now.intensity or 0.0) - (start.intensity or 0.0),
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
the group is, the trend, or how concentrated the total is.
- ``points``: 3–5 points, each one or two sentences and at most 40 words. \
Cover how the typical company moved, who sits at each end and how far \
apart they are, whether the total is concentrated, how the metric grew \
against revenue, and what the numbers imply for cash flow (the metric \
against operating cash flow). Each point lists in ``claim_ids`` the 1–3 ids of \
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
    lines = [
        f"Lens: {spec.title}",
        f"Metric: {spec.metric.definition}",
        f"Companies: {', '.join(c.ticker for c in spec.companies)}",
        "",
    ]
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
    excluded = without_figures(raw)
    companies = [
        LensCompany(ticker=c.ticker, name=c.name, points=company_points(raw[c.ticker], years))
        for c in spec.companies
        if c.ticker in raw and c.ticker not in excluded
    ]
    stats = year_stats(companies, years)
    facts = lens_facts(spec.metric, companies, stats)
    narrative = await write_narrative(spec, facts)
    return LensReport(
        **spec.summary().model_dump(),
        method=_method(spec.metric, excluded),
        years=years,
        companies=companies,
        stats=stats,
        facts=facts,
        narrative=narrative,
        generated_at=datetime.now(UTC),
        excluded=excluded,
    )


def _method(metric: LensMetric, excluded: Sequence[str]) -> str:
    method = METHOD.format(definition=metric.definition)
    if excluded:
        method += (
            f" Not in this lens, for lack of a {metric.short} figure in their SEC filings: "
            f"{', '.join(excluded)}."
        )
    return method


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
