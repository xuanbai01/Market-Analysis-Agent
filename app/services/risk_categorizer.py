"""
Haiku-driven categorizer for Item 1A risk-paragraph deltas. Phase 4.3.B.

Takes the ``added_paragraphs`` + ``removed_paragraphs`` lists from a
``Risk10KDiff`` and produces a per-bucket net delta — added paragraphs
contribute +1 to their category, removed contribute -1, zero-net
buckets are filtered out so the bar chart only renders signal.

## Cost discipline

- One Haiku call per (issuer, year) on uncached input. Typical AAPL-class
  diff: 10–20 paragraphs × ~75 input tokens each ≈ 1.5K input tokens
  + 500-token cached system prompt. At Haiku 4.5 prices that's well
  under $0.005/report; stable disclosures (no paragraphs added or
  removed) skip the LLM call entirely and pay nothing.
- The system prompt carries the bucket definitions + one-line examples
  and is wrapped in ephemeral cache control by the LLM client, so
  repeated runs over many issuers hit the prefix cache.

## Defensive parsing

Haiku's output is schema-forced through ``RiskCategorization``, so a
malformed shape raises Pydantic at the LLM client layer. We add a
second layer of defense for *valid-shape but nonsensical* responses:
  - ``index`` past the end of the input list → drop the row.
  - ``action`` not matching the input list bounds → drop the row.

These checks let a Haiku revision that occasionally hallucinates an
extra index degrade gracefully instead of corrupting category counts.

## Failure modes upstream

When the orchestrator's ``extract_10k_risks_diff`` calls this and we
raise (rate limit, network, malformed schema), the caller catches and
falls back to ``category_deltas={}`` so the diff still ships and the
card degrades to its 4-bar aggregate display.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ten_k import RiskCategory
from app.services import llm

# ── Forced-tool schema ───────────────────────────────────────────────


class ParagraphCategory(BaseModel):
    """One classification: which paragraph (by action + index) belongs
    to which category. ``action`` is the literal "added" or "removed"
    matching the labels in the user prompt; ``index`` is 0-based within
    that list."""

    model_config = ConfigDict(frozen=True)

    action: Literal["added", "removed"]
    index: int = Field(ge=0)
    category: RiskCategory


class RiskCategorization(BaseModel):
    """The full forced-tool output: one classification per input
    paragraph. Order doesn't matter; we aggregate by (action, index)."""

    model_config = ConfigDict(frozen=True)

    categorizations: list[ParagraphCategory] = Field(default_factory=list)


# ── Prompt templates ─────────────────────────────────────────────────
# System prompt is constant — cache-friendly. Identical across calls
# for every issuer / year pair so the 5-min ephemeral TTL on the
# Anthropic side accumulates hits when the orchestrator processes
# multiple symbols in one cache window.

_SYSTEM_PROMPT = """You are a financial-disclosure classifier.

You are given a list of paragraphs from the Item 1A "Risk Factors"
section of a US-listed company's 10-K filing, each labeled as either
ADDED (newly present this year) or REMOVED (present last year, gone
this year).

Classify each paragraph into exactly one of these nine buckets:

- ai_regulatory: AI regulation, government rules on AI/ML systems,
  algorithmic-bias laws, AI safety frameworks.
- export_controls: export licensing, sanctions, trade restrictions on
  technology, US-China bilateral chip controls, EAR/ITAR.
- supply_concentration: dependence on a small number of suppliers,
  contract manufacturers (TSMC, Foxconn), critical raw materials, geo
  single-source supply.
- customer_concentration: dependence on a small number of customers
  (often hyperscalers, sovereign buyers, OEMs); reseller-heavy demand.
- competition: competitive pressure, market share threats, new
  entrants, pricing pressure, product substitutes.
- cybersecurity: cyber attacks, data breaches, ransomware, infrastructure
  threats, intrusions targeting customers or company systems.
- ip: patent disputes, trade-secret litigation, copyright, IP
  enforcement risks, third-party IP claims.
- macro: macroeconomic conditions, FX, interest rates, recession,
  inflation, broad consumer demand softening.
- other: anything that doesn't cleanly fit one of the buckets above.

Output one ParagraphCategory entry per input paragraph. Use the EXACT
action label ("added" or "removed") and the 0-based index that appears
in the user prompt's [ADDED-i] / [REMOVED-j] labels."""


def _build_user_prompt(added: list[str], removed: list[str]) -> str:
    """Concatenate the labeled paragraphs into the user-message body.

    Format mirrors what the system prompt instructs the model to look
    for: ``[ADDED-i] <text>`` and ``[REMOVED-j] <text>``, blank-line
    separated. Keeps the prompt grep-friendly so a future debug run
    can correlate the rendered classification back to its input.
    """
    blocks: list[str] = []
    for i, p in enumerate(added):
        blocks.append(f"[ADDED-{i}] {p}")
    for j, p in enumerate(removed):
        blocks.append(f"[REMOVED-{j}] {p}")
    return "\n\n".join(blocks)


# ── Public entry point ───────────────────────────────────────────────


async def categorize_risk_paragraphs(
    added: list[str],
    removed: list[str],
) -> dict[RiskCategory, int]:
    """Classify each paragraph and return net delta per bucket.

    Short-circuits to ``{}`` when there's nothing to classify — no LLM
    cost on stable disclosures. Otherwise issues one ``triage_call``
    (Haiku) with the forced ``RiskCategorization`` tool schema.

    Returns a dict keyed by ``RiskCategory`` with int values. Buckets
    that net to zero across added + removed are dropped so the bar
    chart renders only meaningful signal.
    """
    if not added and not removed:
        return {}

    response = await llm.triage_call(
        prompt=_build_user_prompt(added, removed),
        schema=RiskCategorization,
        system=_SYSTEM_PROMPT,
    )

    deltas: dict[RiskCategory, int] = {}
    for row in response.categorizations:
        # Defensive: drop classifications whose index is out of range
        # for the relevant list. Schema-validation guards types; this
        # guards values.
        if row.action == "added":
            if row.index < 0 or row.index >= len(added):
                continue
            deltas[row.category] = deltas.get(row.category, 0) + 1
        elif row.action == "removed":
            if row.index < 0 or row.index >= len(removed):
                continue
            deltas[row.category] = deltas.get(row.category, 0) - 1
        # No else — Literal["added", "removed"] guarantees no third
        # value can sneak through schema validation.

    # Drop zero-net buckets so the card doesn't render empty bars.
    return {cat: d for cat, d in deltas.items() if d != 0}
