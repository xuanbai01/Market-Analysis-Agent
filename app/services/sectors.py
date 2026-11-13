"""
Symbol → sector resolution. Shared by ``peers`` (sector → peer set)
and ``macro`` (sector → FRED-series set), and by any future tool that
needs "what kind of company is this".

Two-tier lookup:

1. **Curated map** — ``_TICKER_TO_SECTOR`` covers ~50 well-known
   large-caps across 10 sectors. Hand-picked, higher confidence; we
   control the bucket assignment (e.g. AMZN → ``megacap_tech`` rather
   than ``ecommerce_retail``, which is the more common valuation
   framing).
2. **yfinance industry fallback** — ``_INDUSTRY_TO_SECTOR`` maps the
   industry strings yfinance returns in ``Ticker.info["industry"]``
   to our sector ids. Catches uncurated tickers in known industries.

When neither tier matches, ``resolve_sector`` returns ``None`` and the
caller decides how to degrade (peers returns an empty peer list; macro
falls back to a default series set).

Why a separate module: peers and macro both need this map and the
resolver. Two private cross-module imports between them would smell
worse than one shared utility module.
"""
from __future__ import annotations

# Curated peer sets keyed by our internal sector id. Names are short
# and descriptive; the synth call may quote them. Add aggressively as
# requested coverage grows — this is just a starting set of ~10 sectors
# covering the most common large-cap research targets.
SECTOR_PEERS: dict[str, list[str]] = {
    "semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "MU"],
    "megacap_tech": ["MSFT", "GOOGL", "META", "AMZN", "AAPL", "ORCL"],
    "cloud_saas": ["SNOW", "NET", "DDOG", "MDB", "CRWD", "ZS", "OKTA"],
    "banks": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "ecommerce_retail": ["AMZN", "SHOP", "EBAY", "ETSY", "MELI"],
    "streaming_media": ["NFLX", "DIS", "ROKU", "SPOT"],
    "auto_ev": ["TSLA", "F", "GM", "RIVN", "LCID"],
    "pharma": ["PFE", "JNJ", "MRK", "ABBV", "LLY"],
    # Integrated majors also refine and sell fuel, so their gross margins
    # (27-44%) sit far below a pure producer's (49-74%) and their
    # EV/EBITDA higher. One mixed set made XOM look 65% expensive on
    # EV/EBITDA and 26 points short on gross margin (dogfood 2026-11 #19).
    "integrated_oil": ["XOM", "CVX", "SHEL", "BP", "TTE"],
    "oil_gas_producers": ["COP", "OXY", "EOG", "DVN", "FANG"],
    # Branded staples (60%-ish gross margins) and the retailers that sell
    # them (10–25%) price and earn differently; comparing KO's P/S with
    # WMT's made every valuation gap meaningless (ADR 0007).
    "consumer_staples": ["PG", "KO", "PEP", "CL", "KMB", "MDLZ"],
    "staples_retail": ["WMT", "COST", "TGT", "KR", "DG"],
}

# Reverse-index from each ticker to the sector that lists it. A ticker
# that appears in multiple sectors (e.g. AMZN) gets the first
# enumeration order — for AMZN that's ``megacap_tech``, which is the
# more common framing for valuation comparison than ``ecommerce_retail``.
TICKER_TO_SECTOR: dict[str, str] = {}
for _sector, _tickers in SECTOR_PEERS.items():
    for _t in _tickers:
        TICKER_TO_SECTOR.setdefault(_t, _sector)

# Map yfinance ``info["industry"]`` strings to our sector ids. yfinance
# uses Yahoo's industry taxonomy which is fairly stable. When a ticker
# is outside our curated map, this is the second-tier lookup.
INDUSTRY_TO_SECTOR: dict[str, str] = {
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
    "Oil & Gas Integrated": "integrated_oil",
    "Oil & Gas E&P": "oil_gas_producers",
    "Household & Personal Products": "consumer_staples",
    "Beverages—Non-Alcoholic": "consumer_staples",
    "Confectioners": "consumer_staples",
    "Packaged Foods": "consumer_staples",
    "Discount Stores": "staples_retail",
    "Grocery Stores": "staples_retail",
}


def resolve_sector(symbol: str, industry: str | None = None) -> str | None:
    """
    Resolve a ticker to one of our internal sector ids.

    Curated map first (highest confidence); yfinance industry fallback
    second (medium confidence); ``None`` if neither matched. Symbol is
    expected to be already-uppercased — callers normalize at their own
    boundary.
    """
    if symbol in TICKER_TO_SECTOR:
        return TICKER_TO_SECTOR[symbol]
    if industry and industry in INDUSTRY_TO_SECTOR:
        return INDUSTRY_TO_SECTOR[industry]
    return None
