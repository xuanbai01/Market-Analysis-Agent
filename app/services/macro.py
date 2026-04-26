"""
Macro context tool. Given a ticker, resolve to sector via the shared
``app.services.sectors`` resolver, look up a curated FRED series set
for that sector, fetch the latest observation per series, return as
flat ``dict[str, Claim]``.

Why curated sector→series rather than a generic "give me FRED data"
tool: the agent's question is "what's the macro context for this
ticker?" not "go fetch DGS10". Encoding the "rate-sensitive
long-duration tech wants the 10Y yield" judgement here, in code
that's reviewable and testable, beats expecting the LLM to pick the
right series at synth time.

Why latest value only (no history): the synth call composes one
paragraph of context; "10Y at 4.32% as of 2024-10-25" is enough for
the prose. Period-over-period change calculations are deferred —
the agent can do that math when we expose history if it ever needs
to.

Graceful degradation when ``FRED_API_KEY`` is unset: the production
provider early-returns ``{}`` (no HTTP), and the service stamps
None-valued data Claims while still emitting the metadata Claims
(``sector``, ``series_list``, per-series ``.label``). Mirrors the
NEWSAPI_KEY pattern in ``news_ingestion``.

## Why these series

| Sector | Series (FRED ids) | Why |
|---|---|---|
| semiconductors | DGS10, MANEMP | Rate-sensitive cap-ex; manufacturing employment as ISM-PMI proxy (PMI is paywalled) |
| banks | DGS10, DGS2 | Yield curve = NIM driver |
| megacap_tech, cloud_saas | DGS10 | Long-duration cash flows; rate-sensitive |
| consumer_staples, ecommerce_retail | UMCSENT, RSAFS | Consumer health |
| auto_ev | UMCSENT, DGS10 | Consumer health + financing rates |
| oil_gas | DCOILWTICO, DCOILBRENTEU | Direct revenue driver |
| pharma | DGS10 | Less macro-coupled but still rate-sensitive in valuation |
| streaming_media | UMCSENT | Discretionary spending |
| _default_ | DGS10, UNRATE, CPIAUCSL | Three macro headlines for unknown sectors |

ISM PMI and Net Interest Margin (NIM) aren't on FRED for free. NAPM
(an ISM proxy) was discontinued in 2002. ``MANEMP`` is the closest
free signal of US manufacturing health. NIM has no direct FRED proxy;
the agent infers from the yield curve.

## Excluded for v1

- Period-over-period change (YoY, MoM). Add when an eval case asks
  for "how much has X moved" specifically.
- Multi-period series history. One observation per series.
- ISM PMI, NIM, custom-computed indicators (yield curve = DGS10−DGS2).
  The agent does the subtraction at synth time.
- Custom sector mappings beyond what ``app.services.sectors``
  resolves. Keep that map authoritative.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.observability import log_external_call
from app.core.settings import settings
from app.schemas.research import Claim, ClaimValue, Source
from app.services.sectors import resolve_sector


@dataclass(frozen=True)
class FredSeries:
    """One FRED series + the human-readable label the agent can cite."""

    id: str
    label: str
    units: str = ""


# Sector → curated FRED series. Keys must match ``sectors.SECTOR_PEERS``.
SECTOR_SERIES: dict[str, list[FredSeries]] = {
    "semiconductors": [
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
        FredSeries(id="MANEMP", label="Manufacturing employment", units="thousands"),
    ],
    "banks": [
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
        FredSeries(id="DGS2", label="2Y Treasury yield", units="%"),
    ],
    "megacap_tech": [
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
    ],
    "cloud_saas": [
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
    ],
    "consumer_staples": [
        FredSeries(id="UMCSENT", label="Consumer sentiment", units="index"),
        FredSeries(id="RSAFS", label="Retail sales", units="$M"),
    ],
    "ecommerce_retail": [
        FredSeries(id="UMCSENT", label="Consumer sentiment", units="index"),
        FredSeries(id="RSAFS", label="Retail sales", units="$M"),
    ],
    "auto_ev": [
        FredSeries(id="UMCSENT", label="Consumer sentiment", units="index"),
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
    ],
    "oil_gas": [
        FredSeries(id="DCOILWTICO", label="WTI crude oil price", units="$/bbl"),
        FredSeries(id="DCOILBRENTEU", label="Brent crude oil price", units="$/bbl"),
    ],
    "pharma": [
        FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
    ],
    "streaming_media": [
        FredSeries(id="UMCSENT", label="Consumer sentiment", units="index"),
    ],
}

# Used when ``resolve_sector`` returns None — three macro headlines that
# every research report can lean on: rates, jobs, prices.
DEFAULT_SERIES: list[FredSeries] = [
    FredSeries(id="DGS10", label="10Y Treasury yield", units="%"),
    FredSeries(id="UNRATE", label="Unemployment rate", units="%"),
    FredSeries(id="CPIAUCSL", label="Consumer price index", units="index"),
]


# Provider signature: (series_ids) -> {series_id: {"value": float, "date": str}}.
# Sync — httpx.get blocks; the async entry point hands it to to_thread.
MacroProvider = Callable[[list[str]], dict[str, dict[str, Any]]]


# ── Production provider — FRED HTTP ───────────────────────────────────


_FRED_RATE_LIMIT_SLEEP_SECONDS = 0.0  # FRED's 120 req/min limit is generous


def _fetch_fred_observations(series_ids: list[str]) -> dict[str, dict[str, Any]]:
    """
    Pull the latest observation for each series id from FRED.

    Returns ``{}`` (no HTTP fired) when ``FRED_API_KEY`` is unset —
    callers degrade gracefully. One per-series HTTP call is fine within
    FRED's 120 req/min cap; if that ever bites, batch via the
    ``series/observations`` endpoint with ``observation_start`` filters.
    """
    if not settings.FRED_API_KEY:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for sid in series_ids:
        try:
            resp = httpx.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": sid,
                    "api_key": settings.FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001 — per-series isolation
            # One bad series doesn't kill the rest. Caller stamps None.
            continue

        observations = data.get("observations", [])
        if not observations:
            continue
        latest = observations[0]
        # FRED returns "." for missing observations and stringified
        # numbers otherwise. Coerce; on any failure, skip the series.
        raw_value = latest.get("value")
        if raw_value is None or raw_value == ".":
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        out[sid] = {"value": value, "date": latest.get("date", "")}
    return out


PROVIDERS: dict[str, MacroProvider] = {
    "fred": _fetch_fred_observations,
}


# ── Async entry point ─────────────────────────────────────────────────


async def fetch_macro(
    symbol: str,
    *,
    industry: str | None = None,
    provider: str = "fred",
) -> dict[str, Claim]:
    """
    Fetch macro context for ``symbol`` as ``dict[str, Claim]``.

    ``industry`` is an optional yfinance.industry hint — when the
    caller already has it from another tool (e.g. fundamentals or
    peers), pass it through and we'll save the lookup. When omitted,
    sector resolution falls back to the curated-only path.

    Stable shape: ``sector`` + ``series_list`` + per-resolved-series
    ``<id>.value`` / ``.date`` / ``.label`` keys, even when
    ``FRED_API_KEY`` is unset (data values land as None, label is
    always present from the static map).
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    service_id = f"{provider}.macro"

    sector = resolve_sector(target, industry)
    series = SECTOR_SERIES.get(sector, DEFAULT_SERIES) if sector else DEFAULT_SERIES
    series_ids = [s.id for s in series]

    with log_external_call(
        service_id,
        {"symbol": target, "provider": provider},
    ) as call:
        observations = await asyncio.to_thread(fetch, series_ids)
        call.record_output(
            {"sector": sector, "series_count": len(series)}
        )

    fetched_at = datetime.now(UTC)
    return _build_claims(
        service_id=service_id,
        fetched_at=fetched_at,
        sector=sector,
        series=series,
        observations=observations,
    )


def _build_claims(
    *,
    service_id: str,
    fetched_at: datetime,
    sector: str | None,
    series: list[FredSeries],
    observations: dict[str, dict[str, Any]],
) -> dict[str, Claim]:
    """Stamp Source + Claim objects over the resolved sector + per-series data."""
    out: dict[str, Claim] = {}

    out["sector"] = Claim(
        description="Resolved sector for macro context",
        value=sector,
        source=Source(
            tool=service_id,
            fetched_at=fetched_at,
            detail="curated map / info.industry fallback",
        ),
    )
    out["series_list"] = Claim(
        description="FRED series chosen for this sector",
        value=", ".join(s.id for s in series),
        source=Source(
            tool=service_id,
            fetched_at=fetched_at,
            detail="sector → series map",
        ),
    )

    for s in series:
        obs = observations.get(s.id) or {}
        value: ClaimValue = obs.get("value")
        date_str: ClaimValue = obs.get("date") or None
        out[f"{s.id}.value"] = Claim(
            description=f"{s.label} (latest observation)",
            value=value,
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=f"FRED series:{s.id}",
            ),
        )
        out[f"{s.id}.date"] = Claim(
            description=f"{s.label} observation date",
            value=date_str,
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=f"FRED series:{s.id} latest date",
            ),
        )
        # Label is static — sourced from our curated map, not FRED — but
        # exposed as a Claim so the agent's prompt can iterate over keys
        # uniformly without a sidecar lookup.
        out[f"{s.id}.label"] = Claim(
            description=f"Human-readable label for FRED series {s.id}",
            value=s.label,
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail="curated SECTOR_SERIES map",
            ),
        )

    return out
