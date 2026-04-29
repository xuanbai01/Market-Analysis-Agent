"""
Tests for ``GET /v1/research`` — paginated list of past reports.

The dashboard sidebar reads this to show "your past N reports" with
metadata only (NOT the full report blob — clicks fetch the full report
via the existing ``POST /v1/research/{symbol}`` cache hit).

DB-bound: the conftest ``client`` fixture wires a per-test session
that's rolled back after each test. We seed rows via direct SQL
``upsert`` and then exercise the route.

Auth coverage is light here — the dep is the same one ``test_auth.py``
exercises in depth. We just verify it's wired and that the no-secret
default lets requests through.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_module
from app.schemas.research import (
    Claim,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from app.services import research_cache as cache_module


def _src() -> Source:
    return Source(tool="test.tool", fetched_at=datetime.now(UTC))


def _report(*, symbol: str = "AAPL", confidence: Confidence = Confidence.HIGH) -> ResearchReport:
    return ResearchReport(
        symbol=symbol,
        generated_at=datetime.now(UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[Claim(description="P/E", value=28.5, source=_src())],
                summary="OK.",
                confidence=confidence,
            ),
        ],
        overall_confidence=confidence,
    )


async def _seed(
    session: AsyncSession,
    *,
    symbol: str,
    focus: str,
    report_date: date,
    generated_at: datetime,
    confidence: Confidence = Confidence.HIGH,
) -> None:
    """Seed one report row at a known generated_at."""
    rep = _report(symbol=symbol, confidence=confidence).model_copy(
        update={"generated_at": generated_at}
    )
    await cache_module.upsert(
        session,
        symbol=symbol,
        focus=focus,
        report_date=report_date,
        report=rep,
    )
    await session.flush()


# ── Empty / happy paths ──────────────────────────────────────────────


async def test_empty_db_returns_empty_list(client: AsyncClient) -> None:
    resp = await client.get("/v1/research")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_returns_summary_shape_no_full_report(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Each row carries (symbol, focus, report_date, generated_at,
    overall_confidence) — NOT the full sections/claims tree."""
    await _seed(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        generated_at=datetime.now(UTC) - timedelta(hours=2),
        confidence=Confidence.HIGH,
    )

    resp = await client.get("/v1/research")
    body = resp.json()

    assert resp.status_code == 200
    assert len(body) == 1
    row = body[0]
    assert row["symbol"] == "AAPL"
    assert row["focus"] == "full"
    assert row["report_date"] == "2026-04-29"
    assert row["overall_confidence"] == "high"
    # No leak of the full report — list endpoint stays cheap.
    assert "sections" not in row
    assert "claims" not in row


async def test_orders_by_generated_at_desc(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Newest first, regardless of insert order."""
    await _seed(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today() - timedelta(days=3),
        generated_at=datetime.now(UTC) - timedelta(hours=72),
    )
    await _seed(
        db_session, symbol="NVDA", focus="full",
        report_date=date.today(),
        generated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await _seed(
        db_session, symbol="MSFT", focus="full",
        report_date=date.today() - timedelta(days=1),
        generated_at=datetime.now(UTC) - timedelta(hours=24),
    )

    resp = await client.get("/v1/research")
    body = resp.json()

    assert [r["symbol"] for r in body] == ["NVDA", "MSFT", "AAPL"]


# ── Filters + pagination ─────────────────────────────────────────────


async def test_filter_by_symbol(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(),
        generated_at=datetime.now(UTC),
    )
    await _seed(
        db_session, symbol="NVDA", focus="full",
        report_date=date.today(),
        generated_at=datetime.now(UTC),
    )

    resp = await client.get("/v1/research?symbol=AAPL")
    body = resp.json()

    assert [r["symbol"] for r in body] == ["AAPL"]


async def test_symbol_filter_uppercased(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The route uppercases the symbol filter so ``aapl`` finds AAPL rows."""
    await _seed(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(),
        generated_at=datetime.now(UTC),
    )

    resp = await client.get("/v1/research?symbol=aapl")

    assert resp.status_code == 200
    assert [r["symbol"] for r in resp.json()] == ["AAPL"]


async def test_pagination_limit_and_offset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for i, sym in enumerate(["A", "B", "C", "D", "E"]):
        await _seed(
            db_session, symbol=sym, focus="full",
            report_date=date.today() - timedelta(days=10 - i),
            # Older to newer: A oldest, E newest. List is newest-first.
            generated_at=datetime.now(UTC) - timedelta(hours=10 - i),
        )

    page1 = await client.get("/v1/research?limit=2&offset=0")
    page2 = await client.get("/v1/research?limit=2&offset=2")
    page3 = await client.get("/v1/research?limit=2&offset=4")

    assert [r["symbol"] for r in page1.json()] == ["E", "D"]
    assert [r["symbol"] for r in page2.json()] == ["C", "B"]
    assert [r["symbol"] for r in page3.json()] == ["A"]


async def test_default_limit_is_20(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No-arg call should return at most 20 rows."""
    for i in range(25):
        # 25 unique symbols (A1, A2, ... A25) — distinct PKs.
        await _seed(
            db_session, symbol=f"A{i:02d}", focus="full",
            report_date=date.today() - timedelta(days=i),
            generated_at=datetime.now(UTC) - timedelta(hours=i),
        )

    resp = await client.get("/v1/research")

    assert len(resp.json()) == 20


async def test_limit_above_max_returns_422(client: AsyncClient) -> None:
    """``limit`` is capped at 100 — anything higher fails validation."""
    resp = await client.get("/v1/research?limit=999")
    assert resp.status_code == 422


async def test_negative_offset_returns_422(client: AsyncClient) -> None:
    resp = await client.get("/v1/research?offset=-1")
    assert resp.status_code == 422


# ── Auth ─────────────────────────────────────────────────────────────


async def test_auth_enforced_when_secret_set(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With BACKEND_SHARED_SECRET set, no header → 401."""
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await client.get("/v1/research")
    assert resp.status_code == 401


async def test_auth_passes_with_correct_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await client.get(
        "/v1/research",
        headers={"Authorization": "Bearer the-secret"},
    )
    assert resp.status_code == 200
