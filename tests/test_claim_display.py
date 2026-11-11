"""
``format_claim_value`` renders a claim value the way the dashboard does
(``frontend/src/lib/format.ts::formatClaimValue``), so the synth prompt
can hand the LLM display values instead of raw stored ones.

Why (2026-11 dogfood, tasks/dogfood-2026-11.md #1): the prompt sent
``repr(value)``, so DeepSeek wrote "return on equity of 1.42" and "a
buyback yield of 0.017 against a forward dividend yield of 0.32" — the
two yields are stored in different forms (fraction vs percent), so the
raw numbers inverted the real comparison (1.74% vs 0.32%).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.research import Claim, Section, Source
from app.services.claim_display import format_claim_value
from tests.evals.rubric import score_factuality


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (1.4226, "fraction", "142.26%"),
        (0.276, "fraction", "27.60%"),
        (-0.41, "fraction", "-41.00%"),
        (0.32, "percent", "0.32%"),
        (4.98e12, "usd", "$4.98T"),
        (888_270_000_000, "usd", "$888.27B"),
        (19_870_000, "usd", "$19.87M"),
        (921.04, "usd", "$921.04"),
        (-2.5e9, "usd", "-$2.50B"),
        (0.1689, "usd_per_share", "$0.17"),
        (-1.49, "usd_per_share", "-$1.49"),
        (33.9234, "ratio", "33.92"),
        (131_590_000, "shares", "131.59M"),
        (12_345, "shares", "12,345"),
        (15, "count", "15"),
        (12_345, "count", "12,345"),
        (2.5, "count", "2.50"),
        (0.0043, "basis_points", "43 bps"),
        (0.0188, "percentage_points", "+1.88 pts"),
        (-0.005, "percentage_points", "-0.50 pts"),
        (0.0, "percentage_points", "0.00 pts"),
        (745_021.0, "usd_millions", "$745.02B"),
        (12_700.0, "thousands", "12.70M"),
        (850.0, "thousands", "850,000"),
        ("2027-01-28", "date", "2027-01-28"),
        ("Apple Inc.", "string", "Apple Inc."),
        (True, "count", "yes"),
    ],
)
def test_formats_like_the_dashboard(value: object, unit: str, expected: str) -> None:
    assert format_claim_value(value, unit) == expected


def test_none_value() -> None:
    assert format_claim_value(None, "fraction") == "None"


@pytest.mark.parametrize("value", [0.4879, 7.7375, "megacap_tech", 15])
def test_unannotated_values_keep_their_raw_form(value: object) -> None:
    """Claims from tools without unit annotations (peers, some earnings claims)
    keep today's ``repr`` so their prompt lines don't change."""
    assert format_claim_value(value, None) == repr(value)


def test_display_values_still_pass_the_factuality_rubric() -> None:
    """Prose that quotes the formatted values must still be matched to
    the stored values by the eval rubric — otherwise this change would
    trade a readability bug for a scoring regression."""
    src = Source(tool="yfinance.fundamentals", fetched_at=datetime.now(UTC))
    stored = [
        (1.4226, "fraction"),
        (0.0174, "fraction"),
        (0.32, "percent"),
        (4.98e12, "usd"),
        (0.1689, "usd_per_share"),
        (38.1306, "ratio"),
        (131_590_000, "shares"),
        (0.0188, "percentage_points"),
        (745_021.0, "usd_millions"),
        (12_700.0, "thousands"),
    ]
    claims = [
        Claim(description=f"metric {i}", value=v, unit=u, source=src)
        for i, (v, u) in enumerate(stored)
    ]
    prose = " ".join(f"Metric {i} is {format_claim_value(v, u)}." for i, (v, u) in enumerate(stored))
    section = Section(title="Quality", claims=claims, summary=prose)

    from app.schemas.research import Confidence, ResearchReport

    report = ResearchReport(
        symbol="AAPL",
        generated_at=datetime.now(UTC),
        sections=[section],
        overall_confidence=Confidence.HIGH,
    )
    result = score_factuality(report)
    assert result.unmatched_numbers == []
    assert result.score == 1.0
