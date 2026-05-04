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

## Three entry points, one extraction layer

- ``extract_10k_business(symbol)`` — fetches the latest 10-K, returns
  Item 1 as ``Extracted10KSection``.
- ``extract_10k_risks(symbol, prior=False)`` — same for Item 1A;
  ``prior=True`` returns the *second* most recent 10-K.
- ``extract_10k_risks_diff(symbol)`` — fetches both years in one
  ``fetch_edgar`` round-trip, splits each Item 1A into paragraphs, and
  buckets each paragraph as added / removed / kept via fuzzy similarity
  so cosmetic edits ("we" → "the Company") don't get flagged as new
  risks. Returns ``Risk10KDiff``. The agent reads only the small
  ``added_paragraphs`` list to write a high-confidence "what's new in
  risks" section — anti-hallucination wins over "let the LLM compare
  two ~50KB texts".

All three share ``_extract_section`` for the flat-text anchor pipeline;
the diff path additionally uses ``_extract_section_paragraphs`` for the
paragraph splits the diff operates on.

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
- Pre-computed summaries (extract moat / segments / customer
  concentration as separate Claims). The agent does this at synth
  time from raw text.
- Other Items (7 MD&A, 8 financials, etc.). Separate scope.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from bs4 import BeautifulSoup

from app.core.observability import log_external_call
from app.schemas.ten_k import Extracted10KSection, Risk10KDiff, RiskCategory
from app.services.edgar import fetch_edgar
from app.services.risk_categorizer import categorize_risk_paragraphs

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


# Block-level tags whose text content we treat as one paragraph. Used by
# the paragraph-aware extractor that backs the year-over-year risk diff.
# Headings count too: in real 10-Ks, "Item 1A. Risk Factors" lives in
# its own block element and we anchor on that block.
_PARAGRAPH_BLOCK_TAGS = (
    "p", "div", "li", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "tr",
)


def _flatten_html_to_paragraphs(html: str) -> list[str]:
    """HTML → ordered list of paragraphs, preserving block boundaries.

    Twin of ``_flatten_html_to_text`` for the diff path. Walks block
    tags in document order, collects each block's text content (with
    internal whitespace normalized to single spaces), drops empties.
    Block tags that *contain* other block tags (a ``<div>`` wrapping
    ``<p>`` children) are skipped to avoid double-counting — the
    children carry the same text and we want one paragraph per leaf.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    paragraphs: list[str] = []
    for block in soup.find_all(_PARAGRAPH_BLOCK_TAGS):
        # Skip block containers that nest other block tags — their text
        # is already collected from the leaf children.
        if block.find(_PARAGRAPH_BLOCK_TAGS):
            continue
        text = re.sub(r"\s+", " ", block.get_text(separator=" ")).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


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


def _extract_section_paragraphs(html: str, *, section_id: str) -> list[str] | None:
    """Paragraph-aware twin of ``_extract_section``.

    Returns the section's content paragraphs (heading paragraphs
    excluded) using the same anchor regexes and the same "longest
    candidate wins" heuristic as ``_extract_section`` — but operating
    over the paragraph list from ``_flatten_html_to_paragraphs`` rather
    than the flat text. Returns None on the same conditions: no anchor
    match, or total content below ``_MIN_SECTION_CHARS``.
    """
    if section_id not in _SECTION_ANCHORS:
        raise ValueError(
            f"Unsupported section_id {section_id!r}. "
            f"Supported: {sorted(_SECTION_ANCHORS)}"
        )

    paragraphs = _flatten_html_to_paragraphs(html)
    if not paragraphs:
        return None

    start_pat, end_pats = _SECTION_ANCHORS[section_id]
    start_indices = [i for i, p in enumerate(paragraphs) if start_pat.search(p)]
    if not start_indices:
        return None

    best: list[str] | None = None
    best_chars = 0
    for start_idx in start_indices:
        end_indices = [
            i
            for i, p in enumerate(paragraphs)
            if i > start_idx and any(end_pat.search(p) for end_pat in end_pats)
        ]
        if not end_indices:
            continue
        end_idx = min(end_indices)
        # Strip the heading paragraph itself (start_idx) and the next
        # section's heading (end_idx) — keep only content in between.
        candidate = paragraphs[start_idx + 1 : end_idx]
        chars = sum(len(p) for p in candidate)
        if chars > best_chars:
            best = candidate
            best_chars = chars

    if best is None or best_chars < _MIN_SECTION_CHARS:
        return None
    return best


# Default similarity threshold for paragraph-level fuzzy matching.
# 0.6 catches "we" → "the Company" rewordings while still flagging
# substantively different paragraphs as added/removed. Tunable per call.
_DEFAULT_PARAGRAPH_SIMILARITY = 0.6


def _paragraph_diff(
    current: list[str],
    prior: list[str],
    *,
    similarity_threshold: float = _DEFAULT_PARAGRAPH_SIMILARITY,
) -> tuple[list[str], list[str], int]:
    """Bucket paragraphs into ``(added, removed, kept_count)``.

    For each paragraph in ``current``, compute its max
    ``SequenceMatcher.ratio()`` against any paragraph in ``prior``;
    below ``similarity_threshold`` → added. Symmetric pass for removed.
    ``kept_count`` is ``len(current) - len(added)`` — the number of
    this year's risks that already appeared (verbatim or reworded) in
    last year's. Order is preserved.

    Cost: O(N·M) ratio calls, each O(n·m) on the underlying strings.
    For a typical Item 1A (~50 paragraphs × ~50 paragraphs × ~1KB each)
    this is well under a second.
    """

    def _max_ratio(text: str, candidates: list[str]) -> float:
        if not candidates:
            return 0.0
        return max(SequenceMatcher(None, text, c).ratio() for c in candidates)

    added = [p for p in current if _max_ratio(p, prior) < similarity_threshold]
    removed = [p for p in prior if _max_ratio(p, current) < similarity_threshold]
    kept_count = len(current) - len(added)
    return added, removed, kept_count


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
    second most recent. For year-over-year "what's new in risks"
    analysis, prefer ``extract_10k_risks_diff`` — it does the
    paragraph-level diff mechanically rather than asking the agent to
    compare two ~50KB texts at synth time.
    """
    return await _extract_from_filing_index(
        symbol,
        section_id="Item 1A",
        filing_index=1 if prior else 0,
        edgar_provider=edgar_provider,
    )


def _filing_to_section(
    filing: Any,
    *,
    section_id: str,
    symbol: str,
) -> Extracted10KSection | None:
    """Pure conversion: ``EdgarFiling`` → ``Extracted10KSection`` or None.

    Returns None when the filing has no ``primary_doc_text`` or when the
    section anchors don't match in the text. Shared between the diff
    path (which fetches two filings in one round trip) and any future
    caller that already has the filing in hand.
    """
    if not filing.primary_doc_text:
        return None
    text = _extract_section(filing.primary_doc_text, section_id=section_id)
    if text is None:
        return None
    return Extracted10KSection(
        symbol=symbol,
        accession=filing.accession,
        filed_at=filing.filed_at,
        period_of_report=filing.period_of_report,
        section_id=section_id,
        section_title=_SECTION_TITLES[section_id],
        text=text,
        char_count=len(text),
        primary_doc_url=filing.primary_doc_url,
    )


async def extract_10k_risks_diff(
    symbol: str,
    *,
    edgar_provider: str = "sec",
) -> Risk10KDiff | None:
    """
    Year-over-year diff of Item 1A across the two most recent 10-Ks.

    Mechanical paragraph-level diff with fuzzy match (default 0.6
    similarity) so cosmetic edits don't get flagged as new risks. The
    agent reads only ``added_paragraphs`` to write a high-confidence
    "what's new in risks" section — citation discipline preserved
    because each new paragraph is an exact substring of ``current.text``.

    Returns None when fewer than two 10-Ks are available, or when
    Item 1A can't be extracted from either filing. One ``fetch_edgar``
    round-trip; one ``log_external_call`` record (``sec.ten_k_risks_diff``).
    """
    target = symbol.upper()
    section_id = "Item 1A"
    service_id = f"{edgar_provider}.ten_k_risks_diff"

    with log_external_call(
        service_id,
        {"symbol": target, "edgar_provider": edgar_provider},
    ) as call:
        filings = await fetch_edgar(
            target,
            form_type="10-K",
            recent_n=2,
            include_text=True,
            provider=edgar_provider,
        )

        if len(filings) < 2:
            call.record_output({"available": False, "reason": "fewer_than_2_filings"})
            return None

        current_section = _filing_to_section(
            filings[0], section_id=section_id, symbol=target
        )
        prior_section = _filing_to_section(
            filings[1], section_id=section_id, symbol=target
        )
        if current_section is None or prior_section is None:
            call.record_output({"available": False, "reason": "extraction_failed"})
            return None

        current_paras = (
            _extract_section_paragraphs(
                filings[0].primary_doc_text, section_id=section_id
            )
            or []
        )
        prior_paras = (
            _extract_section_paragraphs(
                filings[1].primary_doc_text, section_id=section_id
            )
            or []
        )
        added, removed, kept_count = _paragraph_diff(current_paras, prior_paras)

        # Phase 4.3.B — Haiku-categorize each added/removed paragraph
        # into one of 9 RiskCategory buckets. Short-circuits to {}
        # internally when both lists are empty (no LLM cost on stable
        # disclosures). Catches any failure (rate limit, network,
        # malformed schema response) and falls back to {} so the
        # research report still ships with the aggregate counts intact.
        category_deltas: dict[RiskCategory, int] = {}
        try:
            category_deltas = await categorize_risk_paragraphs(added, removed)
        except Exception:
            # Logged as part of the existing log_external_call frame —
            # outcome stays "ok" because the diff itself succeeded.
            category_deltas = {}

        call.record_output(
            {
                "available": True,
                "added_count": len(added),
                "removed_count": len(removed),
                "kept_count": kept_count,
                "category_buckets": len(category_deltas),
            }
        )

    return Risk10KDiff(
        symbol=target,
        current=current_section,
        prior=prior_section,
        added_paragraphs=added,
        removed_paragraphs=removed,
        kept_paragraph_count=kept_count,
        char_delta=current_section.char_count - prior_section.char_count,
        category_deltas=category_deltas,
    )


# Re-exported so tests can monkey-patch ``fetch_edgar`` at this module's
# import boundary (the same pattern form_4 uses).
__all__ = [
    "Extracted10KSection",
    "Risk10KDiff",
    "extract_10k_business",
    "extract_10k_risks",
    "extract_10k_risks_diff",
    "fetch_edgar",  # noqa: F822 — surfaced for monkeypatch in tests
]


def _ten_k_module_attrs() -> dict[str, Any]:
    """Test introspection helper — not part of the public API."""
    return {"_extract_section": _extract_section}
