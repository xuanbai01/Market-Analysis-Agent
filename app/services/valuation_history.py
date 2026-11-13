"""
Valuation multiples at each fiscal year-end (2026-11).

"Is this expensive against its own history" was the gap ADR 0004 named
first, and the Valuation card could only compare against peers. With ten
years of annual per-share figures from SEC filings
(``annual_history.py``), a multiple at a fiscal year-end is that day's
closing price over that year's figure:

    pe_annual     close ÷ diluted EPS
    ps_annual     close ÷ revenue per share
    pfcf_annual   close ÷ free cash flow per share

**Prices** are Yahoo's ``Close``, adjusted for splits and not for
dividends, so they sit on the same share basis as the split-adjusted
per-share figures. Each year is priced on the last trading day on or
before its own period end (Apple's year ends in late September, Nvidia's
in late January), read from the same XBRL facts.

**What is left out.** A year with a loss has no earnings multiple; a
multiple above ``MAX_MEANINGFUL_MULTIPLE`` (a near-zero denominator) is
dropped as not meaningful rather than drawn as a spike; a year with no
close within ``MAX_STALE_DAYS`` of its period end (the company listed
later) is skipped. Price-to-sales has no such cap.

Pure functions: ``annual_history`` fetches the inputs and wraps the
series in claims. The comparisons with today's multiples are derived
claims in ``research_derived.py``.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import date

from app.schemas.research import ClaimHistoryPoint

# multiple → the annual per-share series it divides the close by.
_DENOMINATORS: dict[str, str] = {
    "pe_annual": "eps_diluted_annual",
    "ps_annual": "revenue_per_share_annual",
    "pfcf_annual": "fcf_per_share_annual",
}
MULTIPLE_KEYS: tuple[str, ...] = tuple(_DENOMINATORS)

DESCRIPTIONS: dict[str, str] = {
    "pe_annual": "P/E at fiscal year-end (SEC filings)",
    "ps_annual": "Price-to-sales at fiscal year-end (SEC filings)",
    "pfcf_annual": "Price-to-free-cash-flow at fiscal year-end (SEC filings)",
}

DETAILS: dict[str, str] = {
    "pe_annual": (
        "close on the fiscal year's last trading day ÷ that year's diluted EPS; "
        "loss years and multiples above 200 left out"
    ),
    "ps_annual": "close on the fiscal year's last trading day ÷ that year's revenue per share",
    "pfcf_annual": (
        "close on the fiscal year's last trading day ÷ that year's free cash flow per share; "
        "negative years and multiples above 200 left out"
    ),
}

assert set(DESCRIPTIONS) == set(MULTIPLE_KEYS) == set(DETAILS)

# A close this many days before the period end still counts as that
# day's price: covers weekends, holidays and a 52/53-week year's drift.
MAX_STALE_DAYS = 10
# Above this an earnings or cash-flow multiple reflects a denominator
# near zero, not a valuation.
MAX_MEANINGFUL_MULTIPLE = 200.0
_CAPPED = frozenset({"pe_annual", "pfcf_annual"})

Closes = Sequence[tuple[str, float]]  # (ISO date, close), oldest first


def close_on_or_before(closes: Closes, day: str) -> float | None:
    """The last close dated on or before ``day`` (ISO), or None when the
    nearest one is more than ``MAX_STALE_DAYS`` earlier."""
    if not closes or not day:
        return None
    i = bisect_right(closes, day, key=lambda row: row[0])
    if i == 0:
        return None
    found, close = closes[i - 1]
    try:
        stale = (date.fromisoformat(day) - date.fromisoformat(found)).days
    except ValueError:
        return None
    return close if stale <= MAX_STALE_DAYS else None


def multiples_series(
    per_share: Mapping[str, Sequence[ClaimHistoryPoint]],
    period_ends: Mapping[int, str],
    closes: Closes,
) -> dict[str, list[ClaimHistoryPoint]]:
    """Each multiple's year-end series, one point per year that has a
    positive per-share figure, a period end and a close near it."""
    out: dict[str, list[ClaimHistoryPoint]] = {key: [] for key in MULTIPLE_KEYS}
    for key, denominator in _DENOMINATORS.items():
        for point in per_share.get(denominator, []):
            if point.value <= 0:
                continue
            close = close_on_or_before(closes, period_ends.get(int(point.period), ""))
            if close is None:
                continue
            multiple = close / point.value
            if key in _CAPPED and multiple > MAX_MEANINGFUL_MULTIPLE:
                continue
            out[key].append(ClaimHistoryPoint(period=point.period, value=multiple))
    return out
