"""
Tests for ``app.services.risk_categorizer``.

The categorizer takes the added/removed paragraph lists from a 10-K
year-over-year diff and produces a per-bucket net delta. Internally it
calls ``llm.triage_call`` (Haiku 4.5) with a forced-schema tool — the
real LLM is never hit in unit tests; we patch ``triage_call`` to return
a hand-crafted ``RiskCategorization`` instance.

What's being pinned:

1. Short-circuit on empty inputs — never spend Haiku tokens on a
   stable disclosure.
2. Aggregation math — added paragraphs contribute +1 to their
   category, removed contribute -1, zero-net buckets are dropped.
3. Defensive parsing — out-of-range indices and unknown actions in
   the model's response are dropped silently rather than crashing
   the whole call.
4. Pass-through structure — the categorizer's input prompt actually
   carries the paragraph text, so a Haiku that returned random
   classifications would still be schema-valid (the test pins the
   wiring, not the model's accuracy).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.schemas.ten_k import RiskCategory


# ── Module-under-test imports ─────────────────────────────────────────
# ``categorize_risk_paragraphs`` and the schema lands in
# ``app.services.risk_categorizer`` (Phase 4.3.B). The test imports them
# directly so a missing module fails the collection cleanly.


async def test_short_circuits_on_empty_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stable disclosures (no added, no removed) skip the Haiku call —
    cost discipline. Returns ``{}`` immediately."""
    from app.services import risk_categorizer as cat_module

    called = {"count": 0}

    async def _fake_triage(*_a: Any, **_kw: Any) -> Any:
        called["count"] += 1
        raise RuntimeError("should not have been called")

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_risk_paragraphs([], [])
    assert result == {}
    assert called["count"] == 0


async def test_aggregates_added_and_removed_into_net_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Added paragraphs contribute +1; removed contribute -1.
    Zero-net buckets are dropped from the result so the card renders
    only the categories with a real signal."""
    from app.services import risk_categorizer as cat_module
    from app.services.risk_categorizer import (
        ParagraphCategory,
        RiskCategorization,
    )

    added = [
        "AI regulation in the EU is tightening.",
        "Export controls on AI accelerators expanded.",
        "We rely on TSMC for advanced node fab capacity.",
    ]
    removed = [
        "We compete with NVIDIA, AMD, and Intel in datacenter compute.",
    ]

    fake_response = RiskCategorization(
        categorizations=[
            ParagraphCategory(
                action="added", index=0, category=RiskCategory.AI_REGULATORY
            ),
            ParagraphCategory(
                action="added", index=1, category=RiskCategory.EXPORT_CONTROLS
            ),
            ParagraphCategory(
                action="added",
                index=2,
                category=RiskCategory.SUPPLY_CONCENTRATION,
            ),
            ParagraphCategory(
                action="removed", index=0, category=RiskCategory.COMPETITION
            ),
        ]
    )

    async def _fake_triage(*_a: Any, **_kw: Any) -> RiskCategorization:
        return fake_response

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_risk_paragraphs(added, removed)

    assert result == {
        RiskCategory.AI_REGULATORY: 1,
        RiskCategory.EXPORT_CONTROLS: 1,
        RiskCategory.SUPPLY_CONCENTRATION: 1,
        RiskCategory.COMPETITION: -1,
    }


async def test_drops_zero_net_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A category that has equal adds and removes (e.g. paragraphs
    reshuffled within Cybersecurity) nets to zero and shouldn't appear
    in the result — otherwise the card draws an empty bar."""
    from app.services import risk_categorizer as cat_module
    from app.services.risk_categorizer import (
        ParagraphCategory,
        RiskCategorization,
    )

    fake_response = RiskCategorization(
        categorizations=[
            ParagraphCategory(
                action="added", index=0, category=RiskCategory.CYBERSECURITY
            ),
            ParagraphCategory(
                action="removed", index=0, category=RiskCategory.CYBERSECURITY
            ),
            ParagraphCategory(
                action="added", index=1, category=RiskCategory.AI_REGULATORY
            ),
        ]
    )

    async def _fake_triage(*_a: Any, **_kw: Any) -> RiskCategorization:
        return fake_response

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_risk_paragraphs(
        added=["a", "b"], removed=["c"]
    )
    # Cybersecurity dropped (net 0); AI_REGULATORY survives (+1).
    assert RiskCategory.CYBERSECURITY not in result
    assert result == {RiskCategory.AI_REGULATORY: 1}


async def test_defensive_against_out_of_range_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed Haiku response (index past the input list, unknown
    action) shouldn't crash — drop the offending rows and aggregate
    the remaining good ones."""
    from app.services import risk_categorizer as cat_module
    from app.services.risk_categorizer import (
        ParagraphCategory,
        RiskCategorization,
    )

    fake_response = RiskCategorization(
        categorizations=[
            ParagraphCategory(
                action="added", index=0, category=RiskCategory.MACRO
            ),
            # Bogus index — only 1 added paragraph exists at index 0.
            ParagraphCategory(
                action="added", index=42, category=RiskCategory.MACRO
            ),
            # Bogus action — neither "added" nor "removed". Ideally
            # caught at schema-validation time; if it sneaks through
            # in a future Haiku revision, drop it.
            ParagraphCategory(
                action="removed", index=99, category=RiskCategory.MACRO
            ),
        ]
    )

    async def _fake_triage(*_a: Any, **_kw: Any) -> RiskCategorization:
        return fake_response

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_risk_paragraphs(
        added=["macro headwinds"], removed=[]
    )
    # Only the in-range +1 survives.
    assert result == {RiskCategory.MACRO: 1}


async def test_user_prompt_includes_each_paragraph_and_action_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the wire: the prompt must carry every paragraph and label
    it as ADDED-i / REMOVED-j so the model can produce a correct
    classification list. Without this, the model has nothing to ground
    on and would return garbage."""
    from app.services import risk_categorizer as cat_module
    from app.services.risk_categorizer import RiskCategorization

    captured: dict[str, Any] = {}

    async def _fake_triage(prompt: str, schema: type, **kwargs: Any) -> Any:
        captured["prompt"] = prompt
        captured["schema"] = schema
        return RiskCategorization(categorizations=[])

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    added = ["Paragraph about AI regulation.", "Paragraph about supply chain."]
    removed = ["Old paragraph about competition."]

    await cat_module.categorize_risk_paragraphs(added, removed)

    prompt = captured["prompt"]
    # Every paragraph appears verbatim and is action/index-labeled.
    assert "[ADDED-0]" in prompt
    assert "[ADDED-1]" in prompt
    assert "[REMOVED-0]" in prompt
    for para in added + removed:
        assert para in prompt
    # Schema is the categorization shape, not some other type.
    assert captured["schema"] is RiskCategorization
