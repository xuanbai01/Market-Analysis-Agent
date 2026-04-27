"""
Tests for the curated TICKER → CUSIP map.

Pure data — no I/O, no async. Tests pin the lookup contract and the
"every curated peer has a CUSIP" invariant so a future refactor that
adds a SECTOR_PEERS ticker without a CUSIP entry fails CI loudly.
"""
from __future__ import annotations

from app.services.cusips import TICKER_TO_CUSIP, lookup_cusip
from app.services.sectors import SECTOR_PEERS


def test_lookup_cusip_resolves_known_ticker() -> None:
    # AAPL's CUSIP is publicly known (037833100). Pinning it ensures the
    # constant doesn't drift.
    assert lookup_cusip("AAPL") == "037833100"


def test_lookup_cusip_returns_none_for_unknown_ticker() -> None:
    assert lookup_cusip("WEIRDCO") is None


def test_lookup_cusip_uppercases_input() -> None:
    """Lookup is case-insensitive at the boundary."""
    assert lookup_cusip("aapl") == "037833100"


def test_every_sector_peer_has_a_cusip() -> None:
    """Invariant: any ticker in our peer map should have a CUSIP we can use.

    If this fails, a SECTOR_PEERS edit added a ticker without a matching
    CUSIP entry — fix by either adding the CUSIP to TICKER_TO_CUSIP or
    removing the ticker from SECTOR_PEERS.
    """
    missing: list[str] = []
    for tickers in SECTOR_PEERS.values():
        for t in tickers:
            if t not in TICKER_TO_CUSIP:
                missing.append(t)
    assert not missing, f"SECTOR_PEERS tickers missing CUSIPs: {missing}"


def test_cusip_format_is_9_alphanumeric_chars() -> None:
    """CUSIPs are exactly 9 alphanumeric characters per SEC convention."""
    for ticker, cusip in TICKER_TO_CUSIP.items():
        assert len(cusip) == 9, f"{ticker}: CUSIP {cusip!r} is not 9 chars"
        assert cusip.isalnum(), f"{ticker}: CUSIP {cusip!r} has non-alnum chars"
