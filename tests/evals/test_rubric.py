"""
Unit tests for the rubric framework. These run on every PR — they prove
the rubric correctly grades known-good and known-bad reports without
needing an LLM. The agent-against-golden tests live in test_golden.py
and are skipped unless ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.research import (
    Claim,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from tests.evals.rubric import (
    grade,
    score_factuality,
    score_structure,
)


def _src(tool: str = "yfinance.history") -> Source:
    return Source(tool=tool, fetched_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC))


def _report(sections: list[Section]) -> ResearchReport:
    return ResearchReport(
        symbol="NVDA",
        generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        sections=sections,
        overall_confidence=Confidence.HIGH,
    )


# ── Structure scoring ────────────────────────────────────────────────


def test_structure_score_valid_report() -> None:
    valid = _report([Section(title="Overview")])
    result = score_structure(valid.model_dump(mode="json"))
    assert result.valid
    assert result.errors == []


def test_structure_score_rejects_missing_required_field() -> None:
    bad = {"sections": [], "generated_at": "2026-04-25T12:00:00Z"}  # no symbol
    result = score_structure(bad)
    assert not result.valid
    assert any("symbol" in e.lower() for e in result.errors)


def test_structure_score_rejects_unknown_confidence() -> None:
    bad = {
        "symbol": "NVDA",
        "generated_at": "2026-04-25T12:00:00Z",
        "overall_confidence": "vibes",
        "sections": [],
    }
    result = score_structure(bad)
    assert not result.valid


# ── Factuality scoring ───────────────────────────────────────────────


def test_factuality_perfect_when_every_summary_number_matches_a_claim() -> None:
    section = Section(
        title="Valuation",
        claims=[
            Claim(description="P/E", value=32.5, source=_src()),
            Claim(description="P/S", value=18.2, source=_src()),
        ],
        summary="Trades at 32.5 P/E and 18.2 P/S — premium to sector.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    assert result.unmatched_numbers == []


def test_factuality_flags_hallucinated_number_in_summary() -> None:
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=32.5, source=_src())],
        # 18.2 is invented — never appears in claims
        summary="P/E of 32.5 and P/S of 18.2 indicate a premium.",
    )
    result = score_factuality(_report([section]))
    assert 18.2 in result.unmatched_numbers
    assert result.score == 0.5  # 1 of 2 numbers matched


def test_factuality_ignores_4_digit_years() -> None:
    section = Section(
        title="Earnings",
        claims=[Claim(description="EPS", value=0.86, source=_src())],
        # "2026" should not be treated as an unmatched fact.
        summary="Q3 2026 EPS came in at 0.86, beating consensus.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    assert 2026.0 not in result.unmatched_numbers


def test_factuality_pure_prose_section_is_vacuously_factual() -> None:
    section = Section(
        title="Thesis",
        claims=[],
        summary="Strong moat in CUDA tooling; switching costs remain high.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    assert result.summary_numbers == []


def test_factuality_respects_tolerance_for_floats() -> None:
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=32.50, source=_src())],
        # Summary rounds to 32.51 — within default tolerance of 0.01.
        summary="Trades at 32.51 P/E.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_handles_thousands_separators() -> None:
    section = Section(
        title="Capital allocation",
        claims=[Claim(description="Buyback $", value=12500.0, source=_src())],
        summary="Repurchased 12,500 worth of shares this quarter.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_empty_report_is_vacuously_factual() -> None:
    result = score_factuality(_report([]))
    assert result.score == 1.0


# ── Finance-display equivalence rules ────────────────────────────────
#
# Real-LLM prose surfaces the same claim under standard finance display
# conventions: 0.47325 → "47.33%", 3,972,863,098,880 → "$3.97 trillion",
# -714 → "a reduction of 714". The rubric must match these to avoid
# false-positive flagging the LLM correctly behaved.


def test_factuality_accepts_fraction_displayed_as_percentage() -> None:
    """0.47325 fraction in claim → '47.33%' in prose. Match."""
    section = Section(
        title="Quality",
        claims=[Claim(description="Gross margin", value=0.47325, source=_src())],
        summary="Gross margin of 47.33% sits well above sector average.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    assert 47.33 not in result.unmatched_numbers


def test_factuality_accepts_value_above_one_displayed_as_pct() -> None:
    """ROE 1.5202 → '152.02%' in prose. (Apple's real number.)"""
    section = Section(
        title="Quality",
        claims=[Claim(description="ROE", value=1.5202099, source=_src())],
        summary="Return on equity is remarkably high at 152.02%.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_accepts_trillion_scaling() -> None:
    """3,972,863,098,880 raw → '$3.97 trillion' in prose."""
    section = Section(
        title="Capital Allocation",
        claims=[
            Claim(
                description="Market capitalization",
                value=3_972_863_098_880,
                source=_src(),
            ),
        ],
        summary="With a market capitalization of approximately $3.97 trillion.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_accepts_million_scaling() -> None:
    """134,422,787 raw → '134.4 million' in prose."""
    section = Section(
        title="Capital Allocation",
        claims=[
            Claim(description="Shares short", value=134_422_787, source=_src()),
        ],
        summary="Short interest of roughly 134.4 million shares.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_accepts_sign_flip_in_prose() -> None:
    """Claim is -714 (signed delta); prose says 'reduction of 714'."""
    section = Section(
        title="Risk Factors",
        claims=[
            Claim(
                description="Item 1A char delta vs prior 10-K",
                value=-714,
                source=_src(),
            ),
        ],
        summary="Net character reduction of 714 in the risk-factor section.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0


def test_factuality_strips_iso_dates_from_prose() -> None:
    """A summary that references a date like '2026-01-29' must not have
    the components (1, 29) flagged as unmatched numbers."""
    section = Section(
        title="Earnings",
        claims=[Claim(description="EPS", value=2.84, source=_src())],
        summary="The most recent report (2026-01-29) showed EPS of 2.84.",
    )
    result = score_factuality(_report([section]))
    # 2.84 should be the only extracted number; 2026, 01, 29 all stripped.
    assert result.summary_numbers == [2.84]
    assert result.score == 1.0


def test_factuality_still_flags_genuine_fabrication_under_new_rules() -> None:
    """The expanded matchers must NOT accept arbitrary numbers — a
    fabricated 5-digit P/E should still surface as unmatched."""
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=32.5, source=_src())],
        # 18.2 isn't a fraction of any claim, isn't a scaling, isn't a sign-flip.
        summary="P/E of 32.5 and P/S of 18.2.",
    )
    result = score_factuality(_report([section]))
    assert 18.2 in result.unmatched_numbers
    assert result.score == 0.5


def test_factuality_scaling_only_kicks_in_for_large_claim_values() -> None:
    """The trillion/million matcher must not falsely match small claim
    values. Claim of 3.5 should NOT be considered to match prose '3.5e9'
    or anything like that — only claim values >= 1e6 trigger the
    scaling rules."""
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=3.5, source=_src())],
        # Prose has a number that would be 3.5 * 1e6 — must not match.
        summary="Hypothetical: 3500000 was reported.",
    )
    result = score_factuality(_report([section]))
    assert 3500000.0 in result.unmatched_numbers


# ── Combined grade ───────────────────────────────────────────────────


def test_grade_bundles_all_three_scorers() -> None:
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=32.5, source=_src())],
        summary="P/E of 32.5.",
    )
    result = grade(_report([section]), elapsed_ms=1234.5)

    assert result.structure.valid
    assert result.factuality.score == 1.0
    assert result.latency.elapsed_ms == 1234.5
