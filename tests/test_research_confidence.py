"""
Tests for ``app.services.research_confidence``.

Confidence is set programmatically — never by the LLM — based on two
signals: how complete the data is (non-null density across the
section's claims) and how fresh it is (max age across claims). The
rules are deliberately simple so a section's confidence is fully
explainable from its inputs.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.research import Claim, Confidence, Source
from app.services.research_confidence import score_section


def _claim(value: object, *, age_days: int = 1) -> Claim:
    """Build a Claim with the value + a source dated ``age_days`` ago."""
    return Claim(
        description="test claim",
        value=value,  # type: ignore[arg-type]
        source=Source(
            tool="test.tool",
            fetched_at=datetime.now(UTC) - timedelta(days=age_days),
        ),
    )


# ── Empty / sparse cases ──────────────────────────────────────────────


def test_empty_claims_is_low_confidence() -> None:
    """A section with no claims at all is unambiguously LOW."""
    assert score_section([]) == Confidence.LOW


def test_all_none_values_is_low_confidence() -> None:
    """All claims present but all values None → LOW."""
    claims = [_claim(None), _claim(None), _claim(None)]
    assert score_section(claims) == Confidence.LOW


def test_below_50pct_non_null_is_low_confidence() -> None:
    """Less than half the claims have data → LOW."""
    claims = [_claim(1.0), _claim(None), _claim(None), _claim(None)]
    # 1/4 = 25% non-null → LOW
    assert score_section(claims) == Confidence.LOW


# ── Medium band ───────────────────────────────────────────────────────


def test_50_to_80pct_non_null_is_medium_confidence() -> None:
    """50–80% non-null with fresh data → MEDIUM."""
    # 3/5 = 60% non-null
    claims = [
        _claim(1.0),
        _claim(2.0),
        _claim(3.0),
        _claim(None),
        _claim(None),
    ]
    assert score_section(claims) == Confidence.MEDIUM


def test_stale_data_capped_at_medium_even_if_fully_populated() -> None:
    """All claims present, all values non-null, but data > 30 days old → MEDIUM.

    Freshness is a separate floor: a section with verifiable but stale
    data should not present as HIGH confidence.
    """
    claims = [_claim(1.0, age_days=45), _claim(2.0, age_days=45)]
    assert score_section(claims) == Confidence.MEDIUM


def test_freshness_uses_oldest_claim_age() -> None:
    """One stale claim drags the whole section into MEDIUM.

    The motivating case: a section composed from two tools where one
    pulled fresh data and the other has a 90-day-old cached entry.
    The section is only as fresh as its oldest claim.
    """
    claims = [_claim(1.0, age_days=1), _claim(2.0, age_days=60)]
    assert score_section(claims) == Confidence.MEDIUM


# ── High band ─────────────────────────────────────────────────────────


def test_high_when_fresh_and_dense() -> None:
    """≥80% non-null AND all claims within 30 days → HIGH."""
    claims = [_claim(1.0), _claim(2.0), _claim(3.0), _claim(4.0), _claim(5.0)]
    assert score_section(claims) == Confidence.HIGH


def test_exactly_80pct_non_null_is_high_when_fresh() -> None:
    """Threshold inclusive at the high end: 80% non-null + fresh → HIGH."""
    # 4/5 = 80%
    claims = [_claim(1.0), _claim(2.0), _claim(3.0), _claim(4.0), _claim(None)]
    assert score_section(claims) == Confidence.HIGH


# ── Boundary cases ────────────────────────────────────────────────────


def test_exactly_50pct_non_null_is_medium() -> None:
    """Lower boundary of the medium band: 50% non-null is MEDIUM, not LOW."""
    claims = [_claim(1.0), _claim(2.0), _claim(None), _claim(None)]
    assert score_section(claims) == Confidence.MEDIUM


def test_just_below_80pct_non_null_is_medium() -> None:
    """Upper boundary of medium: 75% non-null lands in MEDIUM."""
    # 3/4 = 75%
    claims = [_claim(1.0), _claim(2.0), _claim(3.0), _claim(None)]
    assert score_section(claims) == Confidence.MEDIUM


def test_just_above_30_days_old_is_medium_not_high() -> None:
    """Freshness boundary: 31 days old → not HIGH."""
    claims = [_claim(1.0, age_days=31), _claim(2.0, age_days=31)]
    assert score_section(claims) == Confidence.MEDIUM


def test_exactly_30_days_old_still_high_when_dense() -> None:
    """30 days old is the inclusive cutoff for HIGH."""
    claims = [_claim(1.0, age_days=30), _claim(2.0, age_days=30)]
    assert score_section(claims) == Confidence.HIGH


# ── Value-shape coverage ──────────────────────────────────────────────
#
# ClaimValue is float | int | str | bool | None. Every non-None type
# should count as "has data" — including bool False, which is a real
# signal (e.g., "missed earnings = False" is a valid claim).


def test_zero_int_counts_as_non_null() -> None:
    """0 is a real value, not missing data."""
    claims = [_claim(0), _claim(0), _claim(0), _claim(0), _claim(0)]
    assert score_section(claims) == Confidence.HIGH


def test_false_bool_counts_as_non_null() -> None:
    """``False`` is a real signal (beat=False, dividend_paying=False, etc.)."""
    claims = [_claim(False), _claim(False), _claim(False)]
    assert score_section(claims) == Confidence.HIGH


def test_empty_string_counts_as_non_null() -> None:
    """An empty string is a real (if degenerate) value, not None."""
    claims = [_claim(""), _claim(""), _claim("")]
    assert score_section(claims) == Confidence.HIGH
