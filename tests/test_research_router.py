"""
Tests for ``POST /v1/research/{symbol}``.

The router itself is thin — parse query, call orchestrator, return
the schema. The orchestrator is mocked at the router's import
boundary so these tests exercise routing, query validation, error
mapping, and response shape, NOT the orchestration logic (covered
in test_research_orchestrator.py).

The shared ``client`` fixture in conftest is DB-bound; this router
doesn't touch the DB, so we wire a local ASGI client that skips the
DB session setup. Keeps the test independent of postgres availability.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.research import (
    Claim,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from app.services import research_orchestrator as orch_module


@pytest_asyncio.fixture
async def research_client() -> AsyncIterator[AsyncClient]:
    """ASGI client wired straight to the FastAPI app — no DB.

    ``raise_app_exceptions=False`` lets unhandled exceptions get
    converted to 500 problem+json responses by the global handler in
    app.core.errors, which is what we want to assert on. With the
    default (raise=True) the test client just re-raises into the
    test, masking the actual response shape.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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
