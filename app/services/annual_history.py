"""
Annual per-share history from SEC XBRL filings (2026-11).

yfinance's quarterly statements stop at about five quarters, so the
dashboard's per-share growth card could only say "+7.4% year over year".
Companies' 10-K facts on SEC go back a decade and more; this tool turns
them into four annual per-share series, up to eleven years (ten years of
growth):

    revenue_per_share_annual            revenue ÷ diluted shares
    operating_income_per_share_annual   operating income ÷ diluted shares
    fcf_per_share_annual                (operating cash flow − capex) ÷ diluted shares
    eps_diluted_annual                  reported diluted EPS

**Stock splits.** XBRL values are as filed. A framed fact is the latest
filing for that period, so it reflects the splits before its filing date
and none after: NVDA's CY2018 diluted shares (filed Feb 2021) are 625M,
before its 4:1 (2021) and 10:1 (2024) splits. Share counts are multiplied,
and EPS divided, by every split dated after the fact's filing (splits from
yfinance). As a guard against a missing split, a year-over-year share
count jump beyond 1.6× cuts the history at the jump rather than show a
fake collapse.

Years are the SEC's calendar frames (``CY2025`` is the ~365-day fiscal
year best matching calendar 2025; NVDA's year ending Jan 2026 is CY2025).
Banks get revenue and EPS only: they don't report operating income, and
free cash flow says nothing about a bank (ADR 0007).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, ClaimHistoryPoint, Source
from app.services import edgar, xbrl

CLAIM_KEYS: tuple[str, ...] = (
    "revenue_per_share_annual",
    "operating_income_per_share_annual",
    "fcf_per_share_annual",
    "eps_diluted_annual",
)

DESCRIPTIONS: dict[str, str] = {
    "revenue_per_share_annual": "Revenue per share, annual (SEC filings)",
    "operating_income_per_share_annual": "Operating income per share, annual (SEC filings)",
    "fcf_per_share_annual": "Free cash flow per share, annual (SEC filings)",
    "eps_diluted_annual": "Diluted EPS, annual (SEC filings)",
}

_DETAILS: dict[str, str] = {
    "revenue_per_share_annual": "us-gaap revenue ÷ diluted weighted shares, split-adjusted, calendar-year frames",
    "operating_income_per_share_annual": "us-gaap OperatingIncomeLoss ÷ diluted weighted shares, split-adjusted",
    "fcf_per_share_annual": "(operating cash flow − capex) ÷ diluted weighted shares, split-adjusted",
    "eps_diluted_annual": "us-gaap EarningsPerShareDiluted, split-adjusted",
}

assert set(DESCRIPTIONS) == set(CLAIM_KEYS) == set(_DETAILS)

TOOL = "sec.xbrl"
MAX_POINTS = 11  # eleven annual points = ten years of growth
MAX_SHARE_JUMP = 1.6
GOODS_REVENUE_TAG = "SalesRevenueGoodsNet"
SERVICES_REVENUE_TAG = "SalesRevenueServicesNet"

# Raw facts: per metric, calendar year → (value, filing date), plus the
# splits as (ISO date, ratio).
Facts = Mapping[int, tuple[float, str]]
Raw = dict[str, Any]
Provider = Callable[[str], Raw]


def _fetch_sec(symbol: str) -> Raw:
    """SEC facts for ``symbol`` and its split history. Sync; run in a thread.

    Raises ``ValueError`` for a ticker SEC doesn't know (foreign filers,
    funds) — the orchestrator records the tool as failed and the card
    falls back to the quarterly view.
    """
    cik = edgar._resolve_cik(symbol)
    return {
        "revenue": _revenue(cik),
        "operating_income": xbrl.annual_series_with_filed(cik, xbrl.OPERATING_INCOME_TAGS),
        "ocf": xbrl.annual_series_with_filed(cik, xbrl.OCF_TAGS),
        "capex": xbrl.annual_series_with_filed(cik, xbrl.CAPEX_TAGS),
        "shares": xbrl.annual_series_with_filed(cik, xbrl.DILUTED_SHARES_TAGS, "shares"),
        "eps": xbrl.annual_series_with_filed(cik, xbrl.DILUTED_EPS_TAGS, "USD/shares"),
        "splits": _splits(symbol),
    }


def _revenue(cik: str) -> dict[int, tuple[float, str]]:
    return merge_goods_revenue(
        xbrl.annual_series_with_filed(cik, xbrl.REVENUE_TAGS),
        goods=xbrl.annual_series_with_filed(cik, (GOODS_REVENUE_TAG,)),
        services=xbrl.annual_series_with_filed(cik, (SERVICES_REVENUE_TAG,)),
    )


def merge_goods_revenue(
    revenue: dict[int, tuple[float, str]],
    *,
    goods: dict[int, tuple[float, str]],
    services: dict[int, tuple[float, str]],
) -> dict[int, tuple[float, str]]:
    """Fill years the revenue tags miss with goods revenue — but only
    where no services revenue was filed for the year, since goods alone is
    then a part of revenue (Apple's products line), not all of it. Coca-
    Cola tagged its whole revenue ``SalesRevenueGoodsNet`` until 2016."""
    merged = dict(revenue)
    for year, fact in goods.items():
        if year not in merged and year not in services:
            merged[year] = fact
    return dict(sorted(merged.items()))


def _splits(symbol: str) -> list[tuple[str, float]]:
    """(ISO date, ratio) for every split yfinance knows. [] on any failure;
    the share-jump guard then protects the series."""
    import yfinance  # noqa: PLC0415  (lazy: tests swap in a fake provider)

    try:
        series = yfinance.Ticker(symbol).splits
        return [(ts.date().isoformat(), float(ratio)) for ts, ratio in series.items() if float(ratio) > 0]
    except Exception:  # noqa: BLE001 — a missing split list is not fatal
        return []


PROVIDERS: dict[str, Provider] = {"sec": _fetch_sec}


def _split_factor(filed: str, splits: list[tuple[str, float]]) -> float:
    """Product of the split ratios dated after ``filed``."""
    factor = 1.0
    if not filed:
        return factor
    for date, ratio in splits:
        if date > filed:
            factor *= ratio
    return factor


def _adjusted_shares(raw: Raw) -> dict[int, float]:
    splits = raw.get("splits") or []
    shares = {
        year: value * _split_factor(filed, splits)
        for year, (value, filed) in sorted(raw.get("shares", {}).items())
        if value > 0
    }
    # A jump beyond MAX_SHARE_JUMP is an unadjusted split (or a merger):
    # keep only the years after the last one.
    years = sorted(shares)
    start = years[0] if years else 0
    for prev, year in zip(years, years[1:], strict=False):
        ratio = shares[year] / shares[prev]
        if ratio > MAX_SHARE_JUMP or ratio < 1 / MAX_SHARE_JUMP:
            start = year
    return {year: value for year, value in shares.items() if year >= start}


def per_share_series(raw: Raw) -> dict[str, list[ClaimHistoryPoint]]:
    """The four annual per-share series over the latest ``MAX_POINTS``
    years that have both revenue and a share count."""
    shares = _adjusted_shares(raw)
    revenue: Facts = raw.get("revenue", {})
    operating_income: Facts = raw.get("operating_income", {})
    ocf: Facts = raw.get("ocf", {})
    capex: Facts = raw.get("capex", {})
    eps: Facts = raw.get("eps", {})
    splits = raw.get("splits") or []

    window = sorted(set(revenue) & set(shares))[-MAX_POINTS:]
    out: dict[str, list[ClaimHistoryPoint]] = {key: [] for key in CLAIM_KEYS}
    for year in window:
        sh = shares[year]
        period = str(year)
        out["revenue_per_share_annual"].append(ClaimHistoryPoint(period=period, value=revenue[year][0] / sh))
        if year in operating_income:
            out["operating_income_per_share_annual"].append(
                ClaimHistoryPoint(period=period, value=operating_income[year][0] / sh)
            )
        if year in ocf and year in capex:
            out["fcf_per_share_annual"].append(
                ClaimHistoryPoint(period=period, value=(ocf[year][0] - abs(capex[year][0])) / sh)
            )
        if year in eps:
            value, filed = eps[year]
            out["eps_diluted_annual"].append(
                ClaimHistoryPoint(period=period, value=value / _split_factor(filed, splits))
            )
    return out


def build_claims(
    series: Mapping[str, list[ClaimHistoryPoint]],
    fetched_at: datetime | None = None,
) -> dict[str, Claim]:
    """One claim per key; a series with fewer than two points has no value
    and no history (stable shape — every key is always present)."""
    at = fetched_at or datetime.now(UTC)
    claims: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        points = list(series.get(key, []))
        if len(points) < 2:
            points = []
        claims[key] = Claim(
            description=DESCRIPTIONS[key],
            value=points[-1].value if points else None,
            unit="usd_per_share",
            source=Source(tool=TOOL, fetched_at=at, detail=_DETAILS[key]),
            history=points,
        )
    return claims


async def fetch_annual_history(symbol: str, *, provider: str = "sec") -> dict[str, Claim]:
    """Annual per-share claims for ``symbol``. See module docstring."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}")
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    with log_external_call(f"{TOOL}.annual_history", {"symbol": target, "provider": provider}) as call:
        raw = await asyncio.to_thread(fetch, target)
        series = per_share_series(raw)
        call.record_output({key: len(points) for key, points in series.items()})
    return build_claims(series)
