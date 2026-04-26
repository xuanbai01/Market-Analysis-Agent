"""
Tests for fetch_macro. The FRED HTTP provider is mocked at the
provider registry; the sector resolver is exercised via the real
``resolve_sector`` function (covered separately in test_sectors).

What we're pinning:

1. Sector resolution drives series selection — curated ticker uses
   curated map, uncurated ticker uses ``info["industry"]`` fallback,
   neither match → default series set.
2. Per-series claims have stable shape (``<SERIES>.value`` / ``.date``
   / ``.label``) — agent reads by key without per-symbol branching.
3. Per-series fetch failure isolated — one missing series doesn't
   blank the whole response.
4. FRED_API_KEY missing → metadata claims emitted, value claims are
   None (graceful degradation, mirrors NEWSAPI_KEY pattern).
5. Provenance — Source.tool reflects the provider id, detail names
   the FRED series id.
6. Observability — single log_external_call with sector + series_count.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.research import Claim
from app.services import macro as macro_module
from app.services.macro import (
    DEFAULT_SERIES,
    PROVIDERS,
    SECTOR_SERIES,
    fetch_macro,
)


def _fake_observations(*ids: str) -> dict[str, dict[str, Any]]:
    """Build a typical FRED observations payload for the given series ids."""
    return {
        sid: {"value": 4.32 + i * 0.1, "date": "2024-10-25"}
        for i, sid in enumerate(ids)
    }


# ── sector → series resolution ────────────────────────────────────────


async def test_curated_ticker_uses_sector_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def _capture(ids: list[str]) -> dict[str, Any]:
        seen.append(list(ids))
        return _fake_observations(*ids)

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    result = await fetch_macro("NVDA", provider="fake")

    expected_ids = [s.id for s in SECTOR_SERIES["semiconductors"]]
    assert seen == [expected_ids]
    assert result["sector"].value == "semiconductors"
    for sid in expected_ids:
        assert f"{sid}.value" in result


async def test_unknown_ticker_uses_default_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def _capture(ids: list[str]) -> dict[str, Any]:
        seen.append(list(ids))
        return _fake_observations(*ids)

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    result = await fetch_macro("WEIRDCO", provider="fake")

    expected_ids = [s.id for s in DEFAULT_SERIES]
    assert seen == [expected_ids]
    assert result["sector"].value is None  # neither curated nor industry matched


async def test_industry_fallback_resolves_sector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a non-curated ticker has a known industry, use that sector's series."""

    def _provider(ids: list[str]) -> dict[str, Any]:
        return _fake_observations(*ids)

    monkeypatch.setitem(PROVIDERS, "fake", _provider)

    # Patch the industry resolver — fetch_macro doesn't fetch industry
    # itself; it accepts an optional industry kwarg from the caller.
    result = await fetch_macro("OBSCURE", provider="fake", industry="Semiconductors")

    assert result["sector"].value == "semiconductors"


# ── claim shape ───────────────────────────────────────────────────────


async def test_emits_metadata_and_per_series_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda ids: _fake_observations(*ids)
    )

    result = await fetch_macro("NVDA", provider="fake")

    # Metadata claims always present.
    assert "sector" in result
    assert "series_list" in result
    assert isinstance(result["sector"], Claim)

    # Per-series triplets present for each resolved series.
    expected_ids = [s.id for s in SECTOR_SERIES["semiconductors"]]
    assert result["series_list"].value == ", ".join(expected_ids)
    for sid in expected_ids:
        assert f"{sid}.value" in result
        assert f"{sid}.date" in result
        assert f"{sid}.label" in result


async def test_per_series_value_and_date_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _ids: {"DGS10": {"value": 4.32, "date": "2024-10-25"}},
    )

    result = await fetch_macro("NVDA", provider="fake")

    assert result["DGS10.value"].value == 4.32
    assert result["DGS10.date"].value == "2024-10-25"
    # Label comes from the static SECTOR_SERIES map, not the provider.
    series = next(s for s in SECTOR_SERIES["semiconductors"] if s.id == "DGS10")
    assert result["DGS10.label"].value == series.label


async def test_per_series_missing_observation_yields_none_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A series the provider didn't return becomes a None-value Claim."""
    # Provider only returns one of the two semiconductors series.
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _ids: {"DGS10": {"value": 4.32, "date": "2024-10-25"}},
    )

    result = await fetch_macro("NVDA", provider="fake")

    assert result["DGS10.value"].value == 4.32
    # MANEMP wasn't in the provider response → None Claim, not missing key.
    assert "MANEMP.value" in result
    assert result["MANEMP.value"].value is None
    assert result["MANEMP.date"].value is None
    # Label is static, still present.
    assert result["MANEMP.label"].value is not None


# ── provenance ────────────────────────────────────────────────────────


async def test_per_series_claims_carry_provider_scoped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda ids: _fake_observations(*ids)
    )

    result = await fetch_macro("NVDA", provider="fake")

    dgs10 = result["DGS10.value"]
    assert dgs10.source.tool == "fake.macro"
    assert "DGS10" in dgs10.source.detail


async def test_fetched_at_is_fresh_and_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda ids: _fake_observations(*ids)
    )

    before = datetime.now(UTC)
    result = await fetch_macro("NVDA", provider="fake")
    after = datetime.now(UTC)

    fetched = result["DGS10.value"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched <= after + timedelta(seconds=1)
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1


# ── validation + observability ────────────────────────────────────────


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_macro("NVDA", provider="not-registered")


async def test_symbol_uppercased_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda ids: _fake_observations(*ids)
    )

    result = await fetch_macro("nvda", provider="fake")

    # Curated map is uppercase — only resolves if symbol was uppercased.
    assert result["sector"].value == "semiconductors"


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    monkeypatch.setitem(
        PROVIDERS, "fake", lambda ids: _fake_observations(*ids)
    )

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_macro("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.macro"
    assert r.input_summary["symbol"] == "NVDA"
    assert r.input_summary["provider"] == "fake"
    assert r.output_summary["sector"] == "semiconductors"
    assert r.output_summary["series_count"] == len(SECTOR_SERIES["semiconductors"])
    assert r.outcome == "ok"


async def test_provider_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    def _broken(_ids: list[str]) -> dict[str, Any]:
        raise RuntimeError("FRED is down")

    monkeypatch.setitem(PROVIDERS, "fake", _broken)

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="FRED is down"):
            await fetch_macro("NVDA", provider="fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


# ── FRED_API_KEY graceful degradation ─────────────────────────────────


async def test_missing_api_key_emits_metadata_with_none_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When FRED_API_KEY is unset, the production ``fred`` provider returns
    {} instead of hitting the API. The service still emits the metadata
    claims (sector, series_list, .label per series) so the agent knows
    the shape; .value and .date are None.
    """
    # Empty provider output simulates "no API key" without hitting the real provider.
    monkeypatch.setitem(PROVIDERS, "fake", lambda _ids: {})

    result = await fetch_macro("NVDA", provider="fake")

    assert result["sector"].value == "semiconductors"
    assert result["series_list"].value  # non-empty
    assert result["DGS10.value"].value is None
    assert result["DGS10.date"].value is None
    # Label always present from the static map.
    assert result["DGS10.label"].value is not None


# ── FRED provider — real one returns {} when API key is missing ───────


def test_real_fred_provider_returns_empty_when_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped `fred` provider must early-return on missing key, never fire HTTP."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "")

    # If httpx.get is called, fail loudly — that means we forgot the early return.
    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("httpx.get called despite missing FRED_API_KEY")

    monkeypatch.setattr(macro_module.httpx, "get", _explode)

    result = _fetch_fred_observations(["DGS10", "MANEMP"])
    assert result == {}
