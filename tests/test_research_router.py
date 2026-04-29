"""
Tests for ``POST /v1/research/{symbol}``.

The router is a thin coordinator: cache lookup → orchestrator (on
miss) → cache write. All three are mocked at module boundaries so
these tests exercise routing, query validation, error mapping, the
cache-flow control logic, and response shape — NOT the orchestration
logic (covered in test_research_orchestrator.py) or the cache repo
itself (covered in test_research_cache.py).

The shared ``client`` fixture in conftest is DB-bound; we wire a
local ASGI client that overrides ``get_session`` to yield None and
mocks the cache module so tests don't need postgres available.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.dependencies import get_session
from app.main import app
from app.schemas.research import (
    Claim,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from app.services import research_cache as cache_module
from app.services import research_orchestrator as orch_module


@pytest_asyncio.fixture
async def research_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """ASGI client wired straight to the FastAPI app — no DB.

    Defaults: cache always misses, upsert is a no-op. Tests can
    override either via the ``_patch_cache`` helper. The session
    dependency is overridden to yield None — none of the cache
    functions dereference it under these mocks.

    ``raise_app_exceptions=False`` lets unhandled exceptions render
    as 500 problem+json from the global handler in app.core.errors
    rather than re-raising into the test runner.
    """

    async def _no_session() -> AsyncIterator[None]:
        yield None

    async def _miss(*_args: Any, **_kw: Any) -> None:
        return None

    async def _noop_upsert(*_args: Any, **_kw: Any) -> None:
        return None

    app.dependency_overrides[get_session] = _no_session
    monkeypatch.setattr(cache_module, "lookup_recent", _miss)
    monkeypatch.setattr(cache_module, "upsert", _noop_upsert)

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)


def _stub_report(symbol: str = "AAPL") -> ResearchReport:
    """A minimal but valid ResearchReport the orchestrator stub returns."""
    src = Source(tool="test.tool", fetched_at=datetime.now(UTC))
    return ResearchReport(
        symbol=symbol,
        generated_at=datetime.now(UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[
                    Claim(description="Trailing P/E", value=28.5, source=src),
                ],
                summary="Trades at 28.5x trailing earnings.",
                confidence=Confidence.HIGH,
            )
        ],
        overall_confidence=Confidence.HIGH,
        tool_calls_audit=["fetch_fundamentals: ok"],
    )


def _patch_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    response: ResearchReport | Exception,
) -> list[dict[str, Any]]:
    """Replace ``compose_research_report`` with a stub. Returns a call log."""
    captured: list[dict[str, Any]] = []

    async def _fake(symbol: str, focus: Any) -> ResearchReport:
        captured.append({"symbol": symbol, "focus": focus})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(orch_module, "compose_research_report", _fake)
    return captured


def _patch_cache_lookup(
    monkeypatch: pytest.MonkeyPatch,
    returns: ResearchReport | None,
) -> list[dict[str, Any]]:
    """Replace ``research_cache.lookup_recent`` with a stub.

    Returns a call log so tests can assert on (symbol, focus,
    max_age_hours). The default fixture sets lookup to always-miss;
    use this to inject a hit.
    """
    captured: list[dict[str, Any]] = []

    async def _fake(session: Any, **kwargs: Any) -> ResearchReport | None:
        captured.append(kwargs)
        return returns

    monkeypatch.setattr(cache_module, "lookup_recent", _fake)
    return captured


def _patch_cache_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Replace ``research_cache.upsert`` with a recorder.

    Returns a list that captures every upsert call's kwargs so tests
    can assert what got written.
    """
    captured: list[dict[str, Any]] = []

    async def _fake(session: Any, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(cache_module, "upsert", _fake)
    return captured


# ── Happy paths ──────────────────────────────────────────────────────


async def test_research_full_focus_returns_report(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_orchestrator(monkeypatch, _stub_report("AAPL"))

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["overall_confidence"] == "high"
    assert len(body["sections"]) == 1
    assert body["sections"][0]["title"] == "Valuation"


async def test_research_default_focus_is_full(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting ``?focus=`` should default to FULL."""
    captured = _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 200
    assert captured[0]["focus"].value == "full"


async def test_research_earnings_focus_threaded_through(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/AAPL?focus=earnings")

    assert resp.status_code == 200
    assert captured[0]["focus"].value == "earnings"


async def test_symbol_uppercased_before_orchestrator(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_orchestrator(monkeypatch, _stub_report("AAPL"))

    resp = await research_client.post("/v1/research/aapl")

    assert resp.status_code == 200
    assert captured[0]["symbol"] == "AAPL"


# ── Response shape & audit ───────────────────────────────────────────


async def test_response_includes_tool_calls_audit(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/AAPL")
    body = resp.json()

    assert "tool_calls_audit" in body
    assert body["tool_calls_audit"] == ["fetch_fundamentals: ok"]


async def test_response_section_includes_claims_and_sources(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/AAPL")
    section = resp.json()["sections"][0]

    assert section["claims"][0]["description"] == "Trailing P/E"
    assert section["claims"][0]["value"] == 28.5
    assert section["claims"][0]["source"]["tool"] == "test.tool"
    assert section["confidence"] == "high"


# ── Error mapping ────────────────────────────────────────────────────


async def test_invalid_focus_returns_422(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FastAPI auto-validates the Focus enum query param."""
    _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/AAPL?focus=quantum")

    assert resp.status_code == 422


async def test_runtime_error_from_orchestrator_returns_503(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E.g. ANTHROPIC_API_KEY missing — surface as 503, not 500.

    503 communicates "service is up but a dependency is unavailable",
    which is the right shape for an LLM-backed endpoint when the LLM
    provider is down or misconfigured.
    """
    _patch_orchestrator(
        monkeypatch,
        RuntimeError("ANTHROPIC_API_KEY is not set."),
    )

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 503
    body = resp.json()
    # RFC 7807 problem+json shape from app.core.errors. The HTTPException
    # handler maps a string ``detail`` arg into the problem+json
    # ``title`` field (and leaves ``detail`` null), per the convention
    # in app/core/errors.py.
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert "ANTHROPIC_API_KEY" in body["title"]


async def test_unexpected_exception_propagates_to_500(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unanticipated errors render as RFC 7807 500, not bare exceptions."""
    _patch_orchestrator(
        monkeypatch,
        ValueError("something unexpected"),
    )

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")


# ── Symbol validation ────────────────────────────────────────────────


async def test_empty_symbol_returns_404_or_422(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty path segment is a routing-level miss, not a 200."""
    _patch_orchestrator(monkeypatch, _stub_report())

    resp = await research_client.post("/v1/research/")

    # FastAPI returns 404 (no route) or 405 (wrong method on root) — both
    # are acceptable; the point is "not 200".
    assert resp.status_code in (404, 405, 422)


# ── Same-day cache integration (Phase 2.2b) ──────────────────────────


async def test_cache_hit_skips_orchestrator(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache lookup returns a row → orchestrator must NOT be called."""
    cached = _stub_report()
    cached.sections[0].summary = "Cached summary, served from DB."
    _patch_cache_lookup(monkeypatch, returns=cached)

    orch_calls = _patch_orchestrator(monkeypatch, _stub_report())  # would crash if hit
    upserts = _patch_cache_upsert(monkeypatch)

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 200
    assert resp.json()["sections"][0]["summary"] == "Cached summary, served from DB."
    assert orch_calls == [], "orchestrator must not run on a cache hit"
    assert upserts == [], "upsert must not run on a cache hit (we'd be writing the same row)"


async def test_cache_miss_runs_orchestrator_and_upserts(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache lookup returns None → orchestrator runs, fresh report is upserted."""
    fresh = _stub_report()
    fresh.sections[0].summary = "Fresh from Sonnet."
    _patch_orchestrator(monkeypatch, fresh)
    upserts = _patch_cache_upsert(monkeypatch)

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 200
    assert resp.json()["sections"][0]["summary"] == "Fresh from Sonnet."
    assert len(upserts) == 1
    assert upserts[0]["symbol"] == "AAPL"
    assert upserts[0]["focus"] == "full"
    # The upserted report is the one we just synthesized.
    assert upserts[0]["report"].sections[0].summary == "Fresh from Sonnet."


async def test_refresh_skips_lookup_and_writes(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?refresh=true`` skips the lookup but still upserts the fresh report."""
    cached = _stub_report()
    cached.sections[0].summary = "Stale cached summary."
    lookups = _patch_cache_lookup(monkeypatch, returns=cached)

    fresh = _stub_report()
    fresh.sections[0].summary = "Force-refreshed summary."
    _patch_orchestrator(monkeypatch, fresh)
    upserts = _patch_cache_upsert(monkeypatch)

    resp = await research_client.post("/v1/research/AAPL?refresh=true")

    assert resp.status_code == 200
    assert resp.json()["sections"][0]["summary"] == "Force-refreshed summary."
    # Lookup must not have run when refresh=true.
    assert lookups == [], "refresh=true must skip the cache lookup"
    # The fresh report still gets written to the cache.
    assert len(upserts) == 1


async def test_cache_lookup_uses_settings_max_age_hours(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The router threads ``settings.RESEARCH_CACHE_MAX_AGE_HOURS`` to lookup."""
    from app.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "RESEARCH_CACHE_MAX_AGE_HOURS", 24)
    lookups = _patch_cache_lookup(monkeypatch, returns=None)
    _patch_orchestrator(monkeypatch, _stub_report())

    await research_client.post("/v1/research/AAPL?focus=earnings")

    assert lookups[0]["max_age_hours"] == 24
    assert lookups[0]["focus"] == "earnings"


async def test_orchestrator_failure_does_not_upsert(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If synthesis raises, no row is written to the cache.

    We don't want a transient LLM-down state poisoned into the cache.
    Next request retries cleanly.
    """
    _patch_orchestrator(monkeypatch, RuntimeError("ANTHROPIC_API_KEY missing"))
    upserts = _patch_cache_upsert(monkeypatch)

    resp = await research_client.post("/v1/research/AAPL")

    assert resp.status_code == 503
    assert upserts == [], "must not cache failed orchestrations"


async def test_cache_focus_is_keyed_separately(
    research_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache key includes ``focus`` — full vs earnings are distinct."""
    lookups = _patch_cache_lookup(monkeypatch, returns=None)
    _patch_orchestrator(monkeypatch, _stub_report())
    _patch_cache_upsert(monkeypatch)

    await research_client.post("/v1/research/AAPL?focus=full")
    await research_client.post("/v1/research/AAPL?focus=earnings")

    assert [lookup["focus"] for lookup in lookups] == ["full", "earnings"]
