"""
10-K Item 1 (Business) and Item 1A (Risk Factors) extractors.

Real 10-K HTML is messy: XBRL inline tags everywhere, layouts that vary
by filer, and a Table of Contents at the start that mentions every Item
header. The strategy here is "best-effort regex extraction over
BeautifulSoup-flattened text, with graceful None on miss":

1. ``BeautifulSoup`` flattens HTML to plain text (forgiving of malformed
   markup; strips ``<ix:nonNumeric>`` and other XBRL tags).
2. Regex anchors find candidate ``(start, end)`` pairs for the section
   we want.
3. The "longest match" heuristic picks the real section over the TOC —
   the TOC lists every Item with ~30-100 chars between markers, while
   the real section runs 10-150 KB.
4. Below the 500-char sanity threshold → return ``None``. Defends
   against rare layouts where only the TOC matches.

When the regex layer doesn't find the section, we return ``None`` and
the agent surfaces "10-K extraction unavailable for this filer". An
LLM-based fallback ("here's the 10-K, extract Item 1A") is a deliberate
follow-up — first we want to measure regex hit-rate on real filings.

## Two entry points, one extraction layer

- ``extract_10k_business(symbol)`` — fetches the latest 10-K, returns
  Item 1 as ``Extracted10KSection``.
- ``extract_10k_risks(symbol, prior=False)`` — same for Item 1A;
  ``prior=True`` returns the *second* most recent 10-K so the agent can
  call it twice (once current, once prior) and synthesize "what's new
  in risks" prose itself.

Both share ``_extract_section`` for the HTML→text→anchor pipeline.

## Why a different output shape from the data tools

This tool returns ``Extracted10KSection`` (Pydantic) rather than
``dict[str, Claim]``. The output is multi-page prose that the agent
feeds *to* the synth call as input data — it's not a list of factual
data points. Citation metadata (accession, filed_at, primary_doc_url)
is preserved on the model so the agent can construct Source records
for whatever Claims its synth call ends up emitting in the Business
or Risks sections of the report.

## What's deferred (called out for future PRs)

- LLM-based extraction fallback when regex fails on unusual filers.
- Real text-diff for risks (sentence-level identification of new
  paragraphs). The current "diff" is the agent's job — it gets
  ``current.text`` and ``prior.text`` and writes "new this year: …"
  prose. Sentence-level structural diff is fragile against cosmetic
  edits.
- Pre-computed summaries (extract moat / segments / customer
  concentration as separate Claims). The agent does this at synth
  time from raw text.
- Other Items (7 MD&A, 8 financials, etc.). Separate scope.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.core.observability import log_external_call
from app.schemas.ten_k import Extracted10KSection
from app.services.edgar import fetch_edgar

# Below this threshold, a "matched" section is assumed to be a TOC
# entry rather than the real content. Item 1 / Item 1A in a typical
# 10-K is 10-150 KB; even a tiny filer's section runs at least a few
# thousand chars. 500 is comfortably above any TOC pattern but well
# below any real section.
_MIN_SECTION_CHARS = 500


# Anchor patterns. The regex uses ``\bitem\s+1\b`` style with
# ``re.IGNORECASE`` so headers like "Item 1.", "ITEM 1.", "Item 1 -"
# all match. Multi-character whitespace and non-breaking spaces are
# normalized by BeautifulSoup before this layer sees the text.
_SECTION_ANCHORS: dict[str, tuple[re.Pattern[str], list[re.Pattern[str]]]] = {
    "Item 1": (
        re.compile(r"\bitem\s+1\b\.?\s*(?:business|the\s+company)", re.IGNORECASE),
        [
            re.compile(r"\bitem\s+1a\b\.?\s*risk", re.IGNORECASE),
            re.compile(r"\bitem\s+2\b", re.IGNORECASE),
        ],
    ),
    "Item 1A": (
        re.compile(r"\bitem\s+1a\b\.?\s*risk", re.IGNORECASE),
        [
            re.compile(r"\bitem\s+1b\b", re.IGNORECASE),
            re.compile(r"\bitem\s+2\b", re.IGNORECASE),
        ],
    ),
}

_SECTION_TITLES: dict[str, str] = {
    "Item 1": "Business",
    "Item 1A": "Risk Factors",
}


def _flatten_html_to_text(html: str) -> str:
    """HTML → plain text with whitespace normalized.

    BeautifulSoup tolerates malformed HTML (unclosed tags, missing
    quotes). We use ``get_text(separator=" ")`` so adjacent inline tags
    don't smush their text together. XBRL inline tags
    (``<ix:nonNumeric>`` etc.) carry their text content as children, so
    they get unwrapped naturally — only the tag *attributes* (which
    include ``contextRef`` and ``name="dei:..."``) are stripped.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Drop the HTML head/script/style noise — we only want body prose.
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    # Collapse runs of whitespace into single spaces. Preserves the
    # text content while making regex anchors match across line breaks
    # and non-breaking-space splits.
    return re.sub(r"\s+", " ", text).strip()


def _extract_section(html: str, *, section_id: str) -> str | None:
    """
    Pure HTML → section-text extractor. Returns None on:

    - Unsupported ``section_id`` raises ``ValueError`` (programming error).
    - No anchor match found in the flattened text.
    - Longest match is below the 500-char sanity threshold.
    """
    if section_id not in _SECTION_ANCHORS:
        raise ValueError(
            f"Unsupported section_id {section_id!r}. "
            f"Supported: {sorted(_SECTION_ANCHORS)}"
        )

    text = _flatten_html_to_text(html)
    if not text:
        return None

    start_pat, end_pats = _SECTION_ANCHORS[section_id]

    # Collect every start match and every end match, then pick the
    # (start, end) pair that produces the longest text between them.
    # The "longest" heuristic naturally skips TOC entries (short) and
    # picks the real section (long).
    best_text: str | None = None
    starts = [m.start() for m in start_pat.finditer(text)]
    if not starts:
        return None

    for start in starts:
        # Find the earliest end-anchor that occurs after this start.
        end_positions = [
            m.start()
            for end_pat in end_pats
            for m in end_pat.finditer(text)
            if m.start() > start
        ]
        if not end_positions:
            continue
        end = min(end_positions)
        candidate = text[start:end].strip()
        if best_text is None or len(candidate) > len(best_text):
            best_text = candidate

    if best_text is None or len(best_text) < _MIN_SECTION_CHARS:
        return None
    return best_text


# ── Async entry points ────────────────────────────────────────────────


async def _extract_from_filing_index(
    symbol: str,
    *,
    section_id: str,
    filing_index: int,
    edgar_provider: str,
) -> Extracted10KSection | None:
    """
    Shared coordination layer: fetch ``filing_index + 1`` 10-Ks via
    fetch_edgar (with text), pick the ``filing_index``-th, extract the
    requested section, return as ``Extracted10KSection`` or None.

    Wrapped in ``log_external_call`` so the observability stream
    records whether extraction succeeded — important for measuring
    regex hit-rate against real filers without instrumenting an
    additional layer.
    """
    target = symbol.upper()
    section_label = (
        "ten_k_business" if section_id == "Item 1" else "ten_k_risks"
    )
    service_id = f"{edgar_provider}.{section_label}"

    with log_external_call(
        service_id,
        {
            "symbol": target,
            "edgar_provider": edgar_provider,
            "section_id": section_id,
        },
    ) as call:
        # Fetch enough filings to cover the requested index. recent_n is
        # filing_index+1 (1 for current, 2 for prior, etc.).
        filings = await fetch_edgar(
            target,
            form_type="10-K",
            recent_n=filing_index + 1,
            include_text=True,
            provider=edgar_provider,
        )

        if len(filings) <= filing_index:
            call.record_output({"extracted": False, "reason": "no_filing_at_index"})
            return None

        filing = filings[filing_index]
        if not filing.primary_doc_text:
            call.record_output({"extracted": False, "reason": "no_text"})
            return None

        text = _extract_section(filing.primary_doc_text, section_id=section_id)
        if text is None:
            call.record_output({"extracted": False, "reason": "anchors_not_found"})
            return None

        call.record_output({"extracted": True, "char_count": len(text)})

    return Extracted10KSection(
        symbol=target,
        accession=filing.accession,
        filed_at=filing.filed_at,
        period_of_report=filing.period_of_report,
        section_id=section_id,
        section_title=_SECTION_TITLES[section_id],
        text=text,
        char_count=len(text),
        primary_doc_url=filing.primary_doc_url,
    )


async def extract_10k_business(
    symbol: str,
    *,
    edgar_provider: str = "sec",
) -> Extracted10KSection | None:
    """Extract Item 1 (Business) from the most recent 10-K. None on miss."""
    return await _extract_from_filing_index(
        symbol,
        section_id="Item 1",
        filing_index=0,
        edgar_provider=edgar_provider,
    )


async def extract_10k_risks(
    symbol: str,
    *,
    prior: bool = False,
    edgar_provider: str = "sec",
) -> Extracted10KSection | None:
    """
    Extract Item 1A (Risk Factors).

    ``prior=False`` (default): most recent 10-K. ``prior=True``: the
    second most recent — the agent calls this twice (once for each
    year) and the synth call writes "what's new in risks" prose by
    comparing the two ``.text`` fields.
    """
    return await _extract_from_filing_index(
        symbol,
        section_id="Item 1A",
        filing_index=1 if prior else 0,
        edgar_provider=edgar_provider,
    )


# Re-exported so tests can monkey-patch ``fetch_edgar`` at this module's
# import boundary (the same pattern form_4 uses).
__all__ = [
    "Extracted10KSection",
    "extract_10k_business",
    "extract_10k_risks",
    "fetch_edgar",  # noqa: F822 — surfaced for monkeypatch in tests
]


def _ten_k_module_attrs() -> dict[str, Any]:
    """Test introspection helper — not part of the public API."""
    return {"_extract_section": _extract_section}
