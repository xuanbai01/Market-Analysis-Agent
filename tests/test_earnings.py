"""
Tests for fetch_earnings (Phase 3.2.E shape).

Phase 3.2.E refactor: the original q1/q2/q3/q4 prefix scheme (16 per-
quarter keys = 4 metrics × 4 quarters) collapsed into 3 history-
bearing claims (``eps_actual`` / ``eps_estimate`` / ``eps_surprise_pct``)
each carrying ~20 quarters in ``Claim.history``. CLAIM_KEYS shrunk
from 21 to 9; the agent prompt is dramatically simpler and the
frontend can render an EPS sparkline directly off the history.

What we're pinning:

1. New stable shape — 9 keys total: 1 latest report-date label,
   3 history-bearing per-quarter metrics, 3 forward keys, 2 derived
   summary keys.
2. History attachment — eps_actual / eps_estimate / eps_surprise_pct
   carry up to 20 ClaimHistoryPoint entries each, ordered oldest →
   newest.
3. Snapshot consistency — each history-bearing claim's ``value`` is
   the most-recent quarter's number (== history[-1].value).
4. Window math — ``last_20q.beat_count`` counts strictly-positive
   surprises across all available history (capped at 20); avg likewise.
5. Provider tuple shape — ``EarningsProvider`` returns
   ``(values, history_map)`` matching the 3.2.A pattern.
6. yfinance provider details — uses ``get_earnings_dates(limit=24)``
   for ~6 years of depth; surprise fallback when yfinance's column is
   missing; calendar + earnings_estimate parsing unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.schemas.research import Claim, ClaimHistoryPoint
from app.services.earnings import (
    CLAIM_KEYS,
    HISTORY_KEYS,
    PROVIDERS,
    _fetch_yfinance_earnings,
    fetch_earnings,
)

# ── Fixtures ─────────────────────────────────────────────────────────


def _fake_raw(**overrides: Any) -> dict[str, Any]:
    """Fully-populated raw provider values dict — override per test."""
    base: dict[str, Any] = {
        "latest_report_date": "2024-10-31",
        "eps_actual": 1.64,
        "eps_estimate": 1.60,
        "eps_surprise_pct": 2.5,
        "next.report_date": "2025-02-01",
        "next.eps_estimate": 2.35,
        "next.revenue_estimate": 124_000_000_000,
        # last_20q.* are computed at the entry-point level from history;
        # the provider doesn't need to populate them. Tests inject
        # specific history maps when they need to verify the math.
    }
    # Sanity: fixture must list every key the provider should populate
    # (i.e. all of CLAIM_KEYS minus the computed last_20q.* metrics).
    advertised = {k for k in CLAIM_KEYS if not k.startswith("last_20q.")}
    assert set(base) == advertised, "fixture out of sync with CLAIM_KEYS"
    base.update(overrides)
    return base


def _fake_history(
    eps_actuals: list[float] | None = None,
    eps_estimates: list[float] | None = None,
    surprises: list[float] | None = None,
    periods: list[str] | None = None,
) -> dict[str, list[ClaimHistoryPoint]]:
    """Build a history map with parallel lists. Defaults mirror _fake_raw."""
    if periods is None:
        periods = ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]
    if eps_actuals is None:
        eps_actuals = [1.40, 1.53, 2.18, 1.64]
    if eps_estimates is None:
        eps_estimates = [1.35, 1.50, 2.10, 1.60]
    if surprises is None:
        surprises = [3.7, 2.0, 3.8, 2.5]
    return {
        "eps_actual": [
            ClaimHistoryPoint(period=p, value=v)
            for p, v in zip(periods, eps_actuals, strict=True)
        ],
        "eps_estimate": [
            ClaimHistoryPoint(period=p, value=v)
            for p, v in zip(periods, eps_estimates, strict=True)
        ],
        "eps_surprise_pct": [
            ClaimHistoryPoint(period=p, value=v)
            for p, v in zip(periods, surprises, strict=True)
        ],
    }


def _fake_provider(
    values: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
) -> Any:
    """Build a sync provider matching the new (values, history_map) tuple shape."""
    def _provider(_sym: str) -> tuple[dict[str, Any], dict[str, Any]]:
        return (values if values is not None else _fake_raw()), (
            history if history is not None else _fake_history()
        )

    return _provider


# ── Async entry point: shape ─────────────────────────────────────────


async def test_returns_claim_for_each_known_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3.2.E shape: 9 keys total."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_earnings("AAPL", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for claim in result.values():
        assert isinstance(claim, Claim)


async def test_no_q_prefix_keys_in_new_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anti-regression: the q1/q2/q3/q4 prefix scheme is gone after
    Phase 3.2.E. If any old key name leaked back in, this fails."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_earnings("AAPL", provider="fake")

    legacy_keys = {f"q{i}.{m}" for i in (1, 2, 3, 4)
                   for m in ("report_date", "eps_actual", "eps_estimate",
                             "eps_surprise_pct")}
    assert legacy_keys.isdisjoint(result.keys())


async def test_history_keys_carry_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 3 history-bearing claims must have populated histories."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_earnings("AAPL", provider="fake")

    for key in HISTORY_KEYS:
        claim = result[key]
        assert len(claim.history) == 4, f"{key} should have 4 history points"
        assert all(isinstance(p, ClaimHistoryPoint) for p in claim.history)


async def test_non_history_keys_have_empty_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """latest_report_date, next.*, last_20q.* don't carry history."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_earnings("AAPL", provider="fake")

    for key in (
        "latest_report_date",
        "next.report_date",
        "next.eps_estimate",
        "next.revenue_estimate",
        "last_20q.beat_count",
        "last_20q.avg_surprise_pct",
    ):
        assert result[key].history == [], f"{key} should NOT carry history"


async def test_snapshot_value_matches_history_last_for_history_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For history-bearing claims, value (snapshot) and history[-1].value
    must agree by construction. Otherwise the headline number and the
    sparkline's right endpoint disagree, which is confusing."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_earnings("AAPL", provider="fake")

    for key in HISTORY_KEYS:
        claim = result[key]
        assert claim.value == claim.history[-1].value


# ── Computed last_20q.* metrics ──────────────────────────────────────


async def test_beat_count_counts_strictly_positive_surprises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed surprises: 3 positive, 1 negative, 1 zero. Beat count = 3."""
    history = _fake_history(
        surprises=[5.0, -2.0, 0.0, 3.0, 1.5],
        periods=["2023-Q4", "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"],
        eps_actuals=[1.0, 1.0, 1.0, 1.0, 1.0],
        eps_estimates=[0.95, 1.02, 1.0, 0.97, 0.985],
    )
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(history=history))

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_20q.beat_count"].value == 3


async def test_avg_surprise_skips_nones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Average is over real surprise values only; missing quarters drop
    out of the denominator."""
    # 3 quarters with surprises, 1 missing — average of the 3 reals.
    history = _fake_history(
        surprises=[2.0, 4.0, 6.0],
        periods=["2024-Q2", "2024-Q3", "2024-Q4"],
        eps_actuals=[1.0, 1.0, 1.0],
        eps_estimates=[0.98, 0.96, 0.94],
    )
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(history=history))

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_20q.avg_surprise_pct"].value == pytest.approx(4.0)


async def test_beat_count_none_when_no_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No history → can't count beats. None signals 'unavailable'."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(history={}))

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_20q.beat_count"].value is None
    assert result["last_20q.avg_surprise_pct"].value is None


async def test_beat_count_caps_at_20_quarters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If history has 25 quarters, last_20q.* uses only the most recent 20."""
    surprises = list(range(1, 26))  # 25 strictly-positive surprises
    periods = [f"2018-Q{i}" if i <= 4 else f"2019-Q{i % 4 or 4}"
               for i in range(1, 26)]
    # All beat (positive surprise). With 25 quarters, count over last 20
    # = 20.
    eps_actuals = [1.0] * 25
    eps_estimates = [0.99] * 25
    history = _fake_history(
        eps_actuals=eps_actuals,
        eps_estimates=eps_estimates,
        surprises=[float(s) for s in surprises],
        periods=periods,
    )
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider(history=history))

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_20q.beat_count"].value == 20


# ── Provider isolation, observability ────────────────────────────────


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_earnings("AAPL", provider="not-registered")


async def test_symbol_uppercased_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(sym: str) -> tuple[dict[str, Any], dict[str, Any]]:
        seen.append(sym)
        return _fake_raw(), _fake_history()

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_earnings("aapl", provider="fake")

    assert seen == ["AAPL"]


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A09: one log_external_call per fetch_earnings, with claim_count +
    non_null_count + history_populated_count summary."""
    import logging

    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_earnings("AAPL", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.earnings"
    assert r.input_summary == {"symbol": "AAPL", "provider": "fake"}
    assert r.output_summary["claim_count"] == len(CLAIM_KEYS)
    # 3 history-bearing claims are populated by the fixture.
    assert r.output_summary["history_populated_count"] == 3
    assert r.outcome == "ok"


async def test_provider_exception_propagates_and_logs_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    def _broken(_sym: str) -> tuple[dict[str, Any], dict[str, Any]]:
        raise RuntimeError("yfinance is down")

    monkeypatch.setitem(PROVIDERS, "fake", _broken)

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="yfinance is down"):
            await fetch_earnings("AAPL", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


async def test_fetched_at_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    before = datetime.now(UTC)
    result = await fetch_earnings("AAPL", provider="fake")
    after = datetime.now(UTC)

    fetched_at = result["eps_actual"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched_at <= after + timedelta(seconds=1)
    # All claims share one fetched_at — single provider call.
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1


# ── yfinance provider math ───────────────────────────────────────────


def _patch_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    earnings_dates: pd.DataFrame | None = None,
    earnings_estimate: pd.DataFrame | None = None,
    calendar: dict | None = None,
) -> None:
    """Install a fake yfinance module so the lazy import inside the provider hits it.

    Phase 3.2.E switches from the ``earnings_dates`` property to
    ``get_earnings_dates(limit=24)`` for a wider history. We mock both
    to be safe across yfinance version drift.
    """
    import sys
    from unittest.mock import MagicMock

    fake_ticker = MagicMock()
    # earnings_dates property AND get_earnings_dates(limit) method both
    # return the same mocked frame in tests.
    fake_ticker.earnings_dates = (
        earnings_dates if earnings_dates is not None else pd.DataFrame()
    )
    fake_ticker.get_earnings_dates = MagicMock(
        return_value=(
            earnings_dates if earnings_dates is not None else pd.DataFrame()
        )
    )
    fake_ticker.earnings_estimate = (
        earnings_estimate if earnings_estimate is not None else pd.DataFrame()
    )
    fake_ticker.calendar = calendar if calendar is not None else {}

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker

    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


def _earnings_dates_5q(
    *,
    include_surprise: bool = True,
) -> pd.DataFrame:
    """Synthetic 5 past quarters newest-first (yfinance convention).

    yfinance's ``earnings_dates`` is indexed by tz-aware report-date
    Timestamp; future rows have NaN for Reported EPS / Surprise(%).
    """
    idx = pd.DatetimeIndex(
        [
            "2024-10-31",
            "2024-08-01",
            "2024-05-02",
            "2024-02-01",
            "2023-11-02",
        ],
        tz="America/New_York",
    )
    data: dict[str, list[Any]] = {
        "EPS Estimate": [1.60, 1.35, 1.50, 2.10, 1.20],
        "Reported EPS": [1.64, 1.40, 1.53, 2.18, 1.27],
    }
    if include_surprise:
        data["Surprise(%)"] = [2.5, 3.7, 2.0, 3.8, 5.8]
    return pd.DataFrame(data, index=idx)


def test_yfinance_extracts_eps_history_from_earnings_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 past quarters in earnings_dates → 5 history points per metric,
    oldest-first (chart-rendering convention)."""
    _patch_yfinance(monkeypatch, earnings_dates=_earnings_dates_5q())

    raw, history = _fetch_yfinance_earnings("AAPL")

    assert "eps_actual" in history
    assert len(history["eps_actual"]) == 5
    # Oldest is 2023-Q4 (Nov 2023 report); newest is 2024-Q4 (Oct 2024).
    assert history["eps_actual"][0].period == "2023-Q4"
    assert history["eps_actual"][-1].period == "2024-Q4"
    # Snapshot = newest.
    assert raw["eps_actual"] == 1.64
    assert raw["latest_report_date"] == "2024-10-31"


def test_yfinance_derives_surprise_when_column_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some yfinance versions / symbols omit Surprise(%); we derive it
    from (Reported - Estimate) / |Estimate| × 100."""
    _patch_yfinance(
        monkeypatch, earnings_dates=_earnings_dates_5q(include_surprise=False)
    )

    raw, history = _fetch_yfinance_earnings("AAPL")

    surprises = [p.value for p in history["eps_surprise_pct"]]
    # Newest: 1.64 vs 1.60 -> +2.5%
    assert surprises[-1] == pytest.approx((1.64 - 1.60) / 1.60 * 100.0)


def test_yfinance_handles_no_earnings_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol with no earnings history (very new IPO / delisted) — all
    values None, all histories empty. Stable shape preserved."""
    _patch_yfinance(monkeypatch)  # all defaults empty

    raw, history = _fetch_yfinance_earnings("AAPL")

    # Latest snapshot keys: None.
    assert raw.get("latest_report_date") is None
    assert raw.get("eps_actual") is None
    # Histories empty.
    for key in HISTORY_KEYS:
        assert history.get(key, []) == []


def test_yfinance_extracts_forward_estimates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """earnings_estimate['+1q'] supplies next.eps_estimate +
    next.revenue_estimate; calendar supplies next.report_date."""
    estimate = pd.DataFrame(
        {"avg": [1.5, 2.35, 7.8, 9.5], "revenueAvg": [1e10, 1.24e11, 1e11, 1.5e11]},
        index=["0q", "+1q", "0y", "+1y"],
    )
    cal = {"Earnings Date": [pd.Timestamp("2025-02-01").date()]}
    _patch_yfinance(monkeypatch, earnings_estimate=estimate, calendar=cal)

    raw, _ = _fetch_yfinance_earnings("AAPL")

    assert raw["next.eps_estimate"] == 2.35
    assert raw["next.revenue_estimate"] == 1.24e11
    assert raw["next.report_date"] == "2025-02-01"


def test_yfinance_calendar_handles_single_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance occasionally returns a single date instead of a list."""
    cal = {"Earnings Date": pd.Timestamp("2025-02-01").date()}
    _patch_yfinance(monkeypatch, calendar=cal)

    raw, _ = _fetch_yfinance_earnings("AAPL")

    assert raw["next.report_date"] == "2025-02-01"


def test_yfinance_history_is_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderer convention: history[0] is oldest, history[-1] is current."""
    _patch_yfinance(monkeypatch, earnings_dates=_earnings_dates_5q())

    _, history = _fetch_yfinance_earnings("AAPL")

    for key in HISTORY_KEYS:
        periods = [p.period for p in history[key]]
        assert periods == sorted(periods), f"{key} history not oldest-first"
