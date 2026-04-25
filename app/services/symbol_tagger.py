"""
Symbol tagger — given an article's title + body and a list of tracked
symbols, return the subset that the article plausibly references.

Three signals, in increasing precision:

  1. **Cashtag** — `$NVDA`. Strong signal, near-zero false positives.
  2. **Ticker word-boundary** — ``\\bNVDA\\b``, but only for tickers of
     length ≥ 3. Two-letter tickers ("AA", "GE", "FB") collide with
     common English noise too often; require a cashtag for those.
  3. **Company-name first token** — first word of `symbols.name`,
     case-insensitive, word-boundary match. "NVIDIA" matches NVDA;
     "SPDR" matches SPY. Only used when the company name is set.

False-positive risks accepted at this stage:
  - Common-word tickers ("ALL" → Allstate, "CAR" → Avis): the
    word-boundary + uppercase-required regex catches these only when
    the article writes them in caps, which is rare for non-financial
    contexts. Tolerable noise.
  - Single-word names that are also English words ("Apple"): a
    finance-news article mentioning "apple" usually means AAPL anyway.

This is deliberately a regex pass, not an LLM call. Tagging happens on
every article on every ingest; we save LLM tokens for synthesis.
Replace with an NER pass in a later sprint when accuracy starts
mattering more than throughput.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Tickers shorter than this require a cashtag — too many English false
# positives at length 1 or 2. Tunable per-organization later if we ever
# track 1- or 2-letter tickers (currently we don't).
_TICKER_MIN_LEN = 3

# Cashtag pattern is the same regardless of ticker length.
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")


@dataclass(frozen=True)
class TrackedSymbol:
    """One row from the `symbols` table, in tag-friendly form."""

    symbol: str
    name: str | None = None


def _ticker_pattern(symbol: str) -> re.Pattern[str]:
    """
    ``\\bNVDA\\b`` with the symbol literal-escaped, **case-insensitive**.

    Real headlines mix cases freely ("nvidia and amd vs intel"); a
    case-sensitive match would silently drop lowercase mentions of
    real tickers. The trade-off is occasional false positives when a
    ticker also happens to be an English word — "AND", "FOR", "ALL",
    "ANY", etc. We don't currently track any of those, and the tagger
    is a heuristic by design (see module docstring); when this becomes
    a problem, swap to NER instead of layering more regex bandaids.
    """
    return re.compile(rf"\b{re.escape(symbol)}\b", re.IGNORECASE)


def _name_first_token(name: str) -> str | None:
    """First whitespace-separated word of a company name, stripped."""
    for tok in name.split():
        if tok:
            return tok
    return None


def _name_token_pattern(token: str) -> re.Pattern[str]:
    """Case-insensitive word-boundary match on a company-name first token."""
    return re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)


def tag(text: str, symbols: Iterable[TrackedSymbol]) -> set[str]:
    """
    Return the subset of ``symbols`` whose ticker or company-name first
    token plausibly appears in ``text``. ``text`` is typically
    ``title + " " + description`` of a news article.

    Empty ``text`` or empty ``symbols`` returns the empty set. The
    returned set contains symbol strings (e.g. ``{"NVDA", "AMD"}``),
    not TrackedSymbol objects.
    """
    if not text:
        return set()

    cashtags = {m.group(1) for m in _CASHTAG_RE.finditer(text)}
    matched: set[str] = set()

    for sym in symbols:
        ticker = sym.symbol

        # Cashtag is the strongest signal — accept it for any length.
        if ticker in cashtags:
            matched.add(ticker)
            continue

        # Word-boundary match on the bare ticker, but only for length≥3
        # to avoid ticker-vs-English-word collisions.
        if len(ticker) >= _TICKER_MIN_LEN and _ticker_pattern(ticker).search(text):
            matched.add(ticker)
            continue

        # Company-name first-token match. Helps for full-name mentions
        # ("NVIDIA reported strong earnings" → NVDA).
        if sym.name:
            token = _name_first_token(sym.name)
            if token and _name_token_pattern(token).search(text):
                matched.add(ticker)

    return matched
