"""
Tests for ``app.services.news_categorizer``. Phase 4.4.A.

Mirrors the ``risk_categorizer`` (Phase 4.3.B) pattern: takes a list of
headlines, runs one Haiku ``triage_call`` with a forced-tool schema,
returns a per-headline category + sentiment dict. The real LLM is
never hit — we patch ``llm.triage_call`` in every test.
"""
from __future__ import annotations

from typing import Any

import pytest


async def test_short_circuits_on_empty_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty headline list → no Haiku call. Cost discipline."""
    from app.services import news_categorizer as cat_module

    called = {"count": 0}

    async def _fake_triage(*_a: Any, **_kw: Any) -> Any:
        called["count"] += 1
        raise RuntimeError("should not have been called")

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_news_headlines([])
    assert result == {}
    assert called["count"] == 0


async def test_returns_per_index_category_and_sentiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: Haiku returns one classification per headline; the
    helper assembles a `{index: {category, sentiment}}` dict."""
    from app.services import news_categorizer as cat_module
    from app.services.news_categorizer import (
        HeadlineClassification,
        NewsCategorization,
        NewsCategory,
        NewsSentiment,
    )

    fake_response = NewsCategorization(
        classifications=[
            HeadlineClassification(
                index=0,
                category=NewsCategory.EARNINGS,
                sentiment=NewsSentiment.POSITIVE,
            ),
            HeadlineClassification(
                index=1,
                category=NewsCategory.PRODUCT,
                sentiment=NewsSentiment.NEUTRAL,
            ),
            HeadlineClassification(
                index=2,
                category=NewsCategory.REGULATORY,
                sentiment=NewsSentiment.NEGATIVE,
            ),
        ]
    )

    async def _fake_triage(*_a: Any, **_kw: Any) -> NewsCategorization:
        return fake_response

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    headlines = [
        "Apple beats Q1 estimates",
        "iPhone 17 launches in September",
        "EU opens antitrust probe into App Store",
    ]
    result = await cat_module.categorize_news_headlines(headlines)

    assert result == {
        0: {"category": "earnings", "sentiment": "positive"},
        1: {"category": "product", "sentiment": "neutral"},
        2: {"category": "regulatory", "sentiment": "negative"},
    }


async def test_drops_out_of_range_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed Haiku response (index past end of list) shouldn't
    crash. Drop the offending row, keep the valid ones."""
    from app.services import news_categorizer as cat_module
    from app.services.news_categorizer import (
        HeadlineClassification,
        NewsCategorization,
        NewsCategory,
        NewsSentiment,
    )

    fake_response = NewsCategorization(
        classifications=[
            HeadlineClassification(
                index=0,
                category=NewsCategory.EARNINGS,
                sentiment=NewsSentiment.POSITIVE,
            ),
            # Bogus index — only 1 headline at index 0.
            HeadlineClassification(
                index=42,
                category=NewsCategory.EARNINGS,
                sentiment=NewsSentiment.POSITIVE,
            ),
        ]
    )

    async def _fake_triage(*_a: Any, **_kw: Any) -> NewsCategorization:
        return fake_response

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    result = await cat_module.categorize_news_headlines(["Apple beats"])

    assert result == {
        0: {"category": "earnings", "sentiment": "positive"},
    }


async def test_user_prompt_includes_each_headline_with_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the wire: the prompt carries every headline labeled as
    [HEADLINE-i] so the model can correctly emit indexed
    classifications. Without this the model has nothing to ground on."""
    from app.services import news_categorizer as cat_module
    from app.services.news_categorizer import NewsCategorization

    captured: dict[str, Any] = {}

    async def _fake_triage(prompt: str, schema: type, **kwargs: Any) -> Any:
        captured["prompt"] = prompt
        captured["schema"] = schema
        return NewsCategorization(classifications=[])

    monkeypatch.setattr(cat_module.llm, "triage_call", _fake_triage)

    headlines = [
        "Apple beats Q1 estimates",
        "iPhone 17 launches in September",
    ]
    await cat_module.categorize_news_headlines(headlines)

    prompt = captured["prompt"]
    assert "[HEADLINE-0]" in prompt
    assert "[HEADLINE-1]" in prompt
    for h in headlines:
        assert h in prompt
    assert captured["schema"] is NewsCategorization
