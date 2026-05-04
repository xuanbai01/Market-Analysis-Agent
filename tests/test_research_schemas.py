"""Schema invariants for the citation-enforcing research report."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    Claim,
    ClaimHistoryPoint,
    Confidence,
    ResearchReport,
    Section,
    Source,
)


def _src(tool: str = "yfinance.history", offset_minutes: int = 0) -> Source:
    return Source(
        tool=tool,
        fetched_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
        + timedelta(minutes=offset_minutes),
    )


# ── Source ───────────────────────────────────────────────────────────


def test_source_is_frozen() -> None:
    """Source should be immutable so a Claim can't have its provenance rewritten."""
    s = _src()
    with pytest.raises(ValidationError):
        s.tool = "fabricated"  # type: ignore[misc]


def test_source_rejects_empty_tool() -> None:
    with pytest.raises(ValidationError):
        Source(tool="", fetched_at=datetime.now(UTC))


# ── Claim ────────────────────────────────────────────────────────────


def test_claim_accepts_numeric_values() -> None:
    Claim(description="P/E", value=32.5, source=_src())
    Claim(description="Volume", value=1_000_000, source=_src())


def test_claim_accepts_string_values() -> None:
    Claim(description="Sector", value="Semiconductors", source=_src())


def test_claim_accepts_null_for_unavailable_data() -> None:
    """The agent must be able to report 'we tried, no value' explicitly."""
    Claim(description="EPS estimate", value=None, source=_src())


def test_claim_accepts_bool_values() -> None:
    """Beat/miss flags are real claims."""
    Claim(description="Beat consensus", value=True, source=_src())


def test_claim_rejects_empty_description() -> None:
    with pytest.raises(ValidationError):
        Claim(description="", value=1.0, source=_src())


def test_claim_carries_source_provenance() -> None:
    c = Claim(description="P/E", value=32.5, source=_src(tool="yfinance.info"))
    assert c.source.tool == "yfinance.info"
    assert c.source.fetched_at.tzinfo is not None


# ── Section ──────────────────────────────────────────────────────────


def test_section_last_updated_is_max_fetched_at() -> None:
    s = Section(
        title="Valuation",
        claims=[
            Claim(description="P/E", value=32.5, source=_src(offset_minutes=0)),
            Claim(description="P/S", value=18.2, source=_src(offset_minutes=30)),
        ],
    )
    assert s.last_updated is not None
    expected = datetime(2026, 4, 25, 12, 30, tzinfo=UTC)
    assert s.last_updated == expected


def test_section_with_no_claims_has_no_last_updated() -> None:
    s = Section(title="Thesis")
    assert s.last_updated is None


def test_section_default_confidence_is_low() -> None:
    """Default to LOW so a section that forgot to set confidence isn't oversold."""
    s = Section(title="Risks")
    assert s.confidence == Confidence.LOW


# ── Claim.unit (Phase 4.3.X) ─────────────────────────────────────────
#
# Unit hint drives frontend formatting so a fraction-form ROE > 1
# doesn't render as a plain number, a per-share dollar amount < $1
# doesn't render as a percent, and a percent-form dividend yield
# doesn't get x100'd. Default ``None`` for backwards-compat with
# pre-4.3.X cached rows; the frontend falls back to the existing
# heuristic when the field is missing.


def test_claim_unit_defaults_to_none() -> None:
    """Backwards-compat: pre-4.3.X cached rows have no unit field."""
    c = Claim(description="P/E", value=32.5, source=_src())
    assert c.unit is None


def test_claim_accepts_known_unit_literals() -> None:
    """The literal-typed unit field accepts the documented categories."""
    for unit in (
        "fraction",
        "percent",
        "usd",
        "usd_per_share",
        "ratio",
        "count",
        "date",
        "string",
        "shares",
        "basis_points",
    ):
        c = Claim(
            description=f"X with unit {unit}",
            value=1.0,
            source=_src(),
            unit=unit,  # type: ignore[arg-type]
        )
        assert c.unit == unit


def test_claim_rejects_unknown_unit() -> None:
    """Free-form strings on the literal-typed field should fail validation."""
    with pytest.raises(ValidationError):
        Claim(
            description="X",
            value=1.0,
            source=_src(),
            unit="bushels-per-fortnight",  # type: ignore[arg-type]
        )


def test_claim_unit_round_trips_through_jsonb() -> None:
    """Cache layer serializes via model_dump(mode='json'); the unit
    must survive that round trip so the dashboard sees it on cache hit."""
    c = Claim(
        description="ROE",
        value=1.41,
        source=_src(),
        unit="fraction",
    )
    blob = c.model_dump(mode="json")
    assert blob["unit"] == "fraction"
    re_parsed = Claim.model_validate(blob)
    assert re_parsed.unit == "fraction"


def test_section_summary_has_length_cap() -> None:
    with pytest.raises(ValidationError):
        Section(title="X", summary="x" * 5000)


# ── Section.card_narrative (Phase 4.4.B) ─────────────────────────────
#
# Every dedicated dashboard card (Quality, Earnings, PerShareGrowth,
# RiskDiff, Macro, …) wants a 1-2 sentence punchy framing string —
# distinct from ``summary`` (the broad 2-4 sentence narrative). Default
# ``None`` so pre-4.4.B cached JSONB rows round-trip unchanged and the
# field is simply absent rather than ``""`` (the rendering layer treats
# null and empty identically — the difference matters for the rubric).


def test_section_card_narrative_defaults_to_none() -> None:
    """Backwards-compat: pre-4.4.B cached rows have no card_narrative field."""
    s = Section(title="Quality")
    assert s.card_narrative is None


def test_section_card_narrative_accepts_short_prose() -> None:
    s = Section(
        title="Quality",
        card_narrative="Trajectory positive, level negative. Gross margin up 226 pts in 5Y.",
    )
    assert s.card_narrative is not None
    assert "Trajectory positive" in s.card_narrative


def test_section_card_narrative_round_trips_through_jsonb() -> None:
    """Cache layer serializes via model_dump(mode='json'); the
    card_narrative must survive that round trip so the dashboard sees
    it on cache hit."""
    s = Section(
        title="Earnings",
        summary="Q1 beat consensus.",
        card_narrative="Loss is narrowing. EPS -3.82 -> -0.78 over 20Q.",
    )
    blob = s.model_dump(mode="json")
    assert blob["card_narrative"] == "Loss is narrowing. EPS -3.82 -> -0.78 over 20Q."
    re_parsed = Section.model_validate(blob)
    assert re_parsed.card_narrative == s.card_narrative
    # ``summary`` and ``card_narrative`` are independent surfaces;
    # adding one must not silently overwrite the other.
    assert re_parsed.summary == "Q1 beat consensus."


def test_section_card_narrative_has_length_cap() -> None:
    """Same 4000-char cap as ``summary`` — punchy is encouraged but the
    schema cap matches summary's so we don't have to remember different
    limits."""
    with pytest.raises(ValidationError):
        Section(title="X", card_narrative="x" * 5000)


def test_section_pre_4_4_b_cached_payload_still_parses() -> None:
    """A JSONB row written before this PR has no ``card_narrative``
    key. It must still parse; ``card_narrative`` defaults to None."""
    legacy_payload = {
        "title": "Valuation",
        "claims": [],
        "summary": "Trades at 28.5x trailing earnings.",
        "confidence": "high",
    }
    section = Section.model_validate(legacy_payload)
    assert section.card_narrative is None
    assert section.summary == "Trades at 28.5x trailing earnings."


# ── ResearchReport ───────────────────────────────────────────────────


def test_report_aggregates_all_claims() -> None:
    report = ResearchReport(
        symbol="NVDA",
        generated_at=datetime.now(UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[Claim(description="P/E", value=32.5, source=_src())],
            ),
            Section(
                title="Quality",
                claims=[
                    Claim(description="ROE", value=120.0, source=_src()),
                    Claim(description="ROIC", value=85.0, source=_src()),
                ],
            ),
        ],
    )
    assert len(report.all_claims) == 3


def test_report_serializes_to_json_and_round_trips() -> None:
    """Pydantic round-trip — the structured-output contract depends on this."""
    report = ResearchReport(
        symbol="NVDA",
        generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[Claim(description="P/E", value=32.5, source=_src())],
                summary="P/E of 32.5",
                confidence=Confidence.HIGH,
            )
        ],
        overall_confidence=Confidence.HIGH,
    )
    blob = report.model_dump_json()
    restored = ResearchReport.model_validate_json(blob)
    assert restored == report


def test_report_rejects_unknown_confidence_string() -> None:
    with pytest.raises(ValidationError):
        ResearchReport(
            symbol="NVDA",
            generated_at=datetime.now(UTC),
            overall_confidence="vibes",  # type: ignore[arg-type]
        )


def test_report_rejects_empty_symbol() -> None:
    with pytest.raises(ValidationError):
        ResearchReport(
            symbol="",
            generated_at=datetime.now(UTC),
        )


# ── ClaimHistoryPoint + Claim.history (Phase 3.1) ────────────────────


def test_claim_history_point_constructs() -> None:
    """The atomic time-series unit: period label + numeric value."""
    p = ClaimHistoryPoint(period="2024-Q4", value=2.18)
    assert p.period == "2024-Q4"
    assert p.value == 2.18


def test_claim_history_point_is_frozen() -> None:
    """History points are value objects — mutating one mid-flight is a bug."""
    p = ClaimHistoryPoint(period="2024-Q4", value=2.18)
    with pytest.raises(ValidationError):
        p.value = 99.0  # type: ignore[misc]


def test_claim_history_point_rejects_empty_period() -> None:
    with pytest.raises(ValidationError):
        ClaimHistoryPoint(period="", value=1.0)


def test_claim_history_point_value_must_be_numeric() -> None:
    """Strings/booleans/null don't sparkline; only floats are charted."""
    with pytest.raises(ValidationError):
        ClaimHistoryPoint(period="2024-Q4", value="2.18")  # type: ignore[arg-type]


def test_claim_history_defaults_to_empty_list() -> None:
    """Existing claims (no history field) construct unchanged — backwards-compat."""
    c = Claim(description="P/E", value=28.5, source=_src())
    assert c.history == []


def test_claim_accepts_populated_history() -> None:
    c = Claim(
        description="EPS",
        value=2.18,
        source=_src(),
        history=[
            ClaimHistoryPoint(period="2023-Q4", value=1.46),
            ClaimHistoryPoint(period="2024-Q1", value=1.71),
            ClaimHistoryPoint(period="2024-Q2", value=1.89),
            ClaimHistoryPoint(period="2024-Q3", value=2.05),
            ClaimHistoryPoint(period="2024-Q4", value=2.18),
        ],
    )
    assert len(c.history) == 5
    assert c.history[0].period == "2023-Q4"
    assert c.history[-1].value == 2.18


def test_claim_with_history_round_trips_through_json() -> None:
    """The cache layer round-trips via model_dump → JSONB → model_validate.
    A history-bearing Claim must survive that path unchanged."""
    original = Claim(
        description="EPS",
        value=2.18,
        source=_src(),
        history=[
            ClaimHistoryPoint(period="2024-Q3", value=2.05),
            ClaimHistoryPoint(period="2024-Q4", value=2.18),
        ],
    )
    blob = original.model_dump_json()
    restored = Claim.model_validate_json(blob)
    assert restored == original
    assert len(restored.history) == 2


def test_claim_without_history_serializes_with_empty_list() -> None:
    """``default_factory=list`` means the field is always present in
    serialization, never missing — keeps the JSONB shape stable.
    """
    c = Claim(description="P/E", value=28.5, source=_src())
    blob = c.model_dump()
    assert blob["history"] == []


def test_existing_cache_payload_without_history_still_parses() -> None:
    """Backwards-compat: a cached row written before Phase 3.1 has no
    ``history`` key. Validation must accept it and fill in []."""
    legacy_payload = {
        "description": "P/E",
        "value": 28.5,
        "source": {
            "tool": "yfinance.info",
            "fetched_at": "2026-04-25T12:00:00+00:00",
        },
        # NOTE: no "history" key — pre-Phase-3.1 shape
    }
    c = Claim.model_validate(legacy_payload)
    assert c.history == []


def test_full_report_with_history_round_trips() -> None:
    """The whole-report round-trip the cache layer relies on."""
    report = ResearchReport(
        symbol="NVDA",
        generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        sections=[
            Section(
                title="Earnings",
                claims=[
                    Claim(
                        description="EPS",
                        value=2.18,
                        source=_src(),
                        history=[
                            ClaimHistoryPoint(period="2024-Q3", value=2.05),
                            ClaimHistoryPoint(period="2024-Q4", value=2.18),
                        ],
                    ),
                ],
                summary="EPS rose from 2.05 to 2.18 quarter over quarter.",
                confidence=Confidence.HIGH,
            ),
        ],
        overall_confidence=Confidence.HIGH,
    )
    blob = report.model_dump_json()
    restored = ResearchReport.model_validate_json(blob)
    assert restored == report
    assert restored.sections[0].claims[0].history[0].period == "2024-Q3"


def test_json_schema_for_llm_tool_use() -> None:
    """
    The LLM client passes ``schema.model_json_schema()`` as the
    ``input_schema`` of a forced tool. If the schema can't be generated
    or is missing required fields, the agent path is broken — this is
    a smoke test that schema generation works for nested models.
    """
    schema = ResearchReport.model_json_schema()
    assert "$defs" in schema
    assert "Section" in schema["$defs"]
    assert "Claim" in schema["$defs"]
    assert "Source" in schema["$defs"]
    # Pydantic emits required as an array on the object schema
    assert "symbol" in schema["required"]
    assert "generated_at" in schema["required"]
