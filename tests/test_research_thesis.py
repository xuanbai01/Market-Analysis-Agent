"""
The analyst view (app/services/research_thesis.py).

The LLM is stubbed; these tests pin what code controls: which claims get
ids, how the prompt shows them, and that every point that survives cites
a real claim.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.research import (
    Claim,
    ClaimRef,
    LayoutSignals,
    SectionSummaries,
    Source,
    ThesisDraft,
    ThesisDraftPoint,
)
from app.services import research_thesis as rt

SRC = Source(tool="yfinance.fundamentals", fetched_at=datetime(2026, 11, 8, tzinfo=UTC))


def claim(description: str, value: Any, unit: str | None = None) -> Claim:
    return Claim(description=description, value=value, unit=unit, source=SRC)  # type: ignore[arg-type]


SECTIONS = {
    "Business": [claim("Business description", "Makes drinks.")],
    "Valuation": [claim("P/E ratio (trailing 12 months)", 28.22, "ratio")],
    "Quality": [
        claim("Operating margin", 0.3337, "fraction"),
        claim("Operating margin change, 2025-Q3 → 2026-Q3", 0.0116, "percentage_points"),
    ],
}


def draft(**lists: list[ThesisDraftPoint]) -> ThesisDraft:
    return ThesisDraft(headline="A durable franchise priced for durability.", **lists)


def p(text: str, *ids: str) -> ThesisDraftPoint:
    return ThesisDraftPoint(text=text, claim_ids=list(ids))


def test_claims_get_short_ids_by_section_and_position() -> None:
    ids = rt._assign_ids(SECTIONS)
    assert ids == {
        "V1": ClaimRef(section="Valuation", index=0),
        "Q1": ClaimRef(section="Quality", index=0),
        "Q2": ClaimRef(section="Quality", index=1),
    }


def test_prompt_tags_each_claim_with_its_id_in_display_units() -> None:
    prompt = rt.build_thesis_prompt("KO", SECTIONS, sector="consumer_staples")
    assert "Sector: consumer_staples" in prompt
    assert "- [V1] P/E ratio (trailing 12 months) = 28.22" in prompt
    assert "- [Q2] Operating margin change, 2025-Q3 → 2026-Q3 = +1.16 pts" in prompt
    assert "Business description" not in prompt  # nothing citable there


def test_prompt_flags_distress() -> None:
    prompt = rt.build_thesis_prompt("RIVN", SECTIONS, layout_signals=LayoutSignals(is_unprofitable_ttm=True))
    assert "is_unprofitable_ttm" in prompt


def test_points_resolve_to_claim_refs() -> None:
    thesis = rt.resolve_draft(
        draft(bull=[p("Margins widened 1.16 pts.", "Q2", "Q1")], bear=[p("Priced at 28.22x.", "[v1]")]),
        rt._assign_ids(SECTIONS),
    )
    assert thesis is not None
    assert thesis.bull[0].claim_refs == [
        ClaimRef(section="Quality", index=1),
        ClaimRef(section="Quality", index=0),
    ]
    # Brackets and case are forgiven; the id still has to exist.
    assert thesis.bear[0].claim_refs == [ClaimRef(section="Valuation", index=0)]


def test_points_citing_nothing_real_are_dropped() -> None:
    thesis = rt.resolve_draft(
        draft(
            bull=[p("Unsupported claim.", "Z9"), p("Supported.", "Q1")],
            bear=[p("No ids at all.")],
            watch=[p("Duplicate ids collapse.", "Q1", "Q1")],
        ),
        rt._assign_ids(SECTIONS),
    )
    assert thesis is not None
    assert [pt.text for pt in thesis.bull] == ["Supported."]
    assert thesis.bear == []
    assert thesis.watch[0].claim_refs == [ClaimRef(section="Quality", index=0)]


def test_lists_are_trimmed() -> None:
    many = [p(f"Point {i}.", "Q1") for i in range(6)]
    thesis = rt.resolve_draft(draft(bull=many, watch=many), rt._assign_ids(SECTIONS))
    assert thesis is not None
    assert len(thesis.bull) == rt.MAX_POINTS["bull"]
    assert len(thesis.watch) == rt.MAX_POINTS["watch"]


def test_a_thesis_needs_a_headline_and_at_least_one_case() -> None:
    ids = rt._assign_ids(SECTIONS)
    assert rt.resolve_draft(draft(changed=[p("Only change.", "Q2")]), ids) is None
    blank = ThesisDraft(headline="  ", bull=[p("Supported.", "Q1")])
    assert rt.resolve_draft(blank, ids) is None


async def test_compose_returns_none_when_the_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_kw: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(rt.llm, "synth_call", boom)
    assert await rt.compose_thesis("KO", SECTIONS) is None


async def test_compose_returns_none_on_the_wrong_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    async def wrong(**_kw: Any) -> Any:
        return SectionSummaries()

    monkeypatch.setattr(rt.llm, "synth_call", wrong)
    assert await rt.compose_thesis("KO", SECTIONS) is None


async def test_compose_sends_the_thesis_schema_and_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake(**kw: Any) -> Any:
        seen.update(kw)
        return draft(bull=[p("Margins widened.", "Q2")])

    monkeypatch.setattr(rt.llm, "synth_call", fake)
    thesis = await rt.compose_thesis("KO", SECTIONS, sector="consumer_staples")
    assert thesis is not None and thesis.bull[0].text == "Margins widened."
    assert seen["schema"] is ThesisDraft
    assert seen["system"] == rt.THESIS_SYSTEM_PROMPT
    assert "[Q2]" in seen["prompt"]


async def test_nothing_citable_means_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(**_kw: Any) -> Any:
        raise AssertionError("should not be called")

    monkeypatch.setattr(rt.llm, "synth_call", fail)
    assert await rt.compose_thesis("KO", {"Business": SECTIONS["Business"]}) is None


def test_news_headlines_stay_out_of_the_analyst_view() -> None:
    """Unverified third-party headlines aren't evidence for the thesis."""
    sections = {**SECTIONS, "News": [claim("Headline", "Board investigates the CEO")]}
    assert not any(ref.section == "News" for ref in rt._assign_ids(sections).values())
    assert "Board investigates" not in rt.build_thesis_prompt("NVDA", sections)


# ── Cited claims must be the ones the point quotes ───────────────────

QUOTED = {
    "Quality": [
        claim("Gross margin", 0.7467, "fraction"),
        claim("Operating cash flow per share", 0.91, "usd_per_share"),
        claim("Return on invested capital (TTM)", 0.595, "fraction"),
    ],
}


def test_a_cited_claim_the_point_never_quotes_is_dropped() -> None:
    """The live NVDA run cited OCF per share for a gross-margin point."""
    thesis = rt.resolve_draft(
        draft(bull=[p("Gross margin of 74.67% and ROIC of 59.50% stand out.", "Q2", "Q3", "Q1")]),
        rt._assign_ids(QUOTED),
        QUOTED,
    )
    assert thesis is not None
    assert thesis.bull[0].claim_refs == [
        ClaimRef(section="Quality", index=2),
        ClaimRef(section="Quality", index=0),
    ]


def test_rounded_quotes_still_match() -> None:
    thesis = rt.resolve_draft(
        draft(bull=[p("Gross margin near 74.7%.", "Q1")]), rt._assign_ids(QUOTED), QUOTED
    )
    assert thesis is not None and thesis.bull[0].claim_refs == [ClaimRef(section="Quality", index=0)]


def test_a_point_without_numbers_keeps_its_citations() -> None:
    thesis = rt.resolve_draft(
        draft(bull=[p("Margins lead the group from 2025-Q3 onward.", "Q1", "Q2")]), rt._assign_ids(QUOTED), QUOTED
    )
    assert thesis is not None and len(thesis.bull[0].claim_refs) == 2


def test_a_point_quoting_none_of_its_claims_is_dropped() -> None:
    thesis = rt.resolve_draft(
        draft(bull=[p("Gross margin of 74.67%.", "Q1")], bear=[p("Debt rose to $9.65.", "Q2")]),
        rt._assign_ids(QUOTED),
        QUOTED,
    )
    assert thesis is not None
    assert thesis.bear == []


def test_a_middle_history_point_is_not_evidence() -> None:
    """The prompt shows only first, last, low and high; a coincidence with a
    middle quarter must not keep a claim."""
    from app.schemas.research import ClaimHistoryPoint

    ocf = Claim(
        description="Operating cash flow per share",
        value=1.14,
        unit="usd_per_share",
        source=SRC,
        history=[
            ClaimHistoryPoint(period=f"2025-Q{i}", value=v) for i, v in enumerate([0.9, 1.16, 0.5, 1.3, 1.14], start=1)
        ][:4]
        + [ClaimHistoryPoint(period="2026-Q1", value=1.14)],
    )
    sections = {"Quality": [claim("Operating margin change", 0.0116, "percentage_points"), ocf]}
    thesis = rt.resolve_draft(
        draft(bull=[p("Operating margin widened 1.16 pts.", "Q1", "Q2")]), rt._assign_ids(sections), sections
    )
    assert thesis is not None
    assert thesis.bull[0].claim_refs == [ClaimRef(section="Quality", index=0)]


# ── Point titles (2026-11 analyst-view redesign) ─────────────────────
#
# The card was 982 px of 40-word sentences. Each point now carries a
# short title the dashboard lists by default (the sentence opens on
# click). Titles carry no numbers — the figure beside each title is the
# point's first cited claim, rendered from data — so a title can't add
# an unchecked number.


def titled(title: str, text: str, *ids: str) -> ThesisDraftPoint:
    return ThesisDraftPoint(title=title, text=text, claim_ids=list(ids))


def test_a_clean_title_is_kept() -> None:
    thesis = rt.resolve_draft(
        draft(bull=[titled("  Margins still expanding. ", "Margins widened 1.16 pts.", "Q2")]),
        rt._assign_ids(SECTIONS),
    )
    assert thesis is not None
    assert thesis.bull[0].title == "Margins still expanding"


@pytest.mark.parametrize(
    "title",
    [
        "Margins up 1.16 pts",  # a number the rubric never checks
        "Q3 margins widened",  # digits of any kind
        "A title that runs on for far more than the eight words allowed",
        "",
    ],
)
def test_titles_with_numbers_or_too_long_are_dropped(title: str) -> None:
    thesis = rt.resolve_draft(
        draft(bull=[titled(title, "Margins widened 1.16 pts.", "Q2")]),
        rt._assign_ids(SECTIONS),
    )
    assert thesis is not None
    # The point stays; only its title goes (the card falls back to the text).
    assert thesis.bull[0].title is None
    assert thesis.bull[0].text == "Margins widened 1.16 pts."


def test_points_without_a_title_still_resolve() -> None:
    """Lens narratives share the draft point and never ask for titles."""
    thesis = rt.resolve_draft(draft(bull=[p("Margins widened 1.16 pts.", "Q2")]), rt._assign_ids(SECTIONS))
    assert thesis is not None
    assert thesis.bull[0].title is None


def test_prompt_asks_for_titles_and_the_key_claim_first() -> None:
    assert "title" in rt.THESIS_SYSTEM_PROMPT
    assert "no numbers" in rt.THESIS_SYSTEM_PROMPT.lower()
    assert "first" in rt.THESIS_SYSTEM_PROMPT.lower()


def test_cached_points_without_titles_still_parse() -> None:
    from app.schemas.research import Thesis

    cached = {
        "headline": "Old report.",
        "bull": [{"text": "Margins widened.", "claim_refs": [{"section": "Quality", "index": 0}]}],
    }
    thesis = Thesis.model_validate(cached)
    assert thesis.bull[0].title is None


def test_insider_claims_can_be_cited_in_the_analyst_view() -> None:
    assert rt.SECTION_CODES["Insider Activity"] == "I"
    assert len(set(rt.SECTION_CODES.values())) == len(rt.SECTION_CODES)
