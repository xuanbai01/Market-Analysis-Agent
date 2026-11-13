"""
The version of what a research report contains.

Cached reports are served for up to ``RESEARCH_CACHE_MAX_AGE_HOURS`` (7
days by default). Until 2026-11-10 a fix that changed report content —
corrected earnings dates, new claims, a prompt change — reached a ticker
only when someone pressed Regenerate. Every report now carries
``report_version``; the research route treats a cached report older than
``REPORT_VERSION`` as a miss and rebuilds it on its next visit (serving
the old one only when the rebuild can't run).

**Bump ``REPORT_VERSION`` in the same PR as any change that alters what a
fresh report would contain** — tool output, claims, units, derived
claims, prompts, the thesis, layout signals. Pure frontend changes and
refactors that leave reports identical don't need a bump. Each bump costs
one fresh report per ticker on its next visit.

History:
    0  Reports cached before versioning (the field's default).
    1  2026-11-10 — corrected earnings next date, next-quarter consensus
       and quarter labels (#83); titled analyst-view points (#84).
    2  2026-11-10 — ten years of annual per-share history from SEC filings
       (revenue, operating income, FCF, diluted EPS) and their compound
       annual growth, in the Quality section; FRED values carry units, so
       Macro prose reads "$745.02B" rather than "745021.0".
    3  2026-11-13 — fixes from the XOM check: filings and annual facts
       follow a successor registrant back to its predecessor; a tool
       that found nothing is audited "empty"; oil and gas peers split
       into integrated majors and producers; gross margin's snapshot
       is the latest quarter of its history, with Yahoo's trailing
       figure as a separate Valuation claim for the peer comparison.
    4  2026-11-13 — valuation against the company's own history: P/E,
       price-to-sales and price-to-free-cash-flow at each fiscal
       year-end, their medians, and today's trailing multiples as a
       premium or discount to them, in the Valuation section.
"""
from __future__ import annotations

from app.schemas.research import ResearchReport

REPORT_VERSION = 4


def is_outdated(report: ResearchReport) -> bool:
    """True for a report built before the current version."""
    return report.report_version < REPORT_VERSION
