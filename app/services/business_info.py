"""
Business-info tool. Phase 4.4.A.

Surfaces yfinance ``Ticker.info`` fields (longBusinessSummary,
city/state/country, fullTimeEmployees) as a ``dict[str, Claim]`` keyed
by stable claim ids. The orchestrator's section builder for the
Business section passes them through unchanged.

## Why a separate tool from fetch_fundamentals

``fetch_fundamentals`` already pulls some ``Ticker.info`` fields
(market cap, 52-week band, name, sector tag) but its output is
purpose-built for the Valuation / Quality / Capital Allocation
sections. The Business card surfaces a different slice — prose +
location + employee count — that doesn't fit those section
groupings. Keeping the tool separate keeps the section catalog one-
to-one with its data source and makes the Business section easy to
scope under the EARNINGS focus mode (where it's omitted).

## Failure modes

Provider unavailable / unknown → ``ValueError`` raised before any
work. yfinance returning an info dict missing the requested keys →
the affected Claims land with ``value=None``; downstream the section
builder still emits them so the section's shape is stable.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, Source

# Stable claim ids — the section builder filters on these.
CLAIM_KEYS: tuple[str, ...] = ("summary", "hq", "employee_count")

_DESCRIPTIONS: dict[str, str] = {
    "summary": "Business description (from 10-K filing)",
    "hq": "Headquarters location",
    "employee_count": "Full-time employee count",
}

# Per-claim Source.detail. The strings flow into the report as part of
# the citation; format mirrors fundamentals.py's "info.<key>" style.
_DETAILS: dict[str, str] = {
    "summary": "info.longBusinessSummary",
    "hq": "computed: info.city + info.state + info.country",
    "employee_count": "info.fullTimeEmployees",
}

# Display unit hint per claim (Phase 4.3.X — the frontend formatter
# dispatches by unit; per-share dollars/strings/counts each render
# differently). Strings + counts are the only categories here.
_UNITS: dict[str, str] = {
    "summary": "string",
    "hq": "string",
    "employee_count": "count",
}

# Sanity-check: keep the per-key dicts in lock-step.
assert set(_DESCRIPTIONS) == set(CLAIM_KEYS)
assert set(_DETAILS) == set(CLAIM_KEYS)
assert set(_UNITS) == set(CLAIM_KEYS)


# Provider signature: (symbol) -> dict[str, Any]. Sync — yfinance is
# blocking. Tests register a fake under "fake".
Provider = Callable[[str], dict[str, Any]]


def _fetch_yfinance_info(symbol: str) -> dict[str, Any]:
    """Pull ``Ticker.info`` for ``symbol``. Lazy import so the test
    suite can swap in a fake without paying yfinance's pandas / numpy
    cost at module load."""
    import yfinance  # noqa: PLC0415  (intentional lazy import)

    ticker = yfinance.Ticker(symbol)
    return dict(ticker.info)


PROVIDERS: dict[str, Provider] = {
    "yfinance": _fetch_yfinance_info,
}


def _join_hq(info: dict[str, Any]) -> str | None:
    """Combine info.city / state / country into a single comma-
    separated location string. Drops missing components silently —
    e.g. a non-US filer often has no `state`."""
    parts: list[str] = []
    for key in ("city", "state", "country"):
        v = info.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    if not parts:
        return None
    return ", ".join(parts)


async def fetch_business_info(
    symbol: str,
    *,
    provider: str = "yfinance",
) -> dict[str, Claim]:
    """Pull business-info Claims for ``symbol``. See module docstring."""
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    service_id = f"{provider}.business_info"

    with log_external_call(
        service_id,
        {"symbol": target, "provider": provider},
    ) as call:
        info = await asyncio.to_thread(fetch, target)
        call.record_output(
            {
                "has_summary": bool(
                    isinstance(info.get("longBusinessSummary"), str)
                    and info.get("longBusinessSummary")
                ),
                "has_hq": bool(_join_hq(info)),
                "employee_count_present": isinstance(
                    info.get("fullTimeEmployees"), int
                ),
            }
        )

    fetched_at = datetime.now(UTC)

    summary = info.get("longBusinessSummary")
    if not isinstance(summary, str):
        summary = None

    hq = _join_hq(info)

    employee_count = info.get("fullTimeEmployees")
    if not isinstance(employee_count, int) or isinstance(employee_count, bool):
        employee_count = None

    raw: dict[str, Any] = {
        "summary": summary,
        "hq": hq,
        "employee_count": employee_count,
    }

    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_DESCRIPTIONS[key],
            value=raw[key],
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=_DETAILS[key],
            ),
            unit=_UNITS[key],  # type: ignore[arg-type]
        )
    return out
