"""
Peers tool. Returns sector context plus a comparison matrix of 4 valuation
metrics across 3-5 peers as a flat ``dict[str, Claim]``.

Why hand-curated peers over a clustering approach: yfinance's
``info["industry"]`` is fine for "what does this company do" but its peer
suggestions (when present at all) are noisy. Three semis in a curated
list — AMD, INTC, AVGO — are a stronger comparison set for NVDA than
yfinance's automated picks. The trade-off is coverage: tickers outside
our hand-curated map fall back to a yfinance.industry → curated-bucket
lookup; tickers in unknown industries get an empty peer list and the
agent renders "peer comparison unavailable" rather than fabricating one.

Why ``dict[str, Claim]`` with variable keys: same shape as
``fetch_fundamentals`` so the agent's prompt-building code is uniform,
even though peer count varies. Per-(peer, metric) keys are
``"<PEER>.<metric>"`` (e.g. ``"AMD.trailing_pe"``); per-metric medians
are ``"median.<metric>"``; metadata claims are ``"sector"`` and
``"peers_list"``. Iteration is straightforward: list all keys with a
``.`` and split.

Why median rather than mean: outlier-resistant. One peer with a 200×
trailing P/E (negative earnings reverting) shouldn't pull the
"sector P/E" the agent cites in a 5-peer comparison.

Why a single ``log_external_call`` wrapping the whole fan-out instead
of one per peer: peers fan out 5+ HTTP calls, but they all serve a
single research question ("compare NVDA to its peers"). One log entry
per fetch_peers call keeps the A09 stream readable; per-peer detail is
out of scope for observability and would only matter for performance
analysis, which we don't need until peer counts grow.

Deferred (intentionally):
- Sector-relative ratios (primary's P/E ÷ peer median) — the agent can
  compute these at synth time from the medians + the primary's
  fundamentals. No reason to bake the math into this tool.
- More than 4 metrics — fetch_fundamentals provides depth on a single
  symbol; fetch_peers is breadth across symbols. Adding more metrics
  here just multiplies the response size by N peers.
- Caching across requests — a daily peer-snapshot table comes when we
  have request volume that justifies it.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import median
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, ClaimValue, Source

# ── Comparison contract ───────────────────────────────────────────────
# Four metrics, picked for cross-peer comparability. Keep this lean —
# fetch_fundamentals owns depth on one symbol; this tool owns breadth.
PEER_METRICS: tuple[str, ...] = (
    "trailing_pe",
    "p_s",
    "ev_ebitda",
    "gross_margin",
)

# yfinance .info key for each metric. Mirrors fetch_fundamentals so a
# yfinance schema change hits only one of these tables.
_INFO_KEYS: dict[str, str] = {
    "trailing_pe": "trailingPE",
    "p_s": "priceToSalesTrailing12Months",
    "ev_ebitda": "enterpriseToEbitda",
    "gross_margin": "grossMargins",
}

_DESCRIPTIONS: dict[str, str] = {
    "trailing_pe": "P/E ratio (trailing 12 months)",
    "p_s": "Price-to-sales ratio (trailing 12 months)",
    "ev_ebitda": "Enterprise value to EBITDA",
    "gross_margin": "Gross margin",
}

# ── Sector resolution ─────────────────────────────────────────────────
# Curated peer sets keyed by our internal sector id. Names are short
# and descriptive; the synth call may quote them. Add aggressively as
# requested coverage grows — this is just a starting set of ~10 sectors
# covering the most common large-cap research targets.
_SECTOR_PEERS: dict[str, list[str]] = {
    "semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "MU"],
    "megacap_tech": ["MSFT", "GOOGL", "META", "AMZN", "AAPL", "ORCL"],
    "cloud_saas": ["SNOW", "NET", "DDOG", "MDB", "CRWD", "ZS", "OKTA"],
    "banks": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "ecommerce_retail": ["AMZN", "SHOP", "EBAY", "ETSY", "MELI"],
    "streaming_media": ["NFLX", "DIS", "ROKU", "SPOT"],
    "auto_ev": ["TSLA", "F", "GM", "RIVN", "LCID"],
    "pharma": ["PFE", "JNJ", "MRK", "ABBV", "LLY"],
    "oil_gas": ["XOM", "CVX", "COP", "OXY", "EOG"],
    "consumer_staples": ["PG", "KO", "PEP", "COST", "WMT"],
}

# Reverse-index from each ticker to the sector that lists it. A ticker
# that appears in multiple sectors (e.g. AMZN) gets the first
# enumeration order — for AMZN that's ``megacap_tech``, which is the
# more common framing for valuation comparison than ``ecommerce_retail``.
_TICKER_TO_SECTOR: dict[str, str] = {}
for _sector, _tickers in _SECTOR_PEERS.items():
    for _t in _tickers:
        _TICKER_TO_SECTOR.setdefault(_t, _sector)

# Map yfinance ``info["industry"]`` strings to our sector ids. yfinance
# uses Yahoo's industry taxonomy which is fairly stable. When a ticker
# is outside our curated map, this is the second-tier lookup.
_INDUSTRY_TO_SECTOR: dict[str, str] = {
    "Semiconductors": "semiconductors",
    "Semiconductor Equipment & Materials": "semiconductors",
    "Software—Infrastructure": "cloud_saas",
    "Software—Application": "cloud_saas",
    "Banks—Diversified": "banks",
    "Banks—Regional": "banks",
    "Capital Markets": "banks",
    "Internet Retail": "ecommerce_retail",
    "Specialty Retail": "ecommerce_retail",
    "Entertainment": "streaming_media",
    "Auto Manufacturers": "auto_ev",
    "Drug Manufacturers—General": "pharma",
    "Drug Manufacturers—Specialty & Generic": "pharma",
    "Biotechnology": "pharma",
    "Oil & Gas Integrated": "oil_gas",
    "Oil & Gas E&P": "oil_gas",
    "Household & Personal Products": "consumer_staples",
    "Beverages—Non-Alcoholic": "consumer_staples",
    "Discount Stores": "consumer_staples",
}


# Provider returns the resolved sector + peer list + per-peer metrics.
# Sync — yfinance is blocking; the async entry point hands it to to_thread.
PeersProvider = Callable[[str], dict[str, Any]]


def _resolve_sector(symbol: str, industry: str | None) -> str | None:
    """Curated map first; yfinance industry fallback second; else None."""
    if symbol in _TICKER_TO_SECTOR:
        return _TICKER_TO_SECTOR[symbol]
    if industry and industry in _INDUSTRY_TO_SECTOR:
        return _INDUSTRY_TO_SECTOR[industry]
    return None


def _select_peers(symbol: str, sector: str | None) -> list[str]:
    """Peers from sector list, primary excluded, capped at 5 for response size."""
    if sector is None:
        return []
    return [p for p in _SECTOR_PEERS[sector] if p != symbol][:5]


def _fetch_peer_info(symbol: str) -> dict[str, ClaimValue | None]:
    """One peer's metrics from a single yfinance.Ticker.info call.

    Isolated in its own helper so the per-peer try/except in the
    fan-out has a clean unit to wrap. Errors here become an all-None
    metrics dict for that peer — the comparison matrix still renders,
    just with one column blanked.
    """
    import yfinance  # noqa: PLC0415

    ticker = yfinance.Ticker(symbol)
    info: dict[str, Any] = getattr(ticker, "info", {}) or {}
    return {metric: info.get(_INFO_KEYS[metric]) for metric in PEER_METRICS}


def _fetch_yfinance_peers(symbol: str) -> dict[str, Any]:
    """Resolve sector for ``symbol``, then pull every peer's .info."""
    import yfinance  # noqa: PLC0415

    primary_info: dict[str, Any] = (
        getattr(yfinance.Ticker(symbol), "info", {}) or {}
    )
    industry = primary_info.get("industry")
    sector = _resolve_sector(symbol, industry)
    peers = _select_peers(symbol, sector)

    metrics: dict[str, dict[str, ClaimValue | None]] = {}
    for peer in peers:
        try:
            metrics[peer] = _fetch_peer_info(peer)
        except Exception:  # noqa: BLE001 — peer isolation
            # One peer's broken .info shouldn't blank the whole matrix;
            # fall through to all-None for this column.
            metrics[peer] = {m: None for m in PEER_METRICS}

    return {"sector": sector, "peers": peers, "metrics": metrics}


PROVIDERS: dict[str, PeersProvider] = {
    "yfinance": _fetch_yfinance_peers,
}


def _median_or_none(values: list[ClaimValue | None]) -> float | None:
    """Median over non-null numeric values; None if no usable values remain."""
    nums = [float(v) for v in values if isinstance(v, int | float) and v is not None]
    if not nums:
        return None
    return float(median(nums))


def _build_claims(
    *,
    service_id: str,
    fetched_at: datetime,
    sector: str | None,
    peers: list[str],
    metrics: dict[str, dict[str, ClaimValue | None]],
) -> dict[str, Claim]:
    """Stamp Source + Claim objects over the provider's normalized payload."""
    out: dict[str, Claim] = {}

    # Metadata claims — present even when sector/peer resolution failed,
    # so the agent always sees a stable shape for these two keys.
    out["sector"] = Claim(
        description="Resolved sector for peer comparison",
        value=sector,
        source=Source(
            tool=service_id,
            fetched_at=fetched_at,
            detail="curated map / info.industry fallback",
        ),
    )
    out["peers_list"] = Claim(
        description="Peers selected for comparison",
        value=", ".join(peers),
        source=Source(
            tool=service_id,
            fetched_at=fetched_at,
            detail="curated map / info.industry fallback",
        ),
    )

    # Per-(peer, metric) claims — keyed "<PEER>.<metric>".
    for peer in peers:
        peer_metrics = metrics.get(peer, {})
        for metric in PEER_METRICS:
            value = peer_metrics.get(metric)
            out[f"{peer}.{metric}"] = Claim(
                description=f"{peer}: {_DESCRIPTIONS[metric]}",
                value=value,
                source=Source(
                    tool=service_id,
                    fetched_at=fetched_at,
                    detail=f"{peer} info.{_INFO_KEYS[metric]}",
                ),
            )

    # Per-metric medians across peers — only emitted when we have peers.
    if peers:
        for metric in PEER_METRICS:
            values = [metrics.get(p, {}).get(metric) for p in peers]
            out[f"median.{metric}"] = Claim(
                description=f"Peer median: {_DESCRIPTIONS[metric]}",
                value=_median_or_none(values),
                source=Source(
                    tool=service_id,
                    fetched_at=fetched_at,
                    detail=f"computed: median across {len(peers)} peers",
                ),
            )

    return out


async def fetch_peers(
    symbol: str,
    *,
    provider: str = "yfinance",
) -> dict[str, Claim]:
    """
    Fetch a flat ``dict[str, Claim]`` of peer comparison data for one symbol.

    Single-provider per call: failures propagate (the agent has other
    tools to fall back on). Per-peer failures inside the provider are
    isolated and produce all-None metric columns rather than dropping
    the whole call.
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    service_id = f"{provider}.peers"

    with log_external_call(
        service_id, {"symbol": target, "provider": provider}
    ) as call:
        payload = await asyncio.to_thread(fetch, target)
        sector = payload.get("sector")
        peers = list(payload.get("peers") or [])
        metrics = payload.get("metrics") or {}
        call.record_output(
            {"sector": sector, "peer_count": len(peers)}
        )

    fetched_at = datetime.now(UTC)
    return _build_claims(
        service_id=service_id,
        fetched_at=fetched_at,
        sector=sector,
        peers=peers,
        metrics=metrics,
    )
