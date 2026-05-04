"""
Tests for ``app.services.research_layout_signals.derive_layout_signals``.

Pure-function tests — no DB, no LLM, no provider. Each test constructs
a synthetic ``ResearchReport`` with just enough claims to exercise one
signal at a time, then asserts the derivation flips the expected flag.

Phase 4.5.A. The signals drive Phase 4.5.B's adaptive layout
(distressed-name section reordering + in-card annotations); 4.5.A
ships the derivation + header pills + hero metric swap.
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
from app.services.research_layout_signals import derive_layout_signals


def _src() -> Source:
    return Source(tool="yfinance.fundamentals", fetched_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC))


def _claim(
    description: str,
    value: float | int | None,
    history: list[ClaimHistoryPoint] | None = None,
) -> Claim:
    return Claim(
        description=description,
        value=value,
        source=_src(),
        history=history or [],
    )


def _report(claims: list[Claim], section_title: str = "Quality") -> ResearchReport:
    return ResearchReport(
        symbol="TST",
        generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        sections=[Section(title=section_title, claims=claims, confidence=Confidence.HIGH)],
        overall_confidence=Confidence.HIGH,
    )


# ── is_unprofitable_ttm ──────────────────────────────────────────────


def test_signals_default_healthy_when_no_claims_present() -> None:
    """Empty report → all flags healthy (no data ≠ distressed)."""
    signals = derive_layout_signals(_report([]))
    assert signals.is_unprofitable_ttm is False
    assert signals.beat_rate_below_30pct is False
    assert signals.cash_runway_quarters is None
    assert signals.gross_margin_negative is False
    assert signals.debt_rising_cash_falling is False


def test_is_unprofitable_ttm_when_operating_margin_negative() -> None:
    signals = derive_layout_signals(
        _report([_claim("Operating margin", -0.05)])
    )
    assert signals.is_unprofitable_ttm is True


def test_is_unprofitable_ttm_when_net_profit_margin_negative() -> None:
    signals = derive_layout_signals(
        _report([_claim("Net profit margin", -0.10)])
    )
    assert signals.is_unprofitable_ttm is True


def test_is_unprofitable_ttm_false_when_both_margins_positive() -> None:
    signals = derive_layout_signals(
        _report(
            [
                _claim("Operating margin", 0.32),
                _claim("Net profit margin", 0.25),
            ]
        )
    )
    assert signals.is_unprofitable_ttm is False


def test_is_unprofitable_ttm_false_when_margins_zero() -> None:
    """Strictly negative threshold — break-even is not distressed."""
    signals = derive_layout_signals(
        _report([_claim("Operating margin", 0.0)])
    )
    assert signals.is_unprofitable_ttm is False


# ── beat_rate_below_30pct ───────────────────────────────────────────


def _eps_actual_history(n: int) -> list[ClaimHistoryPoint]:
    return [
        ClaimHistoryPoint(period=f"2024-Q{i % 4 + 1}", value=1.0 + i * 0.01)
        for i in range(n)
    ]


def test_beat_rate_below_30pct_when_count_under_threshold_over_20q() -> None:
    """4 of 20 = 20% → bottom-decile signal fires."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Number of EPS beats over the last 20 quarters (or fewer if"
                    " history is shorter)",
                    4,
                ),
                _claim(
                    "Reported EPS (latest quarter)",
                    1.5,
                    history=_eps_actual_history(20),
                ),
            ],
            section_title="Earnings",
        )
    )
    assert signals.beat_rate_below_30pct is True


def test_beat_rate_below_30pct_false_at_30pct_boundary() -> None:
    """6 of 20 = 30% — strictly less-than threshold so 30% doesn't fire."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Number of EPS beats over the last 20 quarters (or fewer if"
                    " history is shorter)",
                    6,
                ),
                _claim(
                    "Reported EPS (latest quarter)",
                    1.5,
                    history=_eps_actual_history(20),
                ),
            ],
            section_title="Earnings",
        )
    )
    assert signals.beat_rate_below_30pct is False


def test_beat_rate_below_30pct_uses_actual_history_length_as_denominator() -> None:
    """If history has 12Q, the denominator is 12 (not 20).
    4/12 = 33% → not distressed (above the 30% threshold)."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Number of EPS beats over the last 20 quarters (or fewer if"
                    " history is shorter)",
                    4,
                ),
                _claim(
                    "Reported EPS (latest quarter)",
                    1.5,
                    history=_eps_actual_history(12),
                ),
            ],
            section_title="Earnings",
        )
    )
    assert signals.beat_rate_below_30pct is False


def test_beat_rate_below_30pct_false_when_no_eps_history() -> None:
    """Can't compute a rate without a denominator — default to healthy."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Number of EPS beats over the last 20 quarters (or fewer if"
                    " history is shorter)",
                    0,
                ),
            ],
            section_title="Earnings",
        )
    )
    assert signals.beat_rate_below_30pct is False


# ── cash_runway_quarters ────────────────────────────────────────────


def _fcf_history(values: list[float]) -> list[ClaimHistoryPoint]:
    return [
        ClaimHistoryPoint(period=f"2024-Q{i % 4 + 1}", value=v)
        for i, v in enumerate(values)
    ]


def test_cash_runway_computed_from_net_cash_over_fcf_burn() -> None:
    """net cash = 10 - 2 = 8/share; FCF burn TTM = 4 (sum of [-1,-1,-1,-1]).
    runway = 8 / 4 = 2 quarters."""
    signals = derive_layout_signals(
        _report(
            [
                _claim("Cash + short-term investments per share", 10.0),
                _claim("Total debt per share", 2.0),
                _claim(
                    "Free cash flow per share",
                    -1.0,
                    history=_fcf_history([-1.0, -1.0, -1.0, -1.0]),
                ),
            ]
        )
    )
    assert signals.cash_runway_quarters is not None
    assert abs(signals.cash_runway_quarters - 2.0) < 0.01


def test_cash_runway_none_when_fcf_ttm_positive() -> None:
    """Sum of last 4Q FCF >= 0 — runway concept not applicable."""
    signals = derive_layout_signals(
        _report(
            [
                _claim("Cash + short-term investments per share", 10.0),
                _claim("Total debt per share", 2.0),
                _claim(
                    "Free cash flow per share",
                    1.0,
                    history=_fcf_history([0.5, 1.0, 1.5, 2.0]),
                ),
            ]
        )
    )
    assert signals.cash_runway_quarters is None


def test_cash_runway_none_when_fcf_history_too_short() -> None:
    """< 4 quarters of FCF history can't compute a TTM burn."""
    signals = derive_layout_signals(
        _report(
            [
                _claim("Cash + short-term investments per share", 10.0),
                _claim("Total debt per share", 2.0),
                _claim(
                    "Free cash flow per share",
                    -1.0,
                    history=_fcf_history([-1.0, -1.0, -1.0]),
                ),
            ]
        )
    )
    assert signals.cash_runway_quarters is None


def test_cash_runway_none_when_cash_claim_missing() -> None:
    signals = derive_layout_signals(
        _report(
            [
                _claim("Total debt per share", 2.0),
                _claim(
                    "Free cash flow per share",
                    -1.0,
                    history=_fcf_history([-1.0, -1.0, -1.0, -1.0]),
                ),
            ]
        )
    )
    assert signals.cash_runway_quarters is None


def test_cash_runway_zero_when_net_cash_already_negative() -> None:
    """If cash - debt < 0 AND burning FCF, the company is already in
    deficit — clamp runway to 0 to convey 'out of runway'."""
    signals = derive_layout_signals(
        _report(
            [
                _claim("Cash + short-term investments per share", 2.0),
                _claim("Total debt per share", 5.0),
                _claim(
                    "Free cash flow per share",
                    -1.0,
                    history=_fcf_history([-1.0, -1.0, -1.0, -1.0]),
                ),
            ]
        )
    )
    assert signals.cash_runway_quarters == 0.0


# ── gross_margin_negative ───────────────────────────────────────────


def test_gross_margin_negative_when_value_below_zero() -> None:
    signals = derive_layout_signals(
        _report([_claim("Gross margin", -0.18)])
    )
    assert signals.gross_margin_negative is True


def test_gross_margin_negative_false_when_positive() -> None:
    signals = derive_layout_signals(
        _report([_claim("Gross margin", 0.74)])
    )
    assert signals.gross_margin_negative is False


# ── debt_rising_cash_falling ────────────────────────────────────────


def _hist(values: list[float]) -> list[ClaimHistoryPoint]:
    return [
        ClaimHistoryPoint(period=f"2024-Q{i % 4 + 1}", value=v)
        for i, v in enumerate(values)
    ]


def test_debt_rising_cash_falling_when_slopes_match_pattern() -> None:
    """debt slope > 0 AND cash slope < 0 → distressed pattern."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Cash + short-term investments per share",
                    2.0,
                    history=_hist([10.0, 8.0, 5.0, 2.0]),
                ),
                _claim(
                    "Total debt per share",
                    9.0,
                    history=_hist([3.0, 5.0, 7.0, 9.0]),
                ),
            ]
        )
    )
    assert signals.debt_rising_cash_falling is True


def test_debt_rising_cash_falling_false_when_only_one_direction() -> None:
    """Debt rising but cash flat — no signal."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Cash + short-term investments per share",
                    10.0,
                    history=_hist([10.0, 10.0, 10.0, 10.0]),
                ),
                _claim(
                    "Total debt per share",
                    9.0,
                    history=_hist([3.0, 5.0, 7.0, 9.0]),
                ),
            ]
        )
    )
    assert signals.debt_rising_cash_falling is False


def test_debt_rising_cash_falling_false_when_history_too_short() -> None:
    """Need >= 3 points to compute a meaningful slope."""
    signals = derive_layout_signals(
        _report(
            [
                _claim(
                    "Cash + short-term investments per share",
                    2.0,
                    history=_hist([10.0, 2.0]),
                ),
                _claim(
                    "Total debt per share",
                    9.0,
                    history=_hist([3.0, 9.0]),
                ),
            ]
        )
    )
    assert signals.debt_rising_cash_falling is False


# ── compound: realistic distressed report ───────────────────────────


def test_realistic_distressed_report_lights_multiple_signals() -> None:
    """A Rivian-shaped report fires several signals at once."""
    fcf_hist = _fcf_history([-2.0, -2.5, -2.0, -1.5])  # TTM = -8
    cash_hist = _hist([5.0, 4.0, 3.5, 3.0])
    debt_hist = _hist([2.0, 3.0, 4.0, 5.0])
    signals = derive_layout_signals(
        _report(
            [
                _claim("Operating margin", -0.41),
                _claim("Net profit margin", -0.55),
                _claim("Gross margin", -0.18),
                _claim(
                    "Number of EPS beats over the last 20 quarters (or fewer if"
                    " history is shorter)",
                    4,
                ),
                _claim(
                    "Reported EPS (latest quarter)",
                    -3.31,
                    history=_eps_actual_history(20),
                ),
                _claim("Cash + short-term investments per share", 3.0, history=cash_hist),
                _claim("Total debt per share", 5.0, history=debt_hist),
                _claim("Free cash flow per share", -1.5, history=fcf_hist),
            ]
        )
    )
    assert signals.is_unprofitable_ttm is True
    assert signals.beat_rate_below_30pct is True
    assert signals.cash_runway_quarters == 0.0  # net cash -2/sh, already in deficit
    assert signals.gross_margin_negative is True
    assert signals.debt_rising_cash_falling is True
