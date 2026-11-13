"""
The analyst view: a report-level thesis written from the section claims.

Phase 5 (ADR 0005), ADR 0007 layer 2. The section prose explains each
card; this explains the company: a one-sentence headline, the bull and
bear cases, what changed over the past year, and what to watch.

Citation discipline carries over in two ways:

1. **Same rules as the section prose** — numbers only from the claims,
   never computed, display units, no outside facts, no advice.
2. **Every point names its evidence.** The prompt tags each claim with a
   short id ("Q3" = third Quality claim). The model lists the ids each
   point relies on; ``_resolve`` maps them to ``ClaimRef``s and drops any
   id that doesn't exist and any point left citing nothing — so the
   dashboard can link every argument to the claim behind it.

It runs alongside the section synthesis call and never fails the
report: any error returns ``None`` and the dashboard hides the card.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.schemas.research import (
    Claim,
    ClaimRef,
    LayoutSignals,
    Thesis,
    ThesisDraft,
    ThesisDraftPoint,
    ThesisPoint,
)
from app.services import llm
from app.services.claim_display import format_claim_line, format_claim_value

logger = logging.getLogger(__name__)

# Sections the thesis may cite, with the prefix of their claim ids.
# Left out on purpose:
# - Business: a 10-K text blob, no evidence a point could cite.
# - News: headlines are third-party and unverified. In the first live run
#   the model turned NVDA headlines about an investigation into its CEO
#   into a bear point, paraphrasing allegations about a named person and
#   citing risk-paragraph counts as the evidence. The analyst view argues
#   from financial data; the News card shows headlines as written.
SECTION_CODES: dict[str, str] = {
    "Valuation": "V",
    "Quality": "Q",
    "Capital Allocation": "C",
    "Earnings": "E",
    "Peers": "P",
    "Risk Factors": "R",
    "Macro": "M",
    "Insider Activity": "I",
}

# Points kept per list; the model is asked for fewer.
MAX_POINTS = {"bull": 3, "bear": 3, "changed": 3, "watch": 2}
MAX_REFS_PER_POINT = 4

THESIS_SYSTEM_PROMPT = """\
You are an equity analyst writing the "Analyst view" that opens a research \
dashboard. The user gives you the company's factual Claims, grouped by \
section; each line starts with an id in brackets ("[Q3]"). Write:

- ``headline``: one sentence — the central conclusion or tension the data \
supports (e.g. a strong business priced for it, an improving loss-maker \
burning cash). No buy/sell language.
- ``bull``: 2–3 points, the strongest evidence for the business and the \
shares.
- ``bear``: 2–3 points, the strongest evidence against. Argue both sides \
honestly even when the data leans one way.
- ``changed``: 2–3 points on what moved over the past year — use the \
change and growth claims (they name their quarters) and history lines.
- ``watch``: 1–2 points: the metric that would confirm or break the case, \
and why.

Each point has:
- ``title``: 2–6 plain words naming the point, in sentence case with no \
final period ("Margins still expanding", "Rich valuation vs peers", \
"Cash conversion slipping"). No numbers, tickers or symbols — the \
dashboard lists the titles, so a reader should get the case from them \
alone.
- ``text``: one or two sentences, at most 40 words, with the evidence.
- ``claim_ids``: the 1–3 ids of the claims it relies on — ids exactly as \
written in the brackets, and only the claims that actually hold the \
evidence (a point about free cash flow cites the free cash flow claims). \
Put the single most telling claim first: the dashboard shows its value \
beside the title, so the two must read together ("Margins far above \
peers" + "+11.73 pts"; "Unbroken beat streak" + the streak count, not the \
average surprise). A point whose ids don't match the list is discarded, \
so cite carefully.

Rules (non-negotiable):
1. Every number in your text must be a value shown in the claim lines \
(snapshot, history point, or description), in the display units shown. \
Never compute a number yourself — no differences, ratios or growth rates \
of your own; the comparisons you need are already claims.
2. For a signed change, say the direction in words and drop the sign \
("down 2.65 pts").
3. No outside facts: whatever you know about the company from elsewhere \
stays out — no product, model or brand names, events, management \
actions, competitors' news or macro causes unless they appear in the \
claims. If a sector note is given, follow it.
4. No forecasts, price targets or advice. Hedged interpretation \
("suggests", "leaves less room for") is fine.
5. Plain prose, no markdown.
6. A value is as of when its description says: a claim described as \
"at fiscal year-end" or "annual" belongs to the fiscal year its history \
ends on, not to today. Say "today" or "currently" only for trailing \
figures and for the claims that compare today with a median.
"""


def _assign_ids(section_claims: Mapping[str, Sequence[Claim]]) -> dict[str, ClaimRef]:
    """Id → claim location, for every citable section, in prompt order."""
    ids: dict[str, ClaimRef] = {}
    for title, claims in section_claims.items():
        code = SECTION_CODES.get(title)
        if code is None:
            continue
        for index in range(len(claims)):
            ids[f"{code}{index + 1}"] = ClaimRef(section=title, index=index)
    return ids


def build_thesis_prompt(
    symbol: str,
    section_claims: Mapping[str, Sequence[Claim]],
    sector: str | None = None,
    sector_note: str | None = None,
    layout_signals: LayoutSignals | None = None,
) -> str:
    lines = [f"Symbol: {symbol}"]
    if sector:
        lines.append(f"Sector: {sector}")
    if sector_note:
        lines.append(f"Sector note: {sector_note}")
    if layout_signals is not None and layout_signals != LayoutSignals():
        active = [name for name, value in layout_signals.model_dump().items() if value not in (False, None)]
        lines.append(f"Distress signals: {', '.join(active)} — weigh survival over quality.")
    lines += ["", "Write the analyst view from these claims.", ""]
    for title, claims in section_claims.items():
        code = SECTION_CODES.get(title)
        if code is None or not claims:
            continue
        lines.append(f"## {title}")
        for index, claim in enumerate(claims):
            lines.append(format_claim_line(claim, claim_id=f"{code}{index + 1}"))
        lines.append("")
    return "\n".join(lines)


# Quarter labels, ISO dates and years are not evidence values.
_LABEL_RE = re.compile(r"\b\d{4}-Q[1-4]\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b")
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [value for value, _ in _quotes(text)]


def _quotes(text: str) -> list[tuple[float, int]]:
    """Numbers in ``text`` with their decimal places ("74.7" → (74.7, 1))."""
    out: list[tuple[float, int]] = []
    for token in _NUMBER_RE.findall(_LABEL_RE.sub(" ", text)):
        plain = token.replace(",", "")
        decimals = len(plain.split(".")[1]) if "." in plain else 0
        out.append((float(plain), decimals))
    return out


def _claim_numbers(claim: Claim) -> list[float]:
    """The numbers the prompt showed for this claim — the snapshot and its
    history's first, last, low and high — in display form ("74.67%" →
    74.67) and raw. Matching every history point instead let a claim
    through on a coincidence (an OCF-per-share quarter of $1.16 "matched"
    a 1.16-pt margin change)."""
    history = [p.value for p in claim.history]
    endpoints = [history[0], history[-1], min(history), max(history)] if history else []
    values = [claim.value, *endpoints]
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int | float):
            continue
        out.append(abs(float(v)))
        out.extend(_numbers(format_claim_value(v, claim.unit)))
    return out


def _quoted(quotes: Sequence[tuple[float, int]], claim: Claim) -> bool:
    """True when the text quotes one of the claim's numbers, or when the
    claim has no number to check against. A quote matches when it is the
    claim's number rounded to the quote's precision: "74.7" or "75" for
    74.67, but not "1.16" for 1.14."""
    claim_numbers = _claim_numbers(claim)
    if not claim_numbers:
        return True
    return any(
        abs(c - value) <= 0.5 * 10**-decimals + 1e-9
        for value, decimals in quotes
        for c in claim_numbers
    )


MAX_TITLE_WORDS = 8
MAX_TITLE_CHARS = 60


def _clean_title(raw: str) -> str | None:
    """A point's title, or None when unusable. Titles carry no digits:
    the rubric checks numbers in the text, and the dashboard shows the
    point's figure from its first cited claim, so a number in the title
    would be the only one nothing checks."""
    title = raw.strip().rstrip(".:;,").strip()
    if not title or any(ch.isdigit() for ch in title):
        return None
    if len(title) > MAX_TITLE_CHARS or len(title.split()) > MAX_TITLE_WORDS:
        return None
    return title


def resolve_points(
    points: Sequence[ThesisDraftPoint],
    ids: Mapping[str, ClaimRef],
    limit: int,
    section_claims: Mapping[str, Sequence[Claim]] | None,
) -> list[ThesisPoint]:
    out: list[ThesisPoint] = []
    for point in points:
        text = point.text.strip()
        quotes = _quotes(text)
        refs: list[ClaimRef] = []
        for raw in point.claim_ids:
            ref = ids.get(raw.strip().strip("[]").upper())
            if ref is None or ref in refs:
                continue
            # A point that quotes numbers keeps only the claims it quotes:
            # the model sometimes cites a neighbouring claim, and a chip
            # pointing at the wrong evidence is worse than none.
            if section_claims is not None and quotes:
                if not _quoted(quotes, section_claims[ref.section][ref.index]):
                    continue
            refs.append(ref)
        if text and refs:
            out.append(
                ThesisPoint(text=text, claim_refs=refs[:MAX_REFS_PER_POINT], title=_clean_title(point.title))
            )
        if len(out) == limit:
            break
    return out


def resolve_draft(
    draft: ThesisDraft,
    ids: Mapping[str, ClaimRef],
    section_claims: Mapping[str, Sequence[Claim]] | None = None,
) -> Thesis | None:
    """Map a model draft onto the report; None if nothing usable remains.

    With ``section_claims``, a cited claim must be quoted in the point's
    text (when the point quotes any numbers) to count as its evidence."""
    headline = draft.headline.strip()
    resolved = {
        name: resolve_points(getattr(draft, name), ids, limit, section_claims)
        for name, limit in MAX_POINTS.items()
    }
    if not headline or not (resolved["bull"] or resolved["bear"]):
        return None
    return Thesis(headline=headline, **resolved)


async def compose_thesis(
    symbol: str,
    section_claims: Mapping[str, Sequence[Claim]],
    *,
    sector: str | None = None,
    sector_note: str | None = None,
    layout_signals: LayoutSignals | None = None,
) -> Thesis | None:
    """Write the analyst view. Never raises: on any failure, None."""
    ids = _assign_ids(section_claims)
    if not ids:
        return None
    prompt = build_thesis_prompt(symbol, section_claims, sector, sector_note, layout_signals)
    try:
        draft: Any = await llm.synth_call(prompt=prompt, schema=ThesisDraft, system=THESIS_SYSTEM_PROMPT)
    except Exception:  # the report stands without the analyst view
        logger.exception("thesis call failed for %s", symbol)
        return None
    if not isinstance(draft, ThesisDraft):
        return None
    return resolve_draft(draft, ids, section_claims)
