"""
Tests for the shared sector resolver. The resolver is pure (no I/O),
so tests are direct calls — no monkeypatching needed.
"""
from __future__ import annotations

from app.services.sectors import (
    INDUSTRY_TO_SECTOR,
    SECTOR_PEERS,
    TICKER_TO_SECTOR,
    resolve_sector,
)


def test_curated_ticker_resolves_to_known_sector() -> None:
    assert resolve_sector("NVDA") == "semiconductors"
    assert resolve_sector("JPM") == "banks"
    assert resolve_sector("XOM") == "oil_gas"


def test_industry_fallback_used_when_ticker_uncurated() -> None:
    assert resolve_sector("WEIRDCO", industry="Semiconductors") == "semiconductors"
    assert resolve_sector("OBSCURE", industry="Banks—Regional") == "banks"


def test_curated_map_wins_over_industry() -> None:
    """A curated ticker shouldn't get re-classified by yfinance industry text."""
    # NVDA is curated as semiconductors. Even if yfinance reported a
    # quirky industry string, the curated bucket wins.
    assert resolve_sector("NVDA", industry="Some Other Industry") == "semiconductors"


def test_returns_none_when_neither_tier_matches() -> None:
    assert resolve_sector("WEIRDCO") is None
    assert resolve_sector("WEIRDCO", industry="Niche We've Never Heard Of") is None
    assert resolve_sector("WEIRDCO", industry=None) is None
    assert resolve_sector("WEIRDCO", industry="") is None


def test_ticker_to_sector_built_from_sector_peers() -> None:
    """Reverse-index invariant: every curated peer round-trips to its sector."""
    for _sector, tickers in SECTOR_PEERS.items():
        for t in tickers:
            # First-enumeration-wins for tickers in multiple sectors —
            # the assertion is that *some* sector resolves, not necessarily this one.
            assert TICKER_TO_SECTOR[t] in SECTOR_PEERS


def test_industry_map_values_are_real_sector_ids() -> None:
    """Every industry-fallback target must be a key in SECTOR_PEERS."""
    for sector_id in INDUSTRY_TO_SECTOR.values():
        assert sector_id in SECTOR_PEERS, f"unknown sector id: {sector_id}"
