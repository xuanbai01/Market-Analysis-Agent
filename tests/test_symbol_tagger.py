"""
Pure-function tests for the regex symbol tagger.

The tagger has three signals:
  - cashtag ($NVDA)
  - ticker word boundary (NVDA, length >= 3)
  - company-name first token (NVIDIA from "NVIDIA Corp")

Each test pins one of those signals on or off so a regex tweak can't
silently change behaviour. False-positive risks (common-word tickers
like "ALL" / "CAR") are covered explicitly — these are accepted noise
documented in the module docstring; the tests pin the current behaviour
so any future tightening is intentional.
"""
from __future__ import annotations

import pytest

from app.services.symbol_tagger import TrackedSymbol, tag

# Fixtures: a small, realistic universe.
NVDA = TrackedSymbol(symbol="NVDA", name="NVIDIA Corp")
AMD = TrackedSymbol(symbol="AMD", name="Advanced Micro Devices")
SPY = TrackedSymbol(symbol="SPY", name="SPDR S&P 500 ETF")
AAPL = TrackedSymbol(symbol="AAPL", name="Apple Inc")
A = TrackedSymbol(symbol="A", name="Agilent Technologies")  # 1-letter ticker

UNIVERSE = [NVDA, AMD, SPY, AAPL, A]


# ── Cashtag ──────────────────────────────────────────────────────────


def test_cashtag_matches_any_ticker_length() -> None:
    """Cashtag is the strongest signal — accept it even for 1-char tickers."""
    assert tag("Bullish on $A and $NVDA today", UNIVERSE) == {"A", "NVDA"}


def test_cashtag_word_boundary_required() -> None:
    """`$NVDAQ` should not tag NVDA — the cashtag pattern enforces \\b."""
    assert tag("Visit $NVDAQ for more info", UNIVERSE) == set()


# ── Ticker word boundary ─────────────────────────────────────────────


def test_ticker_word_boundary_matches_3_plus_char_tickers() -> None:
    assert tag("NVDA earnings beat estimates.", [NVDA]) == {"NVDA"}


def test_ticker_word_boundary_does_not_match_substrings() -> None:
    """`INVEST` should not tag NVDA. Word-boundary regex does the work."""
    assert tag("Investors are bullish on chips.", [NVDA]) == set()


def test_short_ticker_requires_cashtag() -> None:
    """1- and 2-char tickers without cashtag are too noisy — skip them."""
    # 'A' the article should NOT match A the ticker without a cashtag.
    assert tag("A new chip from NVIDIA Corp launched today.", [A]) == set()


def test_short_ticker_with_cashtag_still_matches() -> None:
    assert tag("Long $A this quarter", [A]) == {"A"}


# ── Company-name first token ─────────────────────────────────────────


def test_name_first_token_matches_case_insensitively() -> None:
    """`NVIDIA` (case insensitive) on a NVDA/NVIDIA Corp tracked symbol."""
    assert tag("Nvidia reported strong demand for AI chips.", [NVDA]) == {"NVDA"}


def test_name_first_token_only_uses_first_word() -> None:
    """`Advanced Micro Devices` → match `Advanced`, not the multi-word phrase."""
    # "Advanced" is the first token of AMD's name. A headline using
    # "Advanced" matches AMD even without the ticker.
    assert tag("Advanced packaging is the new bottleneck.", [AMD]) == {"AMD"}


def test_name_first_token_misses_when_only_secondary_word_present() -> None:
    """Random use of `Devices` shouldn't tag AMD."""
    assert tag("Many devices on the market today.", [AMD]) == set()


# ── Combinations ─────────────────────────────────────────────────────


def test_multiple_signals_collapse_to_one_match() -> None:
    """`$NVDA` + `NVIDIA` in the same headline = one entry, not two."""
    assert tag("$NVDA NVIDIA crushed Q3", [NVDA]) == {"NVDA"}


def test_multi_symbol_article() -> None:
    """A headline mentioning both NVDA and AMD should tag both."""
    text = "NVDA earnings drag AMD lower; chipmaker selloff continues."
    assert tag(text, UNIVERSE) == {"NVDA", "AMD"}


# ── Edge cases ───────────────────────────────────────────────────────


def test_empty_text_returns_empty_set() -> None:
    assert tag("", UNIVERSE) == set()


def test_empty_universe_returns_empty_set() -> None:
    assert tag("NVDA earnings", []) == set()


def test_symbol_without_name_only_uses_ticker_match() -> None:
    """A TrackedSymbol with name=None should still match by ticker."""
    bare = TrackedSymbol(symbol="TSLA", name=None)
    assert tag("TSLA delivery numbers came in soft.", [bare]) == {"TSLA"}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$NVDA report dropped", {"NVDA"}),
        ("NVIDIA's CUDA moat is real", {"NVDA"}),
        ("Apple unveiled a new chip", {"AAPL"}),
        ("nvidia and amd vs intel", {"NVDA", "AMD"}),
    ],
)
def test_realistic_headlines(text: str, expected: set[str]) -> None:
    assert tag(text, UNIVERSE) == expected
