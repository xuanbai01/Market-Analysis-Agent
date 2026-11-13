"""
The public read-only demo (app/api/v1/routers/demo.py, 2026-11).

These are the only routes that answer without the shared secret and
return report data, so the tests are about the fence: only the tickers
the operator listed, only what is already stored, and never a call that
costs money or reaches a provider.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_module
from app.db.models.candles import Candle
from app.db.models.research_reports import ResearchReportRow
from app.db.models.symbols import Symbol
from app.schemas.research import Claim, Confidence, ResearchReport, Section, Source
from app.services import demo

_SECRET = "the-secret"


def _report(symbol: str, generated_at: datetime, *, name: str | None = None) -> ResearchReport:
    src = Source(tool="test.tool", fetched_at=generated_at)
    return ResearchReport(
        symbol=symbol,
        name=name,
        generated_at=generated_at,
        sections=[
            Section(
                title="Valuation",
                claims=[Claim(description="Trailing P/E", value=28.5, source=src)],
                summary="Trades at 28.5x trailing earnings.",
                confidence=Confidence.HIGH,
            )
        ],
        overall_confidence=Confidence.HIGH,
    )


async def _store(db: AsyncSession, report: ResearchReport, *, focus: str = "full") -> None:
    db.add(
        ResearchReportRow(
            symbol=report.symbol,
            focus=focus,
            report_date=report.generated_at.date(),
            report_json=report.model_dump(mode="json"),
            generated_at=report.generated_at,
        )
    )
    await db.flush()


async def _seed_candles(db: AsyncSession, symbol: str, days: int) -> None:
    end = datetime.now(UTC)
    db.add(Symbol(symbol=symbol, name=f"{symbol} test"))
    await db.flush()
    db.add_all(
        Candle(
            symbol=symbol,
            ts=end - timedelta(days=days - 1 - i),
            interval="1d",
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("100") + Decimal(i),
            volume=1_000_000,
        )
        for i in range(days)
    )
    await db.flush()


@pytest.fixture(autouse=True)
def _demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """KO and NVDA are the demo tickers; the API is otherwise locked."""
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "ko, NVDA")
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", _SECRET)
    demo.clear_cache()


@pytest.fixture(autouse=True)
def _no_spending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any path to the LLM or a data provider fails the test."""
    from app.services import market_prices, research_orchestrator

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the demo must never generate a report or call a provider")

    monkeypatch.setattr(research_orchestrator, "compose_research_report", _boom)
    monkeypatch.setattr(market_prices, "ingest_market_data", _boom)


# ── Which tickers ────────────────────────────────────────────────────


def test_demo_symbols_are_parsed_uppercased_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", " ko,NVDA , ko,, brk-b ")
    assert demo.demo_symbols() == ("KO", "NVDA", "BRK-B")


def test_an_empty_setting_means_no_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "")
    assert demo.demo_symbols() == ()


def test_a_malformed_entry_is_dropped_not_served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "KO,../etc,WAYTOOLONGTICKERNAME,A B")
    assert demo.demo_symbols() == ("KO",)


# ── Reports ──────────────────────────────────────────────────────────


async def test_a_demo_ticker_is_served_without_the_secret(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)))

    resp = await client.get("/v1/demo/research/KO")

    assert resp.status_code == 200
    assert resp.json()["symbol"] == "KO"


async def test_the_symbol_is_case_insensitive(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)))
    assert (await client.get("/v1/demo/research/ko")).status_code == 200


async def test_a_ticker_off_the_list_is_not_found_even_when_a_report_is_stored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _store(db_session, _report("AAPL", datetime.now(UTC)))

    resp = await client.get("/v1/demo/research/AAPL")

    assert resp.status_code == 404


async def test_a_demo_ticker_with_no_stored_report_is_not_found_and_nothing_is_generated(
    client: AsyncClient,
) -> None:
    # ``_no_spending`` would fail the test if this reached the orchestrator.
    assert (await client.get("/v1/demo/research/NVDA")).status_code == 404


async def test_the_latest_report_is_served_however_old(client: AsyncClient, db_session: AsyncSession) -> None:
    """The signed-in route rebuilds a report past its cache window. The
    demo cannot rebuild, so it shows what there is, with its date."""
    now = datetime.now(UTC)
    await _store(db_session, _report("KO", now - timedelta(days=90), name="older"))
    await _store(db_session, _report("KO", now - timedelta(days=40), name="newer"))

    body = (await client.get("/v1/demo/research/KO")).json()

    assert body["name"] == "newer"


async def test_only_full_reports_are_served(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)), focus="earnings")
    assert (await client.get("/v1/demo/research/KO")).status_code == 404


async def test_the_real_research_route_still_needs_the_secret(client: AsyncClient) -> None:
    assert (await client.post("/v1/research/KO")).status_code == 401
    assert (await client.get("/v1/research")).status_code == 401


# ── Index ────────────────────────────────────────────────────────────


async def test_the_index_lists_demo_tickers_that_have_a_report(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _store(db_session, _report("KO", datetime(2026, 11, 1, 12, tzinfo=UTC), name="The Coca-Cola Company"))
    await _store(db_session, _report("AAPL", datetime.now(UTC)))  # stored, not on the list

    resp = await client.get("/v1/demo")

    assert resp.status_code == 200
    assert resp.json() == {
        "symbols": [
            {"symbol": "KO", "name": "The Coca-Cola Company", "generated_at": "2026-11-01T12:00:00Z"}
        ]
    }


async def test_with_the_demo_off_everything_is_closed(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "")
    await _store(db_session, _report("KO", datetime.now(UTC)))

    assert (await client.get("/v1/demo")).json() == {"symbols": []}
    assert (await client.get("/v1/demo/research/KO")).status_code == 404
    assert (await client.get("/v1/demo/market/KO/prices")).status_code == 404


# ── Prices ───────────────────────────────────────────────────────────


async def test_stored_prices_are_served_for_a_demo_ticker(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_candles(db_session, "KO", days=30)

    resp = await client.get("/v1/demo/market/KO/prices?range=60D")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "KO"
    assert len(body["prices"]) == 30
    assert body["latest"]["close"] == pytest.approx(129.0)


async def test_missing_prices_come_back_empty_instead_of_being_fetched(client: AsyncClient) -> None:
    """The signed-in route fetches from Yahoo on a miss; the demo doesn't."""
    resp = await client.get("/v1/demo/market/KO/prices?range=1Y")

    assert resp.status_code == 200
    assert resp.json()["prices"] == []


async def test_prices_for_a_ticker_off_the_list_are_not_found(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_candles(db_session, "AAPL", days=30)
    assert (await client.get("/v1/demo/market/AAPL/prices")).status_code == 404


async def test_an_unknown_price_range_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/v1/demo/market/KO/prices?range=banana")).status_code == 422


# ── Repeat requests don't reach the database ─────────────────────────


async def test_a_repeated_request_is_answered_from_memory(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open route can be hit in a loop; it must not turn into a
    database query per request."""
    from app.services import research_cache

    await _store(db_session, _report("KO", datetime.now(UTC)))
    calls = 0
    real = research_cache.lookup_latest

    async def _counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr(research_cache, "lookup_latest", _counting)

    for _ in range(5):
        assert (await client.get("/v1/demo/research/KO")).status_code == 200
    assert calls == 1
