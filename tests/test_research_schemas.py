"""Schema invariants for the citation-enforcing research report."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    Claim,
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


def test_section_summary_has_length_cap() -> None:
    with pytest.raises(ValidationError):
        Section(title="X", summary="x" * 5000)


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
