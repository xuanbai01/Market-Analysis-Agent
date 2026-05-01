"""
Macro context tool. Given a ticker, resolve to sector via the shared
``app.services.sectors`` resolver, look up a curated FRED series set
for that sector, fetch ~36 monthly observations per series, return as
flat ``dict[str, Claim]`` where the ``<id>.value`` claim carries
``Claim.history`` for sparkline rendering.

Why curated sector→series rather than a generic "give me FRED data"
tool: the agent's question is "what's the macro context for this
ticker?" not "go fetch DGS10". Encoding the "rate-sensitive
long-duration tech wants the 10Y yield" judgement here, in code
that's reviewable and testable, beats expecting the LLM to pick the
right series at synth time.

## Phase 3.2.F shape change

Pre-3.2.F the provider returned ``{series_id: {"value", "date"}}`` —
one observation per series. After 3.2.F it returns
``(snapshot, history_map)`` matching the fundamentals/earnings provider
contract; the ``<id>.value`` claim attaches the per-series history,
``<id>.date`` and ``<id>.label`` stay history-less (date is a single
label, label is static metadata).

Snapshot consistency is preserved by construction: the snapshot value
is always ``history[-1].value`` (newest monthly point), so the
headline number and the sparkline's right endpoint agree.

## Why monthly aggregation

FRED supports a ``frequency=m`` parameter that aggregates daily series
(DGS10, DCOILWTICO, …) into monthly observations server-side. For
already-monthly series (UMCSENT, MANEMP, RSAFS, UNRATE, CPIAUCSL) it's
a no-op. One per-series HTTP call still returns the full ~36-month
history — no client-side bucketing, no per-day quota burn.

The semantic shift: pre-3.2.F a daily series' "latest value" was the
most-recent daily observation; after 3.2.F it's the most-recent
**monthly** observation. For sparkline rendering this is the only
internally-consistent choice (otherwise the headline diverges from the
chart's right endpoint), and "the 10Y averaged 4.32% in October" is a
natural enough framing for a research-report headline.

Graceful degradation when ``FRED_API_KEY`` is unset: the production
provider early-returns ``({}, {})`` (no HTTP), and the service stamps
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
  for "how much has X moved" specifically; the renderer can derive
  the trend visually from the sparkline now that history is plumbed.
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
from app.schemas.research import Claim, ClaimHistoryPoint, ClaimValue, Source
from app.services.sectors import resolve_sector

# How many monthly observations to ask FRED for per series. ~3 years
# is a good sparkline depth — enough to see a cycle, short enough to
# stay readable at the small width this renders at.
MACRO_HISTORY_LIMIT_MONTHS: int = 36


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


# Provider signature: (series_ids) -> (snapshot, history_map).
#
# - snapshot[id] = {"value": float, "date": str} — newest monthly obs
# - history_map[id] = list[ClaimHistoryPoint], oldest → newest
#
# Sync — httpx.get blocks; the async entry point hands it to to_thread.
# Mirrors fundamentals + earnings provider tuple shape so a future
# refactor that unifies them is mechanical.
MacroProvider = Callable[
    [list[str]],
    tuple[
        dict[str, dict[str, Any]],
        dict[str, list[ClaimHistoryPoint]],
    ],
]


# ── Production provider — FRED HTTP ───────────────────────────────────


def _format_macro_period(date_str: str) -> str:
    """Render FRED's ``YYYY-MM-DD`` date as ``YYYY-MM`` for chart labels.

    FRED returns the first day of the month for monthly observations
    (e.g. ``"2024-10-01"``); we strip the day for compact sparkline
    tooltips. On any unexpected format we return the input verbatim
    rather than crashing — chart renderer tolerates arbitrary period
    strings, and we'd rather show a slightly-ugly label than blank
    out a real data point.
    """
    if len(date_str) >= 7 and date_str[4] == "-":
        return date_str[:7]
    return date_str


def _parse_observations(
    observations: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[ClaimHistoryPoint]]:
    """Split FRED's desc-sorted observations into (snapshot, history).

    FRED returns ``"."`` for missing observations and stringified numbers
    otherwise. Drop missing rows from history; never let one become the
    snapshot. Returns ``(None, [])`` when no rows are valid.
    """
    valid_rows: list[tuple[str, float]] = []
    for row in observations:
        raw = row.get("value")
        if raw is None or raw == ".":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        date = row.get("date", "") or ""
        valid_rows.append((date, value))

    if not valid_rows:
        return None, []

    # FRED's response is newest-first (sort_order=desc). Snapshot picks
    # from the front; history reverses for the oldest-first chart
    # convention.
    newest_date, newest_value = valid_rows[0]
    snapshot = {"value": newest_value, "date": newest_date}
    history = [
        ClaimHistoryPoint(period=_format_macro_period(d), value=v)
        for d, v in reversed(valid_rows)
    ]
    return snapshot, history


def _fetch_fred_observations(
    series_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[ClaimHistoryPoint]]]:
    """
    Pull ~36 monthly observations per series from FRED.

    Returns ``({}, {})`` (no HTTP fired) when ``FRED_API_KEY`` is unset —
    callers degrade gracefully. One per-series HTTP call is fine within
    FRED's 120 req/min cap.

    Each call uses ``frequency=m`` for monthly aggregation: daily series
    (DGS10 etc.) collapse to per-month observations server-side; already-
    monthly series pass through unchanged. ``aggregation_method=avg`` is
    FRED's default, so we omit it.
    """
    snapshot_out: dict[str, dict[str, Any]] = {}
    history_out: dict[str, list[ClaimHistoryPoint]] = {}

    if not settings.FRED_API_KEY:
        return snapshot_out, history_out

    for sid in series_ids:
        try:
            resp = httpx.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": sid,
                    "api_key": settings.FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": MACRO_HISTORY_LIMIT_MONTHS,
                    "frequency": "m",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001 — per-series isolation
            # One bad series doesn't kill the rest. Caller stamps None.
            continue

        observations = data.get("observations", [])
        snapshot, history = _parse_observations(observations)
        if snapshot is None:
            continue
        snapshot_out[sid] = snapshot
        history_out[sid] = history

    return snapshot_out, history_out


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
    always present from the static map). The ``<id>.value`` claim
    carries ``Claim.history`` for ~36 monthly points when available.
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
        snapshot, history_map = await asyncio.to_thread(fetch, series_ids)
        history_count = sum(1 for sid in series_ids if history_map.get(sid))
        call.record_output(
            {
                "sector": sector,
                "series_count": len(series),
                "history_populated_count": history_count,
            }
        )

    fetched_at = datetime.now(UTC)
    return _build_claims(
        service_id=service_id,
        fetched_at=fetched_at,
        sector=sector,
        series=series,
        snapshot=snapshot,
        history_map=history_map,
    )


def _build_claims(
    *,
    service_id: str,
    fetched_at: datetime,
    sector: str | None,
    series: list[FredSeries],
    snapshot: dict[str, dict[str, Any]],
    history_map: dict[str, list[ClaimHistoryPoint]],
) -> dict[str, Claim]:
    """Stamp Source + Claim objects over the resolved sector + per-series data.

    Only ``<id>.value`` is history-bearing — that's where the sparkline
    renders. ``<id>.date`` is a single label and ``<id>.label`` is
    static metadata; both ship with empty history.
    """
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
        obs = snapshot.get(s.id) or {}
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
            history=history_map.get(s.id, []),
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
