"""
Tests for fetch_peers. The async entry point is exercised through a
registered fake provider (no real yfinance call); the yfinance
provider's logic — sector resolution, per-peer fan-out, median math —
is exercised separately via a mocked ``yfinance.Ticker`` factory.

What we're pinning here:

1. Sector resolution — curated map wins over yfinance.industry; both
   miss → empty peer list, no exception.
2. Stable claim keys — ``sector``, ``peers_list``, ``<PEER>.<metric>``
   for each (peer, metric) pair, plus ``median.<metric>`` per metric.
3. Provenance — every claim's Source carries the peer-scoped detail
   string and the right tool id.
4. Median math — computed only over non-null peer values; None when
   all peers are missing the metric.
5. Per-peer isolation — one peer's missing data doesn't poison others'
   medians or kill the call.
6. Observability — single log_external_call wrapping the whole
   fan-out, not one per peer.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.research import Claim
from app.services.peers import (
    PEER_METRICS,
    PROVIDERS,
    _fetch_yfinance_peers,
    fetch_peers,
)

# ── Fake provider helpers ─────────────────────────────────────────────


def _fake_payload(
    *,
    sector: str | None = "semiconductors",
    peers: list[str] | None = None,
    metrics: dict[str, dict[str, float | None]] | None = None,
) -> dict[str, Any]:
    """Build a payload matching the contract the provider returns to the service.

    Provider signature: (symbol) -> {
        "sector": str | None,
        "peers": list[str],
        "metrics": {peer_symbol: {metric_key: value | None}},
    }
    """
    if peers is None:
        peers = ["AMD", "INTC", "AVGO", "QCOM"]
    if metrics is None:
        # Realistic-ish numbers, all peers populated.
        metrics = {
            p: {
                "trailing_pe": 25.0 + i,
                "p_s": 5.0 + i,
                "ev_ebitda": 20.0 + i,
                "gross_margin": 0.50 + i * 0.02,
            }
            for i, p in enumerate(peers)
        }
    return {"sector": sector, "peers": peers, "metrics": metrics}


# ── async entry point ─────────────────────────────────────────────────


async def test_emits_metadata_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_payload())

    result = await fetch_peers("NVDA", provider="fake")

    assert "sector" in result
    assert isinstance(result["sector"], Claim)
    assert result["sector"].value == "semiconductors"

    assert "peers_list" in result
    # peers_list is a comma-sep string so it fits ClaimValue (str).
    assert result["peers_list"].value == "AMD, INTC, AVGO, QCOM"


async def test_emits_per_peer_per_metric_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_payload())

    result = await fetch_peers("NVDA", provider="fake")

    for peer in ["AMD", "INTC", "AVGO", "QCOM"]:
        for metric in PEER_METRICS:
            key = f"{peer}.{metric}"
            assert key in result, f"missing {key}"
            assert isinstance(result[key], Claim)


async def test_per_peer_claims_carry_correct_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_payload())

    result = await fetch_peers("NVDA", provider="fake")

    pe = result["AMD.trailing_pe"]
    assert pe.source.tool == "fake.peers"
    assert "AMD" in pe.source.detail
    assert "trailingPE" in pe.source.detail
    assert pe.value == 25.0


async def test_median_claims_computed_across_non_null_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Median takes only non-null peer values; one missing value does not poison."""
    metrics = {
        "AMD": {"trailing_pe": 20.0, "p_s": 4.0, "ev_ebitda": 15.0, "gross_margin": 0.50},
        "INTC": {
            "trailing_pe": 30.0,
            "p_s": 5.0,
            "ev_ebitda": None,
            "gross_margin": 0.55,
        },
        "AVGO": {"trailing_pe": 40.0, "p_s": 6.0, "ev_ebitda": 25.0, "gross_margin": 0.60},
    }
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: _fake_payload(peers=["AMD", "INTC", "AVGO"], metrics=metrics),
    )

    result = await fetch_peers("NVDA", provider="fake")

    # Median of [20, 30, 40] = 30; median of [15, 25] = 20 (non-null only).
    assert result["median.trailing_pe"].value == 30.0
    assert result["median.ev_ebitda"].value == 20.0
    # Median's source detail flags it as computed.
    assert "computed" in result["median.trailing_pe"].source.detail.lower()


async def test_median_none_when_all_peers_missing_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = {
        "AMD": {"trailing_pe": None, "p_s": 4.0, "ev_ebitda": 15.0, "gross_margin": 0.50},
        "INTC": {
            "trailing_pe": None,
            "p_s": 5.0,
            "ev_ebitda": 16.0,
            "gross_margin": 0.55,
        },
    }
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: _fake_payload(peers=["AMD", "INTC"], metrics=metrics),
    )

    result = await fetch_peers("NVDA", provider="fake")

    assert result["median.trailing_pe"].value is None


async def test_unknown_sector_returns_empty_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither curated map nor industry fallback resolves, peer list is empty.

    The shape contract still holds — sector + peers_list claims are
    present (with None / empty values), no per-peer claims are emitted.
    """
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda _sym: _fake_payload(sector=None, peers=[], metrics={})
    )

    result = await fetch_peers("WEIRDCO", provider="fake")

    assert result["sector"].value is None
    assert result["peers_list"].value == ""
    # No per-peer keys emitted at all.
    per_peer_keys = [
        k for k in result if "." in k and not k.startswith("median.")
    ]
    assert per_peer_keys == []
    # No median claims either — nothing to median.
    median_keys = [k for k in result if k.startswith("median.")]
    assert median_keys == []


async def test_fetched_at_is_fresh_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_payload())

    before = datetime.now(UTC)
    result = await fetch_peers("NVDA", provider="fake")
    after = datetime.now(UTC)

    fetched = result["AMD.trailing_pe"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched <= after + timedelta(seconds=1)
    # All claims share one fetched_at — single provider call.
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_peers("NVDA", provider="not-registered")


async def test_symbol_uppercased_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(sym: str) -> dict[str, Any]:
        seen.append(sym)
        return _fake_payload()

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_peers("nvda", provider="fake")

    assert seen == ["NVDA"]


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Single log record per call, with the right service id and counts."""
    import logging

    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: _fake_payload())

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_peers("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.peers"
    assert r.input_summary == {"symbol": "NVDA", "provider": "fake"}
    assert r.output_summary["peer_count"] == 4
    assert r.output_summary["sector"] == "semiconductors"
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
            await fetch_peers("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


# ── yfinance provider — sector resolution + fan-out ───────────────────


def _patch_yfinance_factory(
    monkeypatch: pytest.MonkeyPatch,
    info_by_symbol: dict[str, dict[str, Any]],
) -> None:
    """Install a yfinance.Ticker factory that returns per-symbol .info dicts.

    Each call to ``yfinance.Ticker(SYM)`` returns a MagicMock whose
    ``.info`` matches the dict passed for SYM (defaulting to {}). This
    lets tests assert per-peer fan-out works correctly.
    """
    import sys
    from unittest.mock import MagicMock

    def _make_ticker(sym: str) -> MagicMock:
        t = MagicMock()
        t.info = info_by_symbol.get(sym, {})
        return t

    fake_yf = MagicMock()
    fake_yf.Ticker.side_effect = _make_ticker

    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


def test_yfinance_curated_ticker_resolves_known_sector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticker that's hard-coded as semiconductors should never hit yfinance for sector."""
    _patch_yfinance_factory(
        monkeypatch,
        {
            "NVDA": {},  # info irrelevant — sector comes from the curated map
            "AMD": {"trailingPE": 25.0},
            "INTC": {"trailingPE": 18.0},
            "AVGO": {"trailingPE": 28.0},
            "QCOM": {"trailingPE": 16.0},
            "TSM": {"trailingPE": 22.0},
            "MU": {"trailingPE": 14.0},
        },
    )

    payload = _fetch_yfinance_peers("NVDA")

    assert payload["sector"] == "semiconductors"
    assert "NVDA" not in payload["peers"]  # primary excluded from peer list
    assert set(payload["peers"]).issubset(
        {"AMD", "INTC", "AVGO", "QCOM", "TSM", "MU"}
    )
    assert len(payload["peers"]) >= 3


def test_yfinance_industry_fallback_for_uncurated_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown ticker but yfinance reports a known industry → use the fallback peers."""
    _patch_yfinance_factory(
        monkeypatch,
        {
            "WEIRDCO": {"industry": "Semiconductors"},
            "AMD": {"trailingPE": 25.0},
            "INTC": {"trailingPE": 18.0},
            "AVGO": {"trailingPE": 28.0},
            "QCOM": {"trailingPE": 16.0},
            "TSM": {"trailingPE": 22.0},
            "MU": {"trailingPE": 14.0},
        },
    )

    payload = _fetch_yfinance_peers("WEIRDCO")

    assert payload["sector"] == "semiconductors"
    assert len(payload["peers"]) >= 3


def test_yfinance_unknown_ticker_and_industry_returns_empty_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance_factory(
        monkeypatch, {"WEIRDCO": {"industry": "Some Niche We've Never Heard Of"}}
    )

    payload = _fetch_yfinance_peers("WEIRDCO")

    assert payload["sector"] is None
    assert payload["peers"] == []
    assert payload["metrics"] == {}


def test_yfinance_per_peer_metrics_pulled_from_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance_factory(
        monkeypatch,
        {
            "NVDA": {},
            "AMD": {
                "trailingPE": 25.0,
                "priceToSalesTrailing12Months": 5.0,
                "enterpriseToEbitda": 20.0,
                "grossMargins": 0.50,
            },
            "INTC": {
                "trailingPE": 18.0,
                "priceToSalesTrailing12Months": 2.5,
                "enterpriseToEbitda": 12.0,
                "grossMargins": 0.45,
            },
            "AVGO": {},  # all None
            "QCOM": {
                "trailingPE": 16.0,
                "priceToSalesTrailing12Months": 4.0,
                "enterpriseToEbitda": 14.0,
                "grossMargins": 0.55,
            },
            "TSM": {},
            "MU": {},
        },
    )

    payload = _fetch_yfinance_peers("NVDA")

    assert payload["metrics"]["AMD"]["trailing_pe"] == 25.0
    assert payload["metrics"]["AMD"]["gross_margin"] == 0.50
    assert payload["metrics"]["INTC"]["p_s"] == 2.5
    assert payload["metrics"]["AVGO"]["trailing_pe"] is None
    assert payload["metrics"]["AVGO"]["gross_margin"] is None


def test_yfinance_one_peer_failing_does_not_kill_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer whose .info raises is dropped to all-None, others stay populated."""
    import sys
    from unittest.mock import MagicMock, PropertyMock

    def _make_ticker(sym: str) -> MagicMock:
        t = MagicMock()
        if sym == "INTC":
            type(t).info = PropertyMock(side_effect=RuntimeError("INTC fetch broke"))
        elif sym == "AMD":
            t.info = {"trailingPE": 25.0}
        else:
            t.info = {}
        return t

    fake_yf = MagicMock()
    fake_yf.Ticker.side_effect = _make_ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    payload = _fetch_yfinance_peers("NVDA")

    # AMD still came through.
    assert payload["metrics"]["AMD"]["trailing_pe"] == 25.0
    # INTC entry exists but every metric is None.
    assert payload["metrics"]["INTC"] == {m: None for m in PEER_METRICS}
