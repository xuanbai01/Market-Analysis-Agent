"""
Tests for fetch_macro (Phase 3.2.F shape).

Phase 3.2.F refactor: the macro provider used to return a flat
``{series_id: {"value": float, "date": str}}`` snapshot dict — one
observation per series. After 3.2.F it returns a
``(snapshot, history_map)`` tuple matching the fundamentals/earnings
provider contract:

- ``snapshot[id]`` = latest observation, the headline number.
- ``history_map[id]`` = list of ``ClaimHistoryPoint`` ordered oldest →
  newest for the last ~36 monthly observations (chart-rendering
  convention).

The ``<id>.value`` claim attaches its history; ``<id>.date`` and
``<id>.label`` stay history-less (date is a single label, label is
static metadata).

What we're pinning here:

1. Sector resolution drives series selection — same as before
   (curated → industry → default).
2. ``<id>.value`` claims attach ``Claim.history`` from the provider's
   history_map; ``<id>.date`` / ``<id>.label`` claims have ``[]``.
3. Snapshot consistency: ``<id>.value`` claim's ``value`` (snapshot)
   equals ``history[-1].value`` for every series the provider returned
   history for.
4. Provider-shape change: provider returns ``(snapshot, history_map)``
   tuple; legacy single-dict shape is gone.
5. Real FRED provider asks for ~36 monthly observations
   (``frequency=m``, ``limit=36``, ``sort_order=desc``) and parses both
   the snapshot (newest row) AND the history (all rows reversed to
   oldest-first), skipping yfinance-style "." sentinels.
6. ``FRED_API_KEY`` unset → real provider early-returns ``({}, {})``;
   service stamps None values + empty histories with metadata claims
   intact (same graceful-degradation contract as before).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.research import Claim, ClaimHistoryPoint
from app.services import macro as macro_module
from app.services.macro import (
    DEFAULT_SERIES,
    MACRO_HISTORY_LIMIT_MONTHS,
    PROVIDERS,
    SECTOR_SERIES,
    fetch_macro,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _fake_provider_response(
    *ids: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[ClaimHistoryPoint]]]:
    """Build a ``(snapshot, history_map)`` tuple matching the new shape.

    Each series gets a 7-point monthly history (April–October 2024)
    with a gentle uptrend; the snapshot's value equals the newest
    history point so snapshot/history consistency holds by
    construction. Tests that don't care about history can still
    inspect the snapshot.
    """
    periods = [
        "2024-04",
        "2024-05",
        "2024-06",
        "2024-07",
        "2024-08",
        "2024-09",
        "2024-10",
    ]
    snapshot: dict[str, dict[str, Any]] = {}
    history_map: dict[str, list[ClaimHistoryPoint]] = {}
    for i, sid in enumerate(ids):
        base = 4.0 + i * 0.1
        history = [
            ClaimHistoryPoint(period=p, value=round(base + j * 0.01, 4))
            for j, p in enumerate(periods)
        ]
        history_map[sid] = history
        snapshot[sid] = {"value": history[-1].value, "date": f"{periods[-1]}-01"}
    return snapshot, history_map


def _fake_provider(
    response: tuple[dict[str, dict[str, Any]], dict[str, list[ClaimHistoryPoint]]] | None = None,
) -> Any:
    """Wrap a snapshot/history pair in a provider callable that captures
    the call args (so tests that need to assert on ids can read them
    from the returned closure's ``seen`` attribute)."""
    seen: list[list[str]] = []

    def _provider(ids: list[str]) -> tuple[
        dict[str, dict[str, Any]], dict[str, list[ClaimHistoryPoint]]
    ]:
        seen.append(list(ids))
        if response is not None:
            return response
        return _fake_provider_response(*ids)

    _provider.seen = seen  # type: ignore[attr-defined]
    return _provider


# ── sector → series resolution ────────────────────────────────────────


async def test_curated_ticker_uses_sector_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _fake_provider()
    monkeypatch.setitem(PROVIDERS, "fake", provider)

    result = await fetch_macro("NVDA", provider="fake")

    expected_ids = [s.id for s in SECTOR_SERIES["semiconductors"]]
    assert provider.seen == [expected_ids]
    assert result["sector"].value == "semiconductors"
    for sid in expected_ids:
        assert f"{sid}.value" in result


async def test_unknown_ticker_uses_default_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _fake_provider()
    monkeypatch.setitem(PROVIDERS, "fake", provider)

    result = await fetch_macro("WEIRDCO", provider="fake")

    expected_ids = [s.id for s in DEFAULT_SERIES]
    assert provider.seen == [expected_ids]
    assert result["sector"].value is None  # neither curated nor industry matched


async def test_industry_fallback_resolves_sector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-curated ticker with a known industry → that sector's series."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("OBSCURE", provider="fake", industry="Semiconductors")

    assert result["sector"].value == "semiconductors"


# ── claim shape ───────────────────────────────────────────────────────


async def test_emits_metadata_and_per_series_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

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
    snapshot = {"DGS10": {"value": 4.32, "date": "2024-10-01"}}
    history = {
        "DGS10": [
            ClaimHistoryPoint(period="2024-09", value=4.20),
            ClaimHistoryPoint(period="2024-10", value=4.32),
        ]
    }
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider((snapshot, history)))

    result = await fetch_macro("NVDA", provider="fake")

    assert result["DGS10.value"].value == 4.32
    assert result["DGS10.date"].value == "2024-10-01"
    # Label comes from the static SECTOR_SERIES map, not the provider.
    series = next(s for s in SECTOR_SERIES["semiconductors"] if s.id == "DGS10")
    assert result["DGS10.label"].value == series.label


async def test_per_series_missing_observation_yields_none_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A series the provider didn't return becomes a None-value Claim with
    empty history — stable shape regardless of upstream completeness."""
    # Provider only returns one of the two semiconductors series.
    snapshot = {"DGS10": {"value": 4.32, "date": "2024-10-01"}}
    history = {"DGS10": [ClaimHistoryPoint(period="2024-10", value=4.32)]}
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider((snapshot, history)))

    result = await fetch_macro("NVDA", provider="fake")

    assert result["DGS10.value"].value == 4.32
    # MANEMP wasn't in the provider response → None Claim, not missing key.
    assert "MANEMP.value" in result
    assert result["MANEMP.value"].value is None
    assert result["MANEMP.date"].value is None
    # Label is static, still present.
    assert result["MANEMP.label"].value is not None
    # And history is empty for the absent series.
    assert result["MANEMP.value"].history == []


# ── Phase 3.2.F: history attachment ───────────────────────────────────


async def test_value_claim_carries_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``<id>.value`` claim must carry the provider's history list."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("NVDA", provider="fake")

    for s in SECTOR_SERIES["semiconductors"]:
        claim = result[f"{s.id}.value"]
        assert claim.history, f"{s.id}.value should carry history"
        # Every point is a ClaimHistoryPoint (anti-regression on shape).
        assert all(isinstance(p, ClaimHistoryPoint) for p in claim.history)


async def test_value_snapshot_matches_history_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For history-bearing claims, value (snapshot) == history[-1].value
    by construction. Otherwise the headline and the sparkline's right
    endpoint disagree."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("NVDA", provider="fake")

    for s in SECTOR_SERIES["semiconductors"]:
        claim = result[f"{s.id}.value"]
        assert claim.history, f"{s.id} should have history in this fixture"
        assert claim.value == claim.history[-1].value


async def test_date_and_label_claims_have_empty_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``<id>.value`` is history-bearing. Date is a single label;
    label is static metadata."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("NVDA", provider="fake")

    for s in SECTOR_SERIES["semiconductors"]:
        assert result[f"{s.id}.date"].history == []
        assert result[f"{s.id}.label"].history == []
    # Metadata claims also don't carry history.
    assert result["sector"].history == []
    assert result["series_list"].history == []


async def test_value_history_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderer convention: history[0] is oldest, history[-1] is current."""
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("NVDA", provider="fake")

    for s in SECTOR_SERIES["semiconductors"]:
        periods = [p.period for p in result[f"{s.id}.value"].history]
        assert periods == sorted(periods), f"{s.id} history not oldest-first"


# ── provenance ────────────────────────────────────────────────────────


async def test_per_series_claims_carry_provider_scoped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("NVDA", provider="fake")

    dgs10 = result["DGS10.value"]
    assert dgs10.source.tool == "fake.macro"
    assert "DGS10" in dgs10.source.detail


async def test_fetched_at_is_fresh_and_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

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
    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

    result = await fetch_macro("nvda", provider="fake")

    # Curated map is uppercase — only resolves if symbol was uppercased.
    assert result["sector"].value == "semiconductors"


async def test_logs_external_call(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A09: one log_external_call per fetch_macro, output_summary names
    sector + series_count + history_populated_count."""
    import logging

    monkeypatch.setitem(PROVIDERS, "fake", _fake_provider())

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
    # 3.2.F — log how many series came back with a non-empty history.
    assert r.output_summary["history_populated_count"] == len(
        SECTOR_SERIES["semiconductors"]
    )
    assert r.outcome == "ok"


async def test_provider_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    def _broken(_ids: list[str]) -> tuple[
        dict[str, dict[str, Any]], dict[str, list[ClaimHistoryPoint]]
    ]:
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
    """When the production ``fred`` provider returns ``({}, {})``, the
    service still emits metadata claims (sector, series_list, .label per
    series) so the agent knows the shape; .value/.date are None and
    .value's history is empty. Mirrors the NEWSAPI_KEY pattern."""
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda _ids: ({}, {})
    )

    result = await fetch_macro("NVDA", provider="fake")

    assert result["sector"].value == "semiconductors"
    assert result["series_list"].value  # non-empty
    assert result["DGS10.value"].value is None
    assert result["DGS10.value"].history == []
    assert result["DGS10.date"].value is None
    # Label always present from the static map.
    assert result["DGS10.label"].value is not None


# ── Real FRED provider ────────────────────────────────────────────────


def test_real_fred_provider_returns_empty_when_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped `fred` provider must early-return on missing key,
    never fire HTTP. Returns the new ``({}, {})`` tuple shape."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "")

    # If httpx.get is called, fail loudly — that means we forgot the early return.
    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("httpx.get called despite missing FRED_API_KEY")

    monkeypatch.setattr(macro_module.httpx, "get", _explode)

    snapshot, history = _fetch_fred_observations(["DGS10", "MANEMP"])
    assert snapshot == {}
    assert history == {}


def test_real_fred_provider_requests_monthly_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real provider asks FRED for ~36 monthly observations:
    ``frequency=m``, ``limit=MACRO_HISTORY_LIMIT_MONTHS``, sorted desc."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    captured: list[dict[str, Any]] = []

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"observations": []}

    def _capture(_url: str, params: dict[str, Any], timeout: float) -> Any:
        captured.append(dict(params))
        return _FakeResp()

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "test-key")
    monkeypatch.setattr(macro_module.httpx, "get", _capture)

    _fetch_fred_observations(["DGS10"])

    assert len(captured) == 1
    p = captured[0]
    assert p["series_id"] == "DGS10"
    assert p["limit"] == MACRO_HISTORY_LIMIT_MONTHS
    assert p["frequency"] == "m"
    assert p["sort_order"] == "desc"


def test_real_fred_provider_builds_history_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FRED returns newest-first; provider reverses to oldest-first.
    Snapshot is the newest row; history covers all valid rows."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    fake_obs = {
        "observations": [
            {"date": "2024-10-01", "value": "4.32"},
            {"date": "2024-09-01", "value": "4.20"},
            {"date": "2024-08-01", "value": "4.10"},
        ]
    }

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return fake_obs

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "test-key")
    monkeypatch.setattr(macro_module.httpx, "get", lambda *_a, **_kw: _FakeResp())

    snapshot, history = _fetch_fred_observations(["DGS10"])

    # Snapshot = newest (top of FRED's desc-sorted response).
    assert snapshot["DGS10"]["value"] == 4.32
    assert snapshot["DGS10"]["date"] == "2024-10-01"
    # History reversed to oldest-first.
    points = history["DGS10"]
    assert [p.period for p in points] == ["2024-08", "2024-09", "2024-10"]
    assert points[-1].value == 4.32
    # Snapshot/history consistency.
    assert snapshot["DGS10"]["value"] == points[-1].value


def test_real_fred_provider_skips_dot_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FRED returns ``"."`` for missing observations — those are dropped
    from history and never become the snapshot."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    fake_obs = {
        "observations": [
            {"date": "2024-10-01", "value": "4.32"},
            {"date": "2024-09-01", "value": "."},  # missing — dropped
            {"date": "2024-08-01", "value": "4.10"},
        ]
    }

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return fake_obs

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "test-key")
    monkeypatch.setattr(macro_module.httpx, "get", lambda *_a, **_kw: _FakeResp())

    snapshot, history = _fetch_fred_observations(["DGS10"])

    assert snapshot["DGS10"]["value"] == 4.32
    assert [p.period for p in history["DGS10"]] == ["2024-08", "2024-10"]


def test_real_fred_provider_handles_per_series_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One series' HTTP error doesn't kill the others — that series
    drops out of both snapshot and history."""
    from app.core import settings as settings_module
    from app.services.macro import _fetch_fred_observations

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"observations": [{"date": "2024-10-01", "value": "4.32"}]}

    def _maybe_fail(_url: str, params: dict[str, Any], timeout: float) -> Any:
        if params["series_id"] == "BAD":
            raise RuntimeError("network blip")
        return _FakeResp()

    monkeypatch.setattr(settings_module.settings, "FRED_API_KEY", "test-key")
    monkeypatch.setattr(macro_module.httpx, "get", _maybe_fail)

    snapshot, history = _fetch_fred_observations(["DGS10", "BAD"])

    assert "DGS10" in snapshot
    assert "DGS10" in history
    assert "BAD" not in snapshot
    assert "BAD" not in history
