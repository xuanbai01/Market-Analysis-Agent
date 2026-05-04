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
    ClaimHistoryPoint,
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


# ── Phase 3.4: history-aware factuality matching ─────────────────────
#
# After Phase 3.2.A–F, ~19 claims carry a ``Claim.history`` of up to 20
# quarterly / monthly points. The LLM weaves trend prose like "EPS rose
# from $1.40 in Q1 to $2.18 in Q4" — both numbers come from the
# claim's history, not its point-in-time snapshot. The rubric must
# accept these without flagging as fabricated.
#
# Implementation strategy: ``_claim_numeric_values`` widens its yield
# to include each claim's ``history[*].value`` so the existing
# ``_matches_claim`` rules (tolerance, sign-flip, fraction-percent,
# scaled units) apply uniformly to historical values.


def _h(period: str, value: float) -> ClaimHistoryPoint:
    """Tiny ClaimHistoryPoint factory — keeps test fixtures readable."""
    return ClaimHistoryPoint(period=period, value=value)


def test_factuality_accepts_number_from_claim_history() -> None:
    """Prose cites a quarter that's in history but not the snapshot.

    ``Reported EPS`` snapshot is the latest quarter (2.18) but Q2's
    1.53 lives in ``history``. A summary that mentions "EPS reached
    $1.53 in Q2" must match — that's the whole point of a sparkline-
    bearing claim.
    """
    section = Section(
        title="Earnings",
        claims=[
            Claim(
                description="Reported EPS (latest quarter)",
                value=2.18,
                source=_src(),
                history=[
                    _h("2024-Q1", 1.40),
                    _h("2024-Q2", 1.53),
                    _h("2024-Q3", 2.05),
                    _h("2024-Q4", 2.18),
                ],
            ),
        ],
        summary="EPS reached 1.53 in Q2 before climbing further.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0, (
        f"prose cites Q2 EPS from history; expected match, got "
        f"unmatched={result.unmatched_numbers}"
    )


def test_factuality_accepts_both_endpoints_of_a_trend() -> None:
    """The canonical "rose from X to Y" pattern. Both numbers are in
    history — neither is the snapshot, neither matches without history
    support.
    """
    section = Section(
        title="Earnings",
        claims=[
            Claim(
                description="Reported EPS (latest quarter)",
                value=2.18,  # snapshot is the latest, neither endpoint
                source=_src(),
                history=[
                    _h("2024-Q1", 1.40),
                    _h("2024-Q2", 1.53),
                    _h("2024-Q3", 1.85),
                    _h("2024-Q4", 2.18),
                ],
            ),
        ],
        summary="EPS rose from 1.40 in Q1 to 2.18 in Q4 — a 56% climb.",
    )
    result = score_factuality(_report([section]))
    # 1.40 from history; 2.18 is the snapshot AND history[-1]; 56 is
    # narrative growth (not in claims) — would fail without further
    # work, but it's outside this test's scope. Tolerate by allowing
    # one unmatched number.
    assert 1.40 not in result.unmatched_numbers
    assert 2.18 not in result.unmatched_numbers


def test_factuality_history_value_displayed_as_percent() -> None:
    """Historical fraction → percent display. ``operating_margin``
    history has 0.32 for Q3; prose says "operating margin reached 32%
    in Q3". The fraction-to-percent equivalence rule (already in
    ``_matches_claim``) must compose with history matching."""
    section = Section(
        title="Quality",
        claims=[
            Claim(
                description="Operating margin",
                value=0.34,  # snapshot
                source=_src(),
                history=[
                    _h("2024-Q1", 0.28),
                    _h("2024-Q2", 0.30),
                    _h("2024-Q3", 0.32),
                    _h("2024-Q4", 0.34),
                ],
            ),
        ],
        summary="Operating margin reached 32% in Q3 before edging higher.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0, (
        f"32% should match 0.32 from history under fraction-percent rule; "
        f"unmatched={result.unmatched_numbers}"
    )


def test_factuality_still_flags_fabrication_with_history_present() -> None:
    """Anti-regression: history widens the value pool but doesn't
    swallow fabricated numbers. Prose cites 4.50 EPS — not in
    snapshot, not in history (history is 1.40–2.18 range). Must
    surface as unmatched."""
    section = Section(
        title="Earnings",
        claims=[
            Claim(
                description="Reported EPS (latest quarter)",
                value=2.18,
                source=_src(),
                history=[
                    _h("2024-Q1", 1.40),
                    _h("2024-Q2", 1.53),
                    _h("2024-Q3", 2.05),
                    _h("2024-Q4", 2.18),
                ],
            ),
        ],
        # 4.50 is invented — never in snapshot OR history
        summary="EPS of 2.18 latest, but management guided to 4.50 next quarter.",
    )
    result = score_factuality(_report([section]))
    assert 4.50 in result.unmatched_numbers
    # 2.18 still matches snapshot; 4.50 is the fabrication.
    assert result.score == 0.5


def test_factuality_pre_3_2_claim_with_empty_history_unchanged() -> None:
    """Backwards-compat: a Claim with empty history (pre-3.2 cached
    report, or non-history-bearing claim like a date label) behaves
    exactly as before — only the snapshot value matches."""
    section = Section(
        title="Valuation",
        claims=[
            Claim(
                description="P/E ratio (trailing 12 months)",
                value=32.5,
                source=_src(),
                history=[],  # empty — pre-3.2 shape
            ),
        ],
        summary="Trades at 32.5 P/E.",
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    assert result.unmatched_numbers == []


def test_factuality_history_matches_across_sections() -> None:
    """The value pool is per-report, not per-section. A summary in
    Section A can cite a historical value from a claim in Section B
    and still match — same as the existing snapshot-matching
    behavior. Documents the choice; we're not narrowing scope."""
    quality = Section(
        title="Quality",
        claims=[
            Claim(
                description="Operating margin",
                value=0.34,
                source=_src(),
                history=[_h("2024-Q1", 0.28), _h("2024-Q2", 0.30)],
            ),
        ],
        summary="",  # no summary — no numbers extracted from this section
    )
    earnings = Section(
        title="Earnings",
        claims=[Claim(description="EPS", value=2.18, source=_src())],
        # Cite Q2's 30% — historical, from the OTHER section's claim.
        summary="Operating leverage reached 30% margin by Q2 alongside 2.18 EPS.",
    )
    result = score_factuality(_report([quality, earnings]))
    assert result.score == 1.0


# ── Phase 4.4.B — card_narrative is policed alongside summary ────────


def test_factuality_scores_numbers_in_card_narrative() -> None:
    """Numbers cited in ``card_narrative`` must trace to a Claim, same
    as numbers in ``summary``. Otherwise the LLM could hallucinate
    freely in the card-strip and dodge the rubric."""
    section = Section(
        title="Earnings",
        claims=[Claim(description="EPS TTM", value=-3.31, source=_src())],
        summary="EPS sits below break-even.",
        card_narrative="Loss is narrowing. EPS TTM at -3.31.",
    )
    result = score_factuality(_report([section]))
    # Both summary and card_narrative numbers must match — score is 1.0
    # because every cited number traces to a claim.
    assert result.score == 1.0
    # The cited number from the card_narrative is in the found list.
    assert 3.31 in result.summary_numbers


def test_factuality_flags_hallucinated_number_in_card_narrative() -> None:
    """A number in card_narrative that doesn't trace to any claim is
    counted as unmatched."""
    section = Section(
        title="Earnings",
        claims=[Claim(description="EPS TTM", value=-3.31, source=_src())],
        summary="EPS sits below break-even.",
        card_narrative="Loss is narrowing. EPS climbed from -8.42 to -3.31.",
    )
    result = score_factuality(_report([section]))
    # -8.42 isn't in any claim and isn't in any history point. The
    # rubric should flag it.
    assert 8.42 in result.unmatched_numbers
    assert result.score < 1.0


def test_factuality_skips_card_narrative_when_none() -> None:
    """Pre-4.4.B reports (or sections where the model declined a
    narrative) have ``card_narrative=None``. The rubric must skip
    cleanly — no numbers extracted, no false positives."""
    section = Section(
        title="Valuation",
        claims=[Claim(description="P/E", value=32.5, source=_src())],
        summary="P/E of 32.5.",
        card_narrative=None,
    )
    result = score_factuality(_report([section]))
    assert result.score == 1.0
    # Only summary's "32.5" was extracted; card_narrative contributed nothing.
    assert result.summary_numbers == [32.5]


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
