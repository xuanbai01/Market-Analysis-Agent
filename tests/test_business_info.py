"""
Tests for the ``app.services.business_info`` tool. Phase 4.4.A.

Pulls yfinance ``Ticker.info`` fields (longBusinessSummary, city/state/
country, fullTimeEmployees) and emits a ``dict[str, Claim]`` keyed by
stable claim ids so the orchestrator's section builder can pass them
through unchanged. The yfinance dependency is mocked at the module
boundary (same pattern as fundamentals / earnings).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.research import Claim
from app.services.business_info import (
    CLAIM_KEYS,
    PROVIDERS,
    fetch_business_info,
)


def _fake_info(**overrides: Any) -> dict[str, Any]:
    """A fully-populated info dict — override fields per test."""
    base: dict[str, Any] = {
        "longBusinessSummary": (
            "Apple Inc. designs, manufactures, and markets smartphones, "
            "personal computers, tablets, wearables, and accessories."
        ),
        "city": "Cupertino",
        "state": "CA",
        "country": "United States",
        "fullTimeEmployees": 164_000,
    }
    base.update(overrides)
    return base


def _fake_provider(info: dict[str, Any] | None = None) -> Any:
    def _provider(_sym: str) -> dict[str, Any]:
        return info if info is not None else _fake_info()

    return _provider


# ── Async entry point ─────────────────────────────────────────────────


async def test_returns_claim_for_each_known_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_business_info("AAPL", provider="fake")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for c in result.values():
        assert isinstance(c, Claim)


async def test_summary_claim_carries_yfinance_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_business_info("AAPL", provider="fake")

    summary = result["summary"]
    assert isinstance(summary.value, str)
    assert "Apple" in summary.value
    assert summary.source.tool == "fake.business_info"
    assert "longBusinessSummary" in (summary.source.detail or "")


async def test_hq_combines_city_state_country(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_business_info("AAPL", provider="fake")

    hq = result["hq"]
    assert hq.value == "Cupertino, CA, United States"
    assert hq.unit == "string"


async def test_employee_count_is_count_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_business_info("AAPL", provider="fake")

    employees = result["employee_count"]
    assert employees.value == 164_000
    assert employees.unit == "count"


async def test_missing_summary_lands_as_none_valued_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance occasionally returns no ``longBusinessSummary`` for a
    ticker (rare but real for thinly-covered names). The tool must not
    raise — emit a ``None``-valued Claim so the section builder still
    sees a stable shape."""
    monkeypatch.setitem(
        PROVIDERS, "fake", _fake_provider(_fake_info(longBusinessSummary=None))
    )

    result = await fetch_business_info("AAPL", provider="fake")

    assert "summary" in result
    assert result["summary"].value is None


async def test_logs_one_external_call_record(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_business_info("AAPL", provider="fake")

    records = [
        r
        for r in caplog.records
        if r.name == "app.external" and r.service_id == "fake.business_info"
    ]
    assert len(records) == 1
    r = records[0]
    assert r.input_summary == {"symbol": "AAPL", "provider": "fake"}
    assert r.outcome == "ok"


async def test_unknown_provider_raises_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        await fetch_business_info("AAPL", provider="not-a-real-provider")


async def test_fetched_at_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    before = datetime.now(UTC)
    result = await fetch_business_info("AAPL", provider="fake")
    after = datetime.now(UTC)

    fetched_at = result["summary"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched_at <= after + timedelta(seconds=1)
    # All claims share one fetched_at — they came from one provider call.
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1
