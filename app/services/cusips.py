"""
Curated TICKER → CUSIP map.

Why curated and not API-driven: the set of tickers we research is the
``SECTOR_PEERS`` set plus a handful of extras. Hard-coding their CUSIPs
is a one-time cost; freeing us from a runtime API call (OpenFIGI etc.)
keeps fetch_edgar dependency-free and the smoke-test surface small.

CUSIPs are 9-character alphanumeric SEC identifiers. They're public and
stable — once issued they don't change for the security's lifetime.
Sources for the values below: SEC filings, Yahoo Finance, OpenFIGI.

Tickers outside this map cause holdings_13f to short-circuit (no
fetch_edgar calls, all-None claims). When a research request needs
13F coverage of a ticker we haven't curated, add an entry here.

A test invariant in tests/test_cusips.py asserts every SECTOR_PEERS
ticker has an entry — so a future edit to peer lists fails CI loudly
if it doesn't include the CUSIP.
"""
from __future__ import annotations

# Hand-curated. Keep alphabetized within each sector for readability.
TICKER_TO_CUSIP: dict[str, str] = {
    # Semiconductors
    "AMD": "007903107",
    "AVGO": "11135F101",
    "INTC": "458140100",
    "MU": "595112103",
    "NVDA": "67066G104",
    "QCOM": "747525103",
    "TSM": "874039100",
    # Megacap tech
    "AAPL": "037833100",
    "AMZN": "023135106",
    "GOOGL": "02079K305",
    "META": "30303M102",
    "MSFT": "594918104",
    "ORCL": "68389X105",
    # Cloud / SaaS
    "CRWD": "22788C105",
    "DDOG": "23804L103",
    "MDB": "60937P106",
    "NET": "18915M107",
    "OKTA": "679295105",
    "SNOW": "833445109",
    "ZS": "98980G102",
    # Banks
    "BAC": "060505104",
    "C": "172967424",
    "GS": "38141G104",
    "JPM": "46625H100",
    "MS": "61744D101",
    "WFC": "949746101",
    # E-commerce / retail
    "EBAY": "278642103",
    "ETSY": "29786A106",
    "MELI": "58733R102",
    "SHOP": "82509L107",
    # Streaming / media
    "DIS": "254687106",
    "NFLX": "64110L106",
    "ROKU": "77543R102",
    "SPOT": "L8681Q102",
    # Auto / EV
    "F": "345370860",
    "GM": "37045V100",
    "LCID": "534678105",
    "RIVN": "76954A103",
    "TSLA": "88160R101",
    # Pharma
    "ABBV": "00287Y109",
    "JNJ": "478160104",
    "LLY": "532457108",
    "MRK": "58933Y105",
    "PFE": "717081103",
    # Oil & gas
    "COP": "20825C104",
    "CVX": "166764100",
    "EOG": "26875P101",
    "OXY": "674599105",
    "XOM": "30231G102",
    # Consumer staples
    "COST": "22160K105",
    "KO": "191216100",
    "PEP": "713448108",
    "PG": "742718109",
    "WMT": "931142103",
}


def lookup_cusip(ticker: str) -> str | None:
    """
    Resolve a ticker to its 9-character CUSIP, or ``None`` if uncurated.

    Case-insensitive at the boundary — callers can pass mixed-case
    tickers without normalizing.
    """
    return TICKER_TO_CUSIP.get(ticker.upper())
