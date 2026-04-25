"""
Tests for fetch_earnings. Pattern matches fundamentals + peers: provider
mocked at the registry; the yfinance provider's DataFrame extraction
exercised separately with a mocked Ticker.

What we're pinning:

1. Stable shape — all 21 advertised keys present in the response, even
   when upstream returned fewer than 4 past quarters.
2. Quarter ordering — q1 is the most recent past quarter; q2 older; q4
   oldest. Provider order shouldn't matter.
3. Computed math — beat_count counts strictly-positive surprises; avg
   takes only non-null surprises; both None when there are no past
   quarters at all.
4. Surprise computation fallback — when yfinance's own `Surprise(%)` is
   missing but actual + estimate are present, derive it ourselves.
5. Provenance — Source.tool reflects the provider id; details name the
   yfinance attribute or "computed" for derived metrics.
6. Observability — single log_external_call with claim_count +
   non_null_count.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.schemas.research import Claim
from app.services.earnings import (
    CLAIM_KEYS,
    PROVIDERS,
    _fetch_yfinance_earnings,
    fetch_earnings,
)


def _fake_raw(**overrides: Any) -> dict[str, Any]:
    """Fully-populated raw provider payload — override per test."""
    base: dict[str, Any] = {
        # Past quarters, q1=newest
        "q1.report_date": "2024-10-31",
        "q1.eps_actual": 1.64,
        "q1.eps_estimate": 1.60,
        "q1.eps_surprise_pct": 2.5,
        "q2.report_date": "2024-08-01",
        "q2.eps_actual": 1.40,
        "q2.eps_estimate": 1.35,
        "q2.eps_surprise_pct": 3.7,
        "q3.report_date": "2024-05-02",
        "q3.eps_actual": 1.53,
        "q3.eps_estimate": 1.50,
        "q3.eps_surprise_pct": 2.0,
        "q4.report_date": "2024-02-01",
        "q4.eps_actual": 2.18,
        "q4.eps_estimate": 2.10,
        "q4.eps_surprise_pct": 3.8,
        # Forward
        "next.report_date": "2025-02-01",
        "next.eps_estimate": 2.35,
        "next.revenue_estimate": 124_000_000_000,
    }
    # Sanity guard: fixture must list every non-computed key, otherwise
    # tests silently miss whichever key was added without updating it.
    raw_keys_advertised = {
        k for k in CLAIM_KEYS if not k.startswith("last_4q.")
    }
    assert set(base) == raw_keys_advertised, "fixture out of sync with CLAIM_KEYS"
    base.update(overrides)
    return base


# ── async entry point ─────────────────────────────────────────────────


async def test_returns_claim_for_each_known_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_earnings("AAPL", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for claim in result.values():
        assert isinstance(claim, Claim)


async def test_past_quarter_values_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["q1.eps_actual"].value == 1.64
    assert result["q1.eps_estimate"].value == 1.60
    assert result["q1.eps_surprise_pct"].value == 2.5
    assert result["q1.report_date"].value == "2024-10-31"


async def test_forward_quarter_values_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["next.report_date"].value == "2025-02-01"
    assert result["next.eps_estimate"].value == 2.35
    assert result["next.revenue_estimate"].value == 124_000_000_000


async def test_beat_count_counts_strictly_positive_surprises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 0% surprise is a meet, not a beat. Only surprise > 0 counts."""
    raw = _fake_raw(**{
        "q1.eps_surprise_pct": 5.0,
        "q2.eps_surprise_pct": -2.0,
        "q3.eps_surprise_pct": 0.0,
        "q4.eps_surprise_pct": 1.0,
    })
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_4q.beat_count"].value == 2


async def test_avg_surprise_pct_arithmetic_mean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fake_raw(**{
        "q1.eps_surprise_pct": 5.0,
        "q2.eps_surprise_pct": -2.0,
        "q3.eps_surprise_pct": 3.0,
        "q4.eps_surprise_pct": 1.0,
    })
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_4q.avg_surprise_pct"].value == pytest.approx(1.75)


async def test_avg_and_beat_count_skip_null_surprises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Computed stats use only non-null surprises — partial history shouldn't poison the mean."""
    raw = _fake_raw(**{
        "q1.eps_surprise_pct": 4.0,
        "q2.eps_surprise_pct": 2.0,
        "q3.eps_surprise_pct": None,
        "q4.eps_surprise_pct": None,
    })
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_4q.beat_count"].value == 2
    assert result["last_4q.avg_surprise_pct"].value == pytest.approx(3.0)


async def test_computed_stats_none_when_no_past_quarters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fake_raw(**{
        "q1.eps_surprise_pct": None,
        "q2.eps_surprise_pct": None,
        "q3.eps_surprise_pct": None,
        "q4.eps_surprise_pct": None,
    })
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: raw)

    result = await fetch_earnings("AAPL", provider="fake")

    assert result["last_4q.beat_count"].value is None
    assert result["last_4q.avg_surprise_pct"].value is None


async def test_partial_history_keeps_stable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A young IPO with only 2 quarters of history still emits all 21 keys."""
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: {
            "q1.report_date": "2024-10-31",
            "q1.eps_actual": 1.64,
            "q1.eps_estimate": 1.60,
            "q1.eps_surprise_pct": 2.5,
            "q2.report_date": "2024-08-01",
            "q2.eps_actual": 1.40,
            "q2.eps_estimate": 1.35,
            "q2.eps_surprise_pct": 3.7,
            # q3, q4, next.* missing entirely
        },
    )

    result = await fetch_earnings("AAPL", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    assert result["q3.eps_actual"].value is None
    assert result["q4.report_date"].value is None
    assert result["next.eps_estimate"].value is None


async def test_claims_carry_provider_scoped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    result = await fetch_earnings("AAPL", provider="fake")

    eps = result["q1.eps_actual"]
    assert eps.source.tool == "fake.earnings"
    assert "earnings_dates" in eps.source.detail.lower()

    bc = result["last_4q.beat_count"]
    assert "computed" in bc.source.detail.lower()


async def test_fetched_at_is_fresh_and_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    before = datetime.now(UTC)
    result = await fetch_earnings("AAPL", provider="fake")
    after = datetime.now(UTC)

    fetched = result["q1.eps_actual"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched <= after + timedelta(seconds=1)
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_earnings("AAPL", provider="not-registered")


async def test_symbol_uppercased_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(sym: str) -> dict[str, Any]:
        seen.append(sym)
        return _fake_raw()

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_earnings("aapl", provider="fake")

    assert seen == ["AAPL"]


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_raw())

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_earnings("AAPL", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.earnings"
    assert r.input_summary == {"symbol": "AAPL", "provider": "fake"}
    assert r.output_summary["claim_count"] == len(CLAIM_KEYS)
    # Full fixture populates all 19 raw keys + 2 computed = 21 non-null.
    assert r.output_summary["non_null_count"] == len(CLAIM_KEYS)
    assert r.outcome == "ok"


async def test_provider_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    def _broken(_sym: str) -> dict[str, Any]:
        raise RuntimeError("yfinance is down")

    monkeypatch.setitem(PROVIDERS, "fake", _broken)

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="yfinance is down"):
            await fetch_earnings("AAPL", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


# ── yfinance provider — DataFrame extraction ──────────────────────────


def _earnings_dates_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a yfinance-shaped earnings_dates DataFrame.

    yfinance returns a DataFrame indexed by tz-aware datetime (the
    earnings date), with columns 'EPS Estimate', 'Reported EPS',
    'Surprise(%)'. Rows include both past and future quarters; future
    rows have NaN for Reported EPS / Surprise(%).
    """
    if not rows:
        return pd.DataFrame(
            columns=["EPS Estimate", "Reported EPS", "Surprise(%)"]
        )
    df = pd.DataFrame(rows).set_index("date")
    return df


def _patch_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    earnings_dates: pd.DataFrame | None = None,
    earnings_estimate: pd.DataFrame | None = None,
    calendar: dict[str, Any] | None = None,
) -> None:
    """Install a fake yfinance with a Ticker that returns the given attributes."""
    import sys
    from unittest.mock import MagicMock

    fake_ticker = MagicMock()
    fake_ticker.earnings_dates = (
        earnings_dates if earnings_dates is not None else pd.DataFrame()
    )
    fake_ticker.earnings_estimate = (
        earnings_estimate if earnings_estimate is not None else pd.DataFrame()
    )
    fake_ticker.calendar = calendar if calendar is not None else {}

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker

    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


def test_yfinance_extracts_4_past_quarters_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past quarters extracted from earnings_dates, newest assigned to q1."""
    rows = [
        # Future row — should be ignored for past quarters
        {
            "date": pd.Timestamp("2025-02-01", tz="UTC"),
            "EPS Estimate": 2.35,
            "Reported EPS": float("nan"),
            "Surprise(%)": float("nan"),
        },
        # Past quarters in random order
        {
            "date": pd.Timestamp("2024-05-02", tz="UTC"),
            "EPS Estimate": 1.50,
            "Reported EPS": 1.53,
            "Surprise(%)": 2.0,
        },
        {
            "date": pd.Timestamp("2024-10-31", tz="UTC"),
            "EPS Estimate": 1.60,
            "Reported EPS": 1.64,
            "Surprise(%)": 2.5,
        },
        {
            "date": pd.Timestamp("2024-02-01", tz="UTC"),
            "EPS Estimate": 2.10,
            "Reported EPS": 2.18,
            "Surprise(%)": 3.8,
        },
        {
            "date": pd.Timestamp("2024-08-01", tz="UTC"),
            "EPS Estimate": 1.35,
            "Reported EPS": 1.40,
            "Surprise(%)": 3.7,
        },
    ]
    _patch_yfinance(monkeypatch, earnings_dates=_earnings_dates_df(rows))

    raw = _fetch_yfinance_earnings("AAPL")

    # Newest first: 2024-10-31 → q1, then 08-01, 05-02, 02-01.
    assert raw["q1.report_date"] == "2024-10-31"
    assert raw["q1.eps_actual"] == 1.64
    assert raw["q1.eps_estimate"] == 1.60
    assert raw["q1.eps_surprise_pct"] == 2.5

    assert raw["q2.report_date"] == "2024-08-01"
    assert raw["q3.report_date"] == "2024-05-02"
    assert raw["q4.report_date"] == "2024-02-01"


def test_yfinance_only_two_past_quarters_leaves_q3_q4_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "date": pd.Timestamp("2024-10-31", tz="UTC"),
            "EPS Estimate": 1.60,
            "Reported EPS": 1.64,
            "Surprise(%)": 2.5,
        },
        {
            "date": pd.Timestamp("2024-08-01", tz="UTC"),
            "EPS Estimate": 1.35,
            "Reported EPS": 1.40,
            "Surprise(%)": 3.7,
        },
    ]
    _patch_yfinance(monkeypatch, earnings_dates=_earnings_dates_df(rows))

    raw = _fetch_yfinance_earnings("AAPL")

    assert raw["q1.eps_actual"] == 1.64
    assert raw["q2.eps_actual"] == 1.40
    assert raw.get("q3.eps_actual") is None
    assert raw.get("q4.report_date") is None


def test_yfinance_derives_surprise_when_column_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance occasionally omits Surprise(%); derive from actual + estimate."""
    rows = [
        {
            "date": pd.Timestamp("2024-10-31", tz="UTC"),
            "EPS Estimate": 1.60,
            "Reported EPS": 1.64,
            # No Surprise(%) column at all on this DataFrame
        }
    ]
    df = pd.DataFrame(rows).set_index("date")
    _patch_yfinance(monkeypatch, earnings_dates=df)

    raw = _fetch_yfinance_earnings("AAPL")

    # (1.64 - 1.60) / 1.60 * 100 = 2.5
    assert raw["q1.eps_surprise_pct"] == pytest.approx(2.5)


def test_yfinance_handles_completely_empty_dataframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(monkeypatch)

    raw = _fetch_yfinance_earnings("AAPL")

    # No quarters present, no forward data. The provider returns a (possibly
    # sparse) dict; the service stamps None Claims for missing keys.
    assert raw.get("q1.eps_actual") is None
    assert raw.get("next.eps_estimate") is None


def test_yfinance_pulls_forward_estimate_and_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward EPS comes from earnings_estimate (period '+1q'); date from calendar."""
    estimate_df = pd.DataFrame(
        {
            "avg": [2.35],
            "revenueAvg": [124_000_000_000],
        },
        index=["+1q"],
    )
    calendar = {"Earnings Date": [pd.Timestamp("2025-02-01").date()]}

    _patch_yfinance(
        monkeypatch,
        earnings_estimate=estimate_df,
        calendar=calendar,
    )

    raw = _fetch_yfinance_earnings("AAPL")

    assert raw["next.eps_estimate"] == pytest.approx(2.35)
    assert raw["next.revenue_estimate"] == 124_000_000_000
    assert raw["next.report_date"] == "2025-02-01"
