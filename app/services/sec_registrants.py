"""
Which SEC registrants hold a company's filing history.

SEC's ticker file maps a ticker to one registrant (a CIK), and filings and
XBRL facts are stored per registrant. When a company reorganizes under a
new holding company, the ticker moves to a new registrant that starts
with no 10-K and no annual facts; everything filed before stays under the
old one.

Found 2026-11-13 (tasks/dogfood-2026-11.md #18): after Exxon's 1 July
2026 reorganization XOM resolved to ExxonMobil Holdings Corp, which had
filed two 10-Qs and nothing else useful, so the 10-K risk card and the
ten-year per-share history disappeared while every tool reported success.

SEC publishes no machine-readable link between the two registrants: the
succession is an 8-K12B whose header names only the new one. So the
links are kept here by hand. Check a new entry against
``https://data.sec.gov/submissions/CIK<cik>.json`` for both registrants
(the successor lists an ``8-K12B``; the predecessor holds the 10-Ks)
before adding it.

A report whose SEC-backed tools come back empty says so in
``tool_calls_audit`` and on the dashboard, which is how the next missing
entry gets noticed.
"""
from __future__ import annotations

# Successor CIK → the registrants it replaced, most recent first.
PREDECESSOR_CIKS: dict[str, tuple[str, ...]] = {
    # ExxonMobil Holdings Corp ← Exxon Mobil Corp. Holding-company
    # reorganization; 8-K12B filed 2026-07-01 (0001193125-26-291990).
    "0002115436": ("0000034088",),
}


def predecessors_of(cik: str) -> tuple[str, ...]:
    """Earlier registrants of the company now filing as ``cik``, most
    recent first. Empty for nearly every company."""
    chain: list[str] = []
    seen = {cik}
    pending = list(PREDECESSOR_CIKS.get(cik, ()))
    while pending:
        current = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        chain.append(current)
        pending.extend(PREDECESSOR_CIKS.get(current, ()))
    return tuple(chain)


def registrant_chain(cik: str) -> tuple[str, ...]:
    """``cik`` followed by its predecessors: every registrant to read for
    the company's full filing history."""
    return (cik, *predecessors_of(cik))
