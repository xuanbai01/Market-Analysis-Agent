"""
Haiku-driven news headline categorizer. Phase 4.4.A.

Mirrors the ``risk_categorizer`` (Phase 4.3.B) pattern. Takes a list
of headlines, classifies each into a category bucket + sentiment via
one Haiku ``triage_call``, and returns a per-index dict.

## Cost discipline

- One Haiku call per (issuer, report) on uncached input. 20–30
  headlines × ~30 input tokens each ≈ 600 input tokens + a 500-token
  cached system prompt. At Haiku 4.5 prices that's well under
  $0.005/report; empty-headline reports skip the LLM call entirely.
- The system prompt is constant across calls (same 7 categories +
  3-sentiment definitions) so it hits the prompt-cache after the
  first run within the 5-minute TTL.

## Defensive parsing

The LLM is forced into the ``NewsCategorization`` Pydantic schema, so
shape errors raise at the LLM client. We add a second layer of
defense for valid-shape but nonsensical responses (index past end of
input list) — those rows are dropped silently.

## Failure modes upstream

When ``news.fetch_news`` calls this and the categorizer raises (rate
limit, network, malformed schema), the news tool catches and falls
back to a `category=other, sentiment=neutral` default per article so
the dashboard still ships news cards on degraded backends.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.services import llm


class NewsCategory(str, Enum):
    """Buckets the categorizer sorts each headline into. String-valued
    so JSONB / Zod round-trip both stay happy."""

    EARNINGS = "earnings"
    PRODUCT = "product"
    REGULATORY = "regulatory"
    M_AND_A = "m_and_a"
    SUPPLY = "supply"
    STRATEGY = "strategy"
    OTHER = "other"


class NewsSentiment(str, Enum):
    """Three-way sentiment. The frontend renders a colored dot per
    item; the dashboard's filter pills don't filter on sentiment yet,
    but the field is here for future expansion."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class HeadlineClassification(BaseModel):
    """One classification: which headline (by index) goes in which
    bucket with what sentiment. ``index`` is 0-based within the input
    list."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    category: NewsCategory
    sentiment: NewsSentiment


class NewsCategorization(BaseModel):
    """Forced-tool output: one classification per input headline."""

    model_config = ConfigDict(frozen=True)

    classifications: list[HeadlineClassification] = Field(default_factory=list)


# ── Prompt templates ─────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a financial-news classifier.

You are given a list of news headlines about a US-listed company.
Classify each into exactly one bucket and assign a three-way sentiment.

Categories:
- earnings: quarterly results, beats/misses, guidance, consensus revisions.
- product: product launches, feature announcements, design wins.
- regulatory: government action, antitrust, FTC/SEC/EU probes, fines,
  new compliance requirements.
- m_and_a: mergers, acquisitions, divestitures, LBOs, take-privates.
- supply: supply chain, manufacturing partners (TSMC, Foxconn), tariffs,
  raw materials, capacity constraints.
- strategy: leadership changes, restructuring, share buybacks, dividend
  changes, broad strategic pivots.
- other: anything that doesn't cleanly fit one of the buckets above.

Sentiment:
- positive: clearly favorable to the company's stock or fundamentals.
- negative: clearly unfavorable.
- neutral: factual reporting without a clear directional read, or
  mixed.

Output one HeadlineClassification entry per input headline. Use the
EXACT 0-based index that appears in the user prompt's [HEADLINE-i]
labels."""


def _build_user_prompt(headlines: list[str]) -> str:
    """Concatenate the labeled headlines into the user-message body.

    Format: ``[HEADLINE-i] <text>`` blank-line separated. Mirrors what
    the system prompt instructs the model to look for.
    """
    return "\n\n".join(f"[HEADLINE-{i}] {h}" for i, h in enumerate(headlines))


# ── Public entry point ───────────────────────────────────────────────


async def categorize_news_headlines(
    headlines: list[str],
) -> dict[int, dict[str, str]]:
    """Classify each headline; return ``{index: {category, sentiment}}``.

    Empty input → empty dict (no LLM cost on stories with no recent
    news). Otherwise issues one ``triage_call`` (Haiku) and assembles
    the per-index dict, dropping any classification whose ``index``
    is out of range for the input list.
    """
    if not headlines:
        return {}

    response = await llm.triage_call(
        prompt=_build_user_prompt(headlines),
        schema=NewsCategorization,
        system=_SYSTEM_PROMPT,
    )

    out: dict[int, dict[str, str]] = {}
    for row in response.classifications:
        if row.index < 0 or row.index >= len(headlines):
            continue
        out[row.index] = {
            "category": row.category.value,
            "sentiment": row.sentiment.value,
        }
    return out
